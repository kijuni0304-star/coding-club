"""거래 기록을 화면 표시용 데이터로 변환하는 서비스."""

from datetime import timezone
from zoneinfo import ZoneInfo


KOREA_TIMEZONE = ZoneInfo("Asia/Seoul")


def build_transaction_history(transactions):
    """최신순 ORM 거래 기록을 템플릿 표시용 목록으로 변환한다."""
    return [build_transaction_history_item(transaction) for transaction in transactions]


def build_transaction_history_item(transaction):
    """한 건의 거래 기록에 회사명, 한국 시간, 금액 표시를 추가한다."""
    transaction_type = transaction.transaction_type
    return {
        "id": transaction.id,
        "company_name": transaction.stock.company_name,
        "created_at_display": _format_korea_time(transaction.created_at),
        "transaction_type": transaction_type,
        "transaction_type_label": {"BUY": "매수", "SELL": "매도"}.get(
            transaction_type, "거래"
        ),
        "transaction_type_class": {"BUY": "buy", "SELL": "sell"}.get(
            transaction_type, "neutral"
        ),
        "quantity": transaction.quantity,
        "quantity_display": f"{transaction.quantity:,}",
        "price": transaction.price,
        "price_display": f"{transaction.price:,}",
        "total_amount": transaction.total_amount,
        "total_amount_display": f"{transaction.total_amount:,}",
    }


def _format_korea_time(value):
    """UTC로 저장된 거래 시각을 한국 시간 문자열로 표시한다."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KOREA_TIMEZONE).strftime("%Y.%m.%d %H:%M")
