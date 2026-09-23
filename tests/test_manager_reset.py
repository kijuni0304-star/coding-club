import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-at-least-32-characters")

from app import INITIAL_CASH, INITIAL_STOCK_PRICES, create_app
from auth_helpers import login_client
from manager_auth import hash_manager_password
from models import PortfolioItem, PriceUpdateRun, Stock, Transaction, User, db
from order_service import execute_buy_order


class ManagerResetTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "manager-test-secret",
                "MANAGER_PASSWORD_HASH": hash_manager_password("test-manager-password"),
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            }
        )
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def csrf_token(self, client=None):
        with (client or self.client).session_transaction() as state:
            return state["csrf_token"]

    def test_manager_login_opens_separate_console(self):
        invalid = login_client(self.client, "manager", "incorrect")
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(self.client.get("/manager").status_code, 302)
        response = login_client(self.client, "manager", "test-manager-password")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/manager")
        page = self.client.get("/manager")
        self.assertEqual(page.status_code, 200)
        self.assertIn("전체 데이터 초기화".encode(), page.data)
        self.assertIsNone(User.query.filter_by(nickname="manager").first())
        self.assertEqual(self.client.get("/portfolio").headers["Location"], "/manager")

    def test_students_cannot_open_or_submit_manager_reset(self):
        self.assertEqual(self.client.get("/manager").status_code, 302)
        self.assertEqual(login_client(self.client, "user1", "wrong").status_code, 200)
        self.assertEqual(self.client.get("/portfolio").status_code, 302)
        login_client(self.client, "user1")
        self.assertEqual(self.client.get("/manager").status_code, 403)
        response = self.client.post(
            "/manager/reset",
            data={
                "csrf_token": self.csrf_token(),
                "confirmation": "전체 초기화",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(User.query.count(), 10)
        self.assertEqual(Stock.query.count(), 10)

    def test_reset_requires_csrf_and_exact_confirmation_then_restores_defaults(self):
        user = User.query.filter_by(nickname="user1").one()
        execute_buy_order(user_id=user.id, payload={"stock_id": 1, "quantity": 2})
        stock = db.session.get(Stock, 1)
        stock.current_price = 12_345
        stock.previous_price = 10_000
        db.session.add(PriceUpdateRun(minute_key="2026-09-23T12:00Z"))
        db.session.commit()

        login_client(self.client, "manager", "test-manager-password")
        self.assertEqual(self.client.get("/manager").status_code, 200)

        self.assertEqual(
            self.client.post(
                "/manager/reset", data={"confirmation": "전체 초기화"}
            ).status_code,
            403,
        )
        invalid = self.client.post(
            "/manager/reset",
            data={
                "csrf_token": self.csrf_token(),
                "confirmation": "RESET",
            },
        )
        self.assertEqual(invalid.status_code, 403)
        self.assertEqual(Transaction.query.count(), 1)
        self.assertEqual(PortfolioItem.query.count(), 1)

        response = self.client.post(
            "/manager/reset",
            data={
                "csrf_token": self.csrf_token(),
                "confirmation": "전체 초기화",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("reset=1", response.headers["Location"])
        page = self.client.get(response.headers["Location"])
        self.assertEqual(page.status_code, 200)
        self.assertIn("초기화가 완료됐습니다".encode(), page.data)

        self.assertEqual(User.query.count(), 10)
        self.assertTrue(all(user.cash == INITIAL_CASH for user in User.query.all()))
        self.assertEqual(Stock.query.count(), 10)
        self.assertEqual(PortfolioItem.query.count(), 0)
        self.assertEqual(Transaction.query.count(), 0)
        self.assertEqual(PriceUpdateRun.query.count(), 0)
        self.assertEqual(
            {stock.company_name: (stock.current_price, stock.previous_price)
             for stock in Stock.query.all()},
            {name: (price, price) for name, price in INITIAL_STOCK_PRICES.items()},
        )


if __name__ == "__main__":
    unittest.main()
