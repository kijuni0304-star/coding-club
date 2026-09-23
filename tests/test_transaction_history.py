import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-at-least-32-characters")

from auth_helpers import login_client, logout_client
from app import create_app
from models import Stock, Transaction, User, db


class TransactionHistoryTestCase(unittest.TestCase):
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

        user1 = User.query.filter_by(nickname="user1").one()
        user2 = User.query.filter_by(nickname="user2").one()
        stock_a = Stock.query.filter_by(company_name="회사 A").one()
        stock_b = Stock.query.filter_by(company_name="회사 B").one()
        stock_c = Stock.query.filter_by(company_name="회사 C").one()
        db.session.add_all(
            [
                Transaction(
                    user_id=user1.id,
                    stock_id=stock_a.id,
                    transaction_type="SELL",
                    quantity=2,
                    price=10_000,
                    total_amount=20_000,
                    created_at=datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc),
                ),
                Transaction(
                    user_id=user1.id,
                    stock_id=stock_b.id,
                    transaction_type="BUY",
                    quantity=3,
                    price=12_000,
                    total_amount=36_000,
                    created_at=datetime(2026, 9, 13, 1, 10, tzinfo=timezone.utc),
                ),
                Transaction(
                    user_id=user2.id,
                    stock_id=stock_c.id,
                    transaction_type="BUY",
                    quantity=1,
                    price=15_000,
                    total_amount=15_000,
                    created_at=datetime(2026, 9, 13, 2, 0, tzinfo=timezone.utc),
                ),
            ]
        )
        db.session.commit()
        login_client(self.client, "user1")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def test_history_shows_only_current_user_transactions_newest_first(self):
        response = self.client.get("/history")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("회사 B", page)
        self.assertIn("매수", page)
        self.assertIn("3주 · 12,000원", page)
        self.assertIn("36,000원", page)
        self.assertIn("2026.09.13 10:10", page)
        self.assertIn('transaction-type buy', page)
        self.assertIn("회사 A", page)
        self.assertIn("매도", page)
        self.assertIn('transaction-type sell', page)
        self.assertNotIn("회사 C", page)
        self.assertLess(page.index("회사 B"), page.index("회사 A"))

    def test_history_requires_login(self):
        logout_client(self.client)

        response = self.client.get("/history")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
