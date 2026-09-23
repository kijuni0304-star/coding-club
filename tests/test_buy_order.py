import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-at-least-32-characters")

from auth_helpers import login_client, logout_client
from app import create_app
from models import PortfolioItem, Stock, Transaction, User, db


class BuyOrderTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            }
        )
        self.context = self.app.app_context()
        self.context.push()
        self.client = self.app.test_client()

        self.user = User.query.filter_by(nickname="user1").one()
        self.stock = Stock.query.filter_by(company_name="회사 A").one()
        self.user_id = self.user.id
        self.stock_id = self.stock.id
        self.stock.current_price = 10_000
        self.stock.previous_price = 10_000
        db.session.commit()
        login_client(self.client, "user1")
        with self.client.session_transaction() as test_session:
            self.csrf_token = test_session["csrf_token"]

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def post_buy(self, **overrides):
        payload = {"stock_id": self.stock_id, "quantity": 1}
        payload.update(overrides)
        return self.client.post(
            "/api/orders/buy",
            json=payload,
            headers={"X-CSRF-Token": self.csrf_token},
        )

    def test_buy_requires_login(self):
        logout_client(self.client)

        response = self.post_buy()

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.get_json()["error"]["code"], "AUTHENTICATION_REQUIRED"
        )
        self.assertEqual(PortfolioItem.query.count(), 0)
        self.assertEqual(Transaction.query.count(), 0)

    def test_buy_uses_server_price_and_updates_all_records(self):
        db.session.add(
            PortfolioItem(
                user_id=self.user_id,
                stock_id=self.stock_id,
                quantity=2,
                average_price=8_000,
            )
        )
        db.session.commit()

        response = self.post_buy(quantity=3, price=1, total_amount=3)

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertTrue(result["success"])
        self.assertEqual(result["order"]["price"], 10_000)
        self.assertEqual(result["order"]["total_amount"], 30_000)
        self.assertEqual(result["order"]["remaining_cash"], 970_000)

        user = db.session.get(User, self.user_id)
        holding = PortfolioItem.query.filter_by(
            user_id=self.user_id, stock_id=self.stock_id
        ).one()
        transaction = Transaction.query.one()
        self.assertEqual(user.cash, 970_000)
        self.assertEqual(holding.quantity, 5)
        self.assertEqual(holding.average_price, 9_200)
        self.assertEqual(transaction.transaction_type, "BUY")
        self.assertEqual(transaction.quantity, 3)
        self.assertEqual(transaction.price, 10_000)
        self.assertEqual(transaction.total_amount, 30_000)

    def test_buy_rejects_insufficient_cash_without_changes(self):
        response = self.post_buy(quantity=101)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "INSUFFICIENT_CASH")
        self.assertEqual(db.session.get(User, self.user_id).cash, 1_000_000)
        self.assertEqual(PortfolioItem.query.count(), 0)
        self.assertEqual(Transaction.query.count(), 0)

    def test_buy_rejects_invalid_quantity_and_stock(self):
        for quantity in (0, -1, 1.5, True, 1_000_001):
            with self.subTest(quantity=quantity):
                response = self.post_buy(quantity=quantity)
                self.assertEqual(response.status_code, 400)

        response = self.post_buy(stock_id=999999)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"]["code"], "STOCK_NOT_FOUND")

    def test_buy_accepts_valid_form_data(self):
        response = self.client.post(
            "/api/orders/buy",
            data={"stock_id": str(self.stock_id), "quantity": "2"},
            headers={"X-CSRF-Token": self.csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["order"]["total_amount"], 20_000)
        holding = PortfolioItem.query.filter_by(
            user_id=self.user_id, stock_id=self.stock_id
        ).one()
        self.assertEqual(holding.quantity, 2)
        self.assertEqual(holding.average_price, 10_000)

    def test_mid_transaction_error_rolls_everything_back(self):
        with (
            patch("order_service.Transaction", side_effect=RuntimeError("boom")),
            patch.object(self.app.logger, "exception"),
        ):
            response = self.post_buy(quantity=2)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(db.session.get(User, self.user_id).cash, 1_000_000)
        self.assertEqual(PortfolioItem.query.count(), 0)
        self.assertEqual(Transaction.query.count(), 0)


if __name__ == "__main__":
    unittest.main()
