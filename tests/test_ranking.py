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
from models import Stock, db


class RankingTestCase(unittest.TestCase):
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

        self.stocks = {
            stock.company_name: stock for stock in Stock.query.order_by(Stock.id)
        }
        self.stocks["회사 A"].previous_price = 10_000
        self.stocks["회사 A"].current_price = 10_500  # +5%
        self.stocks["회사 B"].previous_price = 10_000
        self.stocks["회사 B"].current_price = 12_000  # +20%
        self.stocks["회사 C"].previous_price = 10_000
        self.stocks["회사 C"].current_price = 9_000  # -10%
        db.session.commit()
        login_client(self.client, "user1")

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
        self.context.pop()

    def test_ranking_renders_all_stocks_in_change_percent_descending_order(self):
        response = self.client.get("/ranking")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(page.count('class="stock-item"'), 10)
        self.assertLess(page.index("회사 B"), page.index("회사 A"))
        self.assertLess(page.index("회사 A"), page.index("회사 C"))
        self.assertIn('data-rank>1</span>', page)
        self.assertIn('data-rank>10</span>', page)

        for stock in self.stocks.values():
            self.assertIn(f'href="/order/{stock.id}"', page)

    def test_stocks_api_uses_the_same_ranked_database_values(self):
        response = self.client.get("/api/stocks")
        stocks = response.get_json()["stocks"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(stocks), 10)
        self.assertEqual(stocks[0]["company_name"], "회사 B")
        self.assertEqual(stocks[0]["change_percent"], 20.0)
        self.assertEqual(stocks[-1]["company_name"], "회사 C")
        self.assertEqual(stocks[-1]["change_percent"], -10.0)


if __name__ == "__main__":
    unittest.main()
