import unittest
from types import SimpleNamespace

from portfolio_service import (
    build_portfolio_item_data,
    calculate_holding_metrics,
    calculate_portfolio_summary,
)


class PortfolioServiceTestCase(unittest.TestCase):
    def test_calculates_holding_metrics_from_average_and_current_price(self):
        metrics = calculate_holding_metrics(
            quantity=5,
            average_price=10_000,
            current_price=12_000,
        )

        self.assertEqual(metrics.quantity, 5)
        self.assertEqual(metrics.average_price, 10_000)
        self.assertEqual(metrics.purchase_value, 50_000)
        self.assertEqual(metrics.current_price, 12_000)
        self.assertEqual(metrics.market_value, 60_000)
        self.assertEqual(metrics.profit_loss, 10_000)
        self.assertEqual(metrics.profit_loss_percent, 20.0)

    def test_zero_quantity_does_not_raise_or_divide_by_zero(self):
        metrics = calculate_holding_metrics(
            quantity=0,
            average_price=0,
            current_price=12_000,
        )

        self.assertEqual(metrics.purchase_value, 0)
        self.assertEqual(metrics.market_value, 0)
        self.assertEqual(metrics.profit_loss, 0)
        self.assertEqual(metrics.profit_loss_percent, 0.0)

    def test_zero_average_price_has_zero_percent_return(self):
        metrics = calculate_holding_metrics(
            quantity=3,
            average_price=0,
            current_price=12_000,
        )

        self.assertEqual(metrics.purchase_value, 0)
        self.assertEqual(metrics.market_value, 36_000)
        self.assertEqual(metrics.profit_loss, 36_000)
        self.assertEqual(metrics.profit_loss_percent, 0.0)

    def test_builds_display_data_without_template_calculations(self):
        portfolio_item = SimpleNamespace(
            quantity=2,
            average_price=10_000,
            stock=SimpleNamespace(id=7, company_name="회사 G", current_price=9_000),
        )

        data = build_portfolio_item_data(portfolio_item)

        self.assertEqual(data["stock_id"], 7)
        self.assertEqual(data["company_name"], "회사 G")
        self.assertEqual(data["purchase_value"], 20_000)
        self.assertEqual(data["market_value"], 18_000)
        self.assertEqual(data["profit_loss"], -2_000)
        self.assertEqual(data["profit_loss_percent"], -10.0)
        self.assertEqual(data["profit_loss_display"], "-2,000")
        self.assertEqual(data["profit_loss_percent_display"], "-10.00%")
        self.assertEqual(data["profit_loss_class"], "negative")

    def test_calculates_summary_from_cash_and_all_holdings(self):
        summary = calculate_portfolio_summary(
            cash=800_000,
            holdings=[
                {"purchase_value": 50_000, "market_value": 60_000},
                {"purchase_value": 20_000, "market_value": 18_000},
            ],
        )

        self.assertEqual(summary["cash"], 800_000)
        self.assertEqual(summary["stock_market_value"], 78_000)
        self.assertEqual(summary["total_asset"], 878_000)
        self.assertEqual(summary["profit_loss"], 8_000)
        self.assertEqual(summary["profit_loss_percent"], 11.43)
        self.assertEqual(summary["profit_loss_display"], "+8,000")
        self.assertEqual(summary["profit_loss_percent_display"], "+11.43%")
        self.assertEqual(summary["profit_loss_class"], "positive")

    def test_empty_portfolio_has_zero_return(self):
        summary = calculate_portfolio_summary(cash=1_000_000, holdings=[])

        self.assertEqual(summary["stock_market_value"], 0)
        self.assertEqual(summary["total_asset"], 1_000_000)
        self.assertEqual(summary["profit_loss"], 0)
        self.assertEqual(summary["profit_loss_percent"], 0.0)


if __name__ == "__main__":
    unittest.main()
