import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-at-least-32-characters")

from auth_helpers import login_client, logout_client
from app import create_app
from models import PortfolioItem, Stock, User, db


class PortfolioRouteTestCase(unittest.TestCase):
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
        self.stock_a = Stock.query.filter_by(company_name="회사 A").one()
        self.stock_b = Stock.query.filter_by(company_name="회사 B").one()
        self.user.cash = 900_000
        self.stock_a.current_price = 12_000
        self.stock_b.current_price = 15_000
        db.session.add_all(
            [
                PortfolioItem(
                    user_id=self.user.id,
                    stock_id=self.stock_a.id,
                    quantity=5,
                    average_price=10_000,
                ),
                PortfolioItem(
                    user_id=self.user.id,
                    stock_id=self.stock_b.id,
                    quantity=0,
                    average_price=0,
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

    def test_portfolio_renders_database_totals_and_excludes_zero_quantity(self):
        response = self.client.get("/portfolio")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("900,000원", page)
        self.assertIn("60,000원", page)
        self.assertIn("960,000", page)
        self.assertIn("+10,000원 (+20.00%)", page)
        self.assertIn("회사 A", page)
        self.assertIn("보유 5주 · 평균 10,000원", page)
        self.assertIn("평가 60,000원", page)
        self.assertNotIn("회사 B", page)


if __name__ == "__main__":
    unittest.main()
