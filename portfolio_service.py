"""포트폴리오 평가 금액과 손익을 계산하는 도메인 서비스."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HoldingMetrics:
    """한 보유 종목의 수량·매입·평가 정보를 나타낸다.

    모든 금액은 원 단위 정수이며, 수익률만 퍼센트 실수이다.
    """

    quantity: int
    average_price: int
    purchase_value: int
    current_price: int
    market_value: int
    profit_loss: int
    profit_loss_percent: float


@dataclass(frozen=True)
class PortfolioSummary:
    """사용자 예수금과 보유 종목을 합산한 포트폴리오 요약 정보."""

    cash: int
    stock_market_value: int
    total_asset: int
    profit_loss: int
    profit_loss_percent: float


def calculate_holding_metrics(*, quantity, average_price, current_price):
    """수량, 평균 매수가, 현재가로 보유 종목의 평가 지표를 계산한다.

    공식:
    - 매입 금액 = 보유 수량 × 평균 매수가
    - 평가 금액 = 보유 수량 × 현재가
    - 평가 손익 = 평가 금액 - 매입 금액
    - 수익률 = 평가 손익 ÷ 매입 금액 × 100

    매입 금액이 0원인 경우에는 수익률을 0.0%로 정의해 0 나누기를 막는다.
    """
    normalized_quantity = max(quantity or 0, 0)
    normalized_average_price = max(average_price or 0, 0)
    normalized_current_price = max(current_price or 0, 0)

    purchase_value = normalized_quantity * normalized_average_price
    market_value = normalized_quantity * normalized_current_price
    profit_loss = market_value - purchase_value
    profit_loss_percent = (
        round((profit_loss / purchase_value) * 100, 2)
        if purchase_value > 0
        else 0.0
    )

    return HoldingMetrics(
        quantity=normalized_quantity,
        average_price=normalized_average_price,
        purchase_value=purchase_value,
        current_price=normalized_current_price,
        market_value=market_value,
        profit_loss=profit_loss,
        profit_loss_percent=profit_loss_percent,
    )


def build_portfolio_item_data(portfolio_item):
    """ORM 보유 종목을 템플릿에서 바로 표시할 데이터로 변환한다."""
    metrics = calculate_holding_metrics(
        quantity=portfolio_item.quantity,
        average_price=portfolio_item.average_price,
        current_price=portfolio_item.stock.current_price,
    )

    data = asdict(metrics)
    data.update(
        stock_id=portfolio_item.stock.id,
        company_name=portfolio_item.stock.company_name,
        quantity_display=f"{metrics.quantity:,}",
        average_price_display=f"{metrics.average_price:,}",
        purchase_value_display=f"{metrics.purchase_value:,}",
        current_price_display=f"{metrics.current_price:,}",
        market_value_display=f"{metrics.market_value:,}",
        profit_loss_display=_signed_money(metrics.profit_loss),
        profit_loss_percent_display=_signed_percent(metrics.profit_loss_percent),
        profit_loss_class=_profit_loss_class(metrics.profit_loss),
    )
    return data


def build_portfolio_items(portfolio_items):
    """여러 ORM 보유 종목을 평가 데이터 목록으로 변환한다."""
    return [build_portfolio_item_data(item) for item in portfolio_items]


def calculate_portfolio_summary(*, cash, holdings):
    """예수금과 보유 종목 평가 데이터를 합산한다.

    공식:
    - 주식 총 평가금액 = 각 종목 평가금액의 합
    - 총자산 = 현재 예수금 + 주식 총 평가금액
    - 전체 평가손익 = 각 종목 평가손익의 합
    - 전체 수익률 = 전체 평가손익 ÷ 총 매입금액 × 100

    보유 종목이 없거나 총 매입금액이 0원이면 전체 수익률은 0.0%이다.
    """
    normalized_cash = max(cash or 0, 0)
    stock_market_value = sum(item["market_value"] for item in holdings)
    total_purchase_value = sum(item["purchase_value"] for item in holdings)
    profit_loss = stock_market_value - total_purchase_value
    profit_loss_percent = (
        round((profit_loss / total_purchase_value) * 100, 2)
        if total_purchase_value > 0
        else 0.0
    )
    summary = PortfolioSummary(
        cash=normalized_cash,
        stock_market_value=stock_market_value,
        total_asset=normalized_cash + stock_market_value,
        profit_loss=profit_loss,
        profit_loss_percent=profit_loss_percent,
    )

    data = asdict(summary)
    data.update(
        cash_display=f"{summary.cash:,}",
        stock_market_value_display=f"{summary.stock_market_value:,}",
        total_asset_display=f"{summary.total_asset:,}",
        profit_loss_display=_signed_money(summary.profit_loss),
        profit_loss_percent_display=_signed_percent(summary.profit_loss_percent),
        profit_loss_class=_profit_loss_class(summary.profit_loss),
    )
    return data


def _signed_money(amount):
    if amount > 0:
        return f"+{amount:,}"
    if amount < 0:
        return f"-{abs(amount):,}"
    return "0"


def _signed_percent(percent):
    if percent > 0:
        return f"+{percent:.2f}%"
    if percent < 0:
        return f"{percent:.2f}%"
    return "0.00%"


def _profit_loss_class(profit_loss):
    if profit_loss > 0:
        return "positive"
    if profit_loss < 0:
        return "negative"
    return "neutral"
