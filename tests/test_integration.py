"""임시 DB에서 인증 → 시장 → 매수/매도 → 자산/내역을 통합 검증한다."""

import os
import sys
import unittest
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "test-only-secret")

from auth_helpers import login_client, logout_client
from app import create_app, initialize_database
from models import db, User, Stock, PortfolioItem, Transaction, PriceUpdateRun
from order_service import execute_buy_order, execute_sell_order
from order_validation import OrderValidationError, MAX_DATABASE_INTEGER
from stock_price_updater import update_stock_prices

NOW = datetime(2026, 9, 13, 1, 0, tzinfo=timezone.utc)


def worker_init(barrier):
    global START
    START = barrier


def concurrent_work(args):
    uri, action = args
    app = create_app({"TESTING": True, "SECRET_KEY": "test", "SQLALCHEMY_DATABASE_URI": uri})
    with app.app_context():
        try:
            # 인증 단계처럼 잠금 전에 값을 읽어서 오래된 ORM 캐시도 검증한다.
            User.query.filter_by(nickname="user1").one()
            Stock.query.filter_by(company_name="회사 A").one()
            START.wait(timeout=20)
            if action == "market":
                return update_stock_prices(update_time=NOW, rate_generator=lambda: 0.20)
            if action == "seed":
                initialize_database()
                return True
            function = execute_sell_order if action == "sell" else execute_buy_order
            result = function(user_id=1, payload={"stock_id": 1, "quantity": 1})
            return {"price": result.price, "cash": result.remaining_cash}
        except OrderValidationError as error:
            return error.code
        finally:
            db.session.remove()
            db.engine.dispose()


