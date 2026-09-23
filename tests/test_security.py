import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-at-least-32-characters")

from sqlalchemy.exc import IntegrityError

from auth_helpers import login_client, logout_client
from app import create_app
from models import PortfolioItem, Stock, User, db
from order_validation import (
    MAX_DATABASE_INTEGER,
    OrderValidationError,
    calculate_order_total,
)


class SecurityTestCase(unittest.TestCase):
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
        self.user1 = User.query.filter_by(nickname="user1").one()
        self.user2 = User.query.filter_by(nickname="user2").one()
        self.stock = Stock.query.filter_by(company_name="회사 A").one()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def login(self, nickname="user1"):
        login_client(self.client, nickname)
        with self.client.session_transaction() as test_session:
            return test_session["csrf_token"]

    def test_secret_key_is_required(self):
        with self.assertRaises(RuntimeError):
            create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": None,
                    "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                }
            )

    def test_post_order_rejects_missing_csrf_token(self):
        self.login()

        response = self.client.post(
            "/api/orders/buy",
            json={"stock_id": self.stock.id, "quantity": 1},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_CSRF_TOKEN")
        self.assertEqual(PortfolioItem.query.count(), 0)
        self.assertEqual(db.session.get(User, self.user1.id).cash, 1_000_000)

    def test_order_ignores_client_user_id(self):
        csrf_token = self.login("user1")

        response = self.client.post(
            "/api/orders/buy",
            json={
                "stock_id": self.stock.id,
                "quantity": 1,
                "user_id": self.user2.id,
                "price": 1,
            },
            headers={"X-CSRF-Token": csrf_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(
            PortfolioItem.query.filter_by(
                user_id=self.user1.id, stock_id=self.stock.id
            ).first()
        )
        self.assertIsNone(
            PortfolioItem.query.filter_by(
                user_id=self.user2.id, stock_id=self.stock.id
            ).first()
        )

    def test_invalid_session_user_is_rejected(self):
        with self.client.session_transaction() as test_session:
            test_session["user_id"] = 999_999
            test_session["csrf_token"] = "forged-token"

        web_response = self.client.get("/portfolio")
        api_response = self.client.get("/api/stocks")

        self.assertEqual(web_response.status_code, 302)
        self.assertEqual(api_response.status_code, 401)

    def test_database_constraints_reject_invalid_portfolio_state(self):
        self.user1.cash = -1
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(
            PortfolioItem(
                user_id=self.user1.id,
                stock_id=self.stock.id,
                quantity=-1,
                average_price=0,
            )
        )
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_order_total_cannot_exceed_database_integer_range(self):
        with self.assertRaises(OrderValidationError) as error_context:
            calculate_order_total(price=MAX_DATABASE_INTEGER, quantity=2)

        self.assertEqual(
            error_context.exception.code,
            "ORDER_TOTAL_TOO_LARGE",
        )

    def test_database_rejects_duplicate_and_unknown_foreign_keys(self):
        db.session.add(
            PortfolioItem(
                user_id=self.user1.id,
                stock_id=self.stock.id,
                quantity=1,
                average_price=self.stock.current_price,
            )
        )
        db.session.commit()
        db.session.add(
            PortfolioItem(
                user_id=self.user1.id,
                stock_id=self.stock.id,
                quantity=1,
                average_price=self.stock.current_price,
            )
        )
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.add(
            PortfolioItem(
                user_id=999_999,
                stock_id=self.stock.id,
                quantity=1,
                average_price=self.stock.current_price,
            )
        )
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()


if __name__ == "__main__":
    unittest.main()