def cold_start(uri):
    """빈 SQLite 파일을 여러 프로세스가 처음 여는 상황을 재현한다."""
    START.wait(timeout=20)
    app = create_app({
        "TESTING": True,
        "SECRET_KEY": "test",
        "SQLALCHEMY_DATABASE_URI": uri,
    })
    with app.app_context():
        try:
            return User.query.count(), Stock.query.count()
        finally:
            db.session.remove()
            db.engine.dispose()


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in {"href", "src"} and value.startswith("/"):
                self.urls.append(value)


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.uri = "sqlite:///" + (Path(self.temp.name) / "test.db").as_posix()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "SQLALCHEMY_DATABASE_URI": self.uri})
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()
        self.temp.cleanup()

    def headers(self, client=None):
        with (client or self.client).session_transaction() as state:
            return {"X-CSRF-Token": state["csrf_token"]}

    def run_concurrently(self, *actions):
        db.session.remove()
        context = get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=len(actions), mp_context=context,
            initializer=worker_init, initargs=(context.Barrier(len(actions)),),
        ) as pool:
            results = list(pool.map(concurrent_work, [(self.uri, a) for a in actions]))
        db.session.remove()
        return results

    def test_all_logins_and_session_boundaries(self):
        for i in range(1, 11):
            self.assertEqual(login_client(self.client, f"user{i}").status_code, 302)
            self.assertEqual(self.client.get("/portfolio").status_code, 200)
        token = self.headers()["X-CSRF-Token"]
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/logout").status_code, 403)
        self.assertEqual(logout_client(self.client).status_code, 302)
        for path in ("/ranking", "/portfolio", "/history", "/order", "/order/1"):
            self.assertEqual(self.client.get(path).status_code, 302)
        for endpoint in ("buy", "sell", "validate"):
            self.assertEqual(self.client.post("/api/orders/" + endpoint,
                             json={}, headers={"X-CSRF-Token": token}).status_code, 401)
        self.assertEqual(self.client.post("/", data={"nickname": "user1"}).status_code, 403)

    def test_buy_market_sell_and_user_isolation(self):
        login_client(self.client)
        other = self.app.test_client()
        login_client(other, "user2")
        buy = self.client.post("/api/orders/buy", json={
            "stock_id": 1, "quantity": 3, "price": 1, "user_id": 2,
        }, headers=self.headers())
        self.assertEqual(buy.get_json()["order"]["remaining_cash"], 970_000)
        self.assertTrue(update_stock_prices(update_time=NOW, rate_generator=lambda: 0.20))
        self.assertEqual(self.client.get("/api/stocks").json, other.get("/api/stocks").json)
        page = self.client.get("/portfolio").text
        self.assertIn("1,006,000", page)
        self.assertIn("+6,000원 (+20.00%)", page)
        self.assertNotIn("회사 A", other.get("/portfolio?user_id=1").text)
        self.assertNotIn("회사 A", other.get("/history?user_id=1").text)
        sell = self.client.post("/api/orders/sell", json={"stock_id": 1, "quantity": 3},
                                headers=self.headers())
        self.assertEqual(sell.json["order"]["remaining_cash"], 1_006_000)
        self.assertEqual(PortfolioItem.query.one().average_price, 0)
        self.assertNotIn("회사 A", self.client.get("/portfolio").text)
        self.assertEqual(Transaction.query.count(), 2)
        self.assertIn("36,000원", self.client.get("/history").text)

    def test_market_bounds_independence_duplicates_and_rollback(self):
        before = [(s.id, s.current_price) for s in Stock.query.order_by(Stock.id)]
        rates = iter([-0.20, 0.20, 0, 0.01, -0.01] * 2)
        expected_rates = [-0.20, 0.20, 0, 0.01, -0.01] * 2
        self.assertTrue(update_stock_prices(update_time=NOW, rate_generator=lambda: next(rates)))
        for (_, price), rate, stock in zip(before, expected_rates, Stock.query.order_by(Stock.id)):
            self.assertEqual(stock.previous_price, price)
            self.assertEqual(stock.current_price, max(1, round(price * (1 + rate))))
            self.assertEqual(stock.updated_at.replace(tzinfo=timezone.utc), NOW)
        self.assertFalse(update_stock_prices(update_time=NOW + timedelta(seconds=59),
                         rate_generator=lambda: self.fail("duplicate generated prices")))
        snapshot = [(s.current_price, s.previous_price) for s in Stock.query.order_by(Stock.id)]
        with patch("stock_price_updater.random.uniform", side_effect=[0.1, RuntimeError("failure")]):
            with self.assertRaises(RuntimeError):
                update_stock_prices(update_time=NOW + timedelta(minutes=1))
        self.assertEqual(snapshot, [(s.current_price, s.previous_price) for s in Stock.query.order_by(Stock.id)])
        self.assertEqual(PriceUpdateRun.query.count(), 1)
        self.assertTrue(update_stock_prices(update_time=NOW + timedelta(minutes=1), rate_generator=lambda: 0))
        stock = db.session.get(Stock, 1)
        stock.current_price = 1
        db.session.commit()
        update_stock_prices(update_time=NOW + timedelta(minutes=2), rate_generator=lambda: -0.2)
        self.assertEqual(db.session.get(Stock, 1).current_price, 1)

    def test_concurrent_buy_cannot_spend_cash_twice(self):
        db.session.get(User, 1).cash = 10_000
        db.session.commit()
        results = self.run_concurrently("buy", "buy")
        self.assertEqual(results.count("INSUFFICIENT_CASH"), 1)
        self.assertEqual(db.session.get(User, 1).cash, 0)
        self.assertEqual(PortfolioItem.query.one().quantity, 1)
        self.assertEqual(Transaction.query.count(), 1)

    def test_concurrent_sell_cannot_sell_same_share_twice(self):
        execute_buy_order(user_id=1, payload={"stock_id": 1, "quantity": 1})
        results = self.run_concurrently("sell", "sell")
        self.assertEqual(results.count("INSUFFICIENT_HOLDINGS"), 1)
        self.assertEqual(db.session.get(User, 1).cash, 1_000_000)
        self.assertEqual(PortfolioItem.query.one().quantity, 0)
        self.assertEqual(Transaction.query.count(), 2)

    def test_concurrent_market_only_one_update(self):
        results = self.run_concurrently("market", "market")
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(PriceUpdateRun.query.count(), 1)
        self.assertEqual(db.session.get(Stock, 1).current_price, 12_000)

    def test_concurrent_order_and_market_preserve_consistent_price(self):
        self.run_concurrently("buy", "market")
        transaction = Transaction.query.one()
        self.assertIn(transaction.price, (10_000, 12_000))
        self.assertEqual(db.session.get(User, 1).cash, 1_000_000 - transaction.price)
        self.assertEqual(PortfolioItem.query.one().average_price, transaction.price)
        self.assertEqual(db.session.get(Stock, 1).current_price, 12_000)

    def test_seed_is_idempotent_without_resetting_cash_or_prices(self):
        db.session.get(User, 1).cash = 321
        db.session.get(Stock, 1).current_price = 123
        db.session.commit()
        self.run_concurrently("seed", "seed")
        self.assertEqual(User.query.count(), 10)
        self.assertEqual(Stock.query.count(), 10)
        self.assertEqual(db.session.get(User, 1).cash, 321)
        self.assertEqual(db.session.get(Stock, 1).current_price, 123)

    def test_concurrent_first_start_creates_schema_and_seed_once(self):
        uri = "sqlite:///" + (Path(self.temp.name) / "new.db").as_posix()
        context = get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=2,
            mp_context=context,
            initializer=worker_init,
            initargs=(context.Barrier(2),),
        ) as pool:
            results = list(pool.map(cold_start, [uri, uri]))

        self.assertEqual(results, [(10, 10), (10, 10)])

    def test_invalid_inputs_http_errors_and_links(self):
        login_client(self.client)
        headers = self.headers()
        for data in ('[]', 'null', '{', '{"stock_id":1,"quantity":1,"quantity":2}'):
            response = self.client.post("/api/orders/buy", data=data,
                       content_type="application/json", headers=headers)
            self.assertEqual(response.status_code, 400)
        response = self.client.post("/api/orders/buy", data=' ' * 20_000,
                   content_type="application/json", headers=headers)
        self.assertEqual(response.status_code, 413)
        self.assertIsNotNone(response.json)
        self.assertEqual(self.client.post("/api/orders/buy", json={},
                         headers={"X-CSRF-Token": "가짜"}).status_code, 403)
        for path in ("/order/999999999999999999999", "/order?stock_id=abc", "/order/0"):
            self.assertEqual(self.client.get(path).status_code, 404)
        for path in ("/", "/ranking", "/portfolio", "/history", "/order/1"):
            page = self.client.get(path)
            parser = Links()
            parser.feed(page.text)
            for url in parser.urls:
                with self.client.get(url) as linked:
                    self.assertLess(linked.status_code, 400, url)
        self.assertEqual(Transaction.query.count(), 0)

    def test_precise_ranking_before_display_rounding(self):
        a, b = db.session.get(Stock, 1), db.session.get(Stock, 2)
        a.previous_price = b.previous_price = 100_000
        a.current_price, b.current_price = 101_001, 101_004
        db.session.commit()
        login_client(self.client)
        stocks = self.client.get("/api/stocks").json["stocks"]
        self.assertEqual(stocks[0]["id"], 2)
        self.assertEqual(stocks[0]["change_percent"], stocks[1]["change_percent"])


if __name__ == "__main__":
    unittest.main()
