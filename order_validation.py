import re
import json
from dataclasses import dataclass

from models import PortfolioItem, Stock, User, db


MAX_ORDER_QUANTITY = 1_000_000
MAX_DATABASE_INTEGER = 9_223_372_036_854_775_807
VALID_TRANSACTION_TYPES = {"BUY", "SELL"}
INTEGER_PATTERN = re.compile(r"[+-]?\d+")


class OrderValidationError(ValueError):
    def __init__(self, code, message, status_code=400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedOrder:
    user: User
    stock: Stock
    transaction_type: str
    quantity: int
    price: int
    total_amount: int
    owned_quantity: int

    def to_dict(self):
        return {
            "user_id": self.user.id,
            "stock_id": self.stock.id,
            "company_name": self.stock.company_name,
            "transaction_type": self.transaction_type,
            "quantity": self.quantity,
            "price": self.price,
            "total_amount": self.total_amount,
            "available_cash": self.user.cash,
            "owned_quantity": self.owned_quantity,
        }


def parse_integer(value, *, field_name, maximum=MAX_DATABASE_INTEGER):
    """JSON 정수 또는 form의 정수 문자열만 안전하게 변환한다."""
    if isinstance(value, bool):
        raise OrderValidationError(
            f"INVALID_{field_name.upper()}", f"{field_name}는 정수여야 합니다."
        )

    if isinstance(value, int):
        parsed_value = value
    elif isinstance(value, str):
        stripped_value = value.strip()
        if len(stripped_value) > 20 or not INTEGER_PATTERN.fullmatch(stripped_value):
            raise OrderValidationError(
                f"INVALID_{field_name.upper()}", f"{field_name}는 정수여야 합니다."
            )
        try:
            parsed_value = int(stripped_value)
        except ValueError as error:
            raise OrderValidationError(
                f"INVALID_{field_name.upper()}", f"{field_name}는 정수여야 합니다."
            ) from error
    else:
        raise OrderValidationError(
            f"INVALID_{field_name.upper()}", f"{field_name}는 정수여야 합니다."
        )

    if parsed_value > maximum:
        raise OrderValidationError(
            f"{field_name.upper()}_TOO_LARGE",
            f"{field_name} 값이 너무 큽니다.",
        )
    return parsed_value


def parse_order_payload(http_request):
    """JSON 또는 form 요청을 주문 데이터 딕셔너리로 변환한다."""
    if http_request.is_json:
        try:
            payload = json.loads(http_request.get_data(), object_pairs_hook=unique_fields)
        except (ValueError, RecursionError, UnicodeDecodeError):
            raise OrderValidationError("INVALID_REQUEST", "올바른 JSON 객체가 필요합니다.")
        if not isinstance(payload, dict):
            raise OrderValidationError(
                "INVALID_REQUEST", "올바른 JSON 객체가 필요합니다."
            )
        return payload

    if http_request.mimetype in {
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    }:
        if any(len(values) != 1 for _, values in http_request.form.lists()):
            raise OrderValidationError("INVALID_REQUEST", "중복된 주문 항목입니다.")
        return http_request.form.to_dict(flat=True)

    raise OrderValidationError(
        "INVALID_REQUEST",
        "JSON 또는 form 형식으로 주문 정보를 보내야 합니다.",
    )


def calculate_order_total(*, price, quantity):
    """검증된 서버 가격과 수량의 총액이 DB 정수 범위인지 확인한다."""
    if isinstance(price, bool) or not isinstance(price, int) or price < 1:
        raise OrderValidationError(
            "INVALID_SERVER_PRICE",
            "서버에 저장된 종목 가격이 올바르지 않습니다.",
            status_code=500,
        )

    total_amount = price * quantity
    if total_amount > MAX_DATABASE_INTEGER:
        raise OrderValidationError(
            "ORDER_TOTAL_TOO_LARGE",
            "주문 총액이 처리 가능한 범위를 초과했습니다.",
        )
    return total_amount


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("중복된 JSON 항목입니다.")
        result[key] = value
    return result


def validate_order_payload(*, user_id, payload):
    """DB를 변경하지 않고 주문 데이터와 현재 사용자 상태를 검증한다."""
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise OrderValidationError(
            "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.", status_code=401
        )

    user = db.session.get(User, user_id)
    if user is None:
        raise OrderValidationError(
            "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.", status_code=401
        )

    if not isinstance(payload, dict):
        raise OrderValidationError("INVALID_REQUEST", "잘못된 주문 요청입니다.")

    missing_fields = [
        field
        for field in ("stock_id", "transaction_type", "quantity")
        if field not in payload
    ]
    if missing_fields:
        raise OrderValidationError(
            "MISSING_FIELD",
            f"필수 항목이 없습니다: {', '.join(missing_fields)}",
        )

    stock_id = parse_integer(payload["stock_id"], field_name="stock_id")
    if stock_id < 1:
        raise OrderValidationError(
            "INVALID_STOCK_ID", "stock_id는 1 이상이어야 합니다."
        )

    stock = db.session.get(Stock, stock_id)
    if stock is None:
        raise OrderValidationError(
            "STOCK_NOT_FOUND", "존재하지 않는 종목입니다.", status_code=404
        )

    transaction_type_value = payload["transaction_type"]
    if not isinstance(transaction_type_value, str):
        raise OrderValidationError(
            "INVALID_TRANSACTION_TYPE", "transaction_type이 올바르지 않습니다."
        )
    transaction_type = transaction_type_value.strip().upper()
    if transaction_type not in VALID_TRANSACTION_TYPES:
        raise OrderValidationError(
            "INVALID_TRANSACTION_TYPE", "transaction_type은 BUY 또는 SELL이어야 합니다."
        )

    quantity = parse_integer(
        payload["quantity"],
        field_name="quantity",
        maximum=MAX_ORDER_QUANTITY,
    )
    if quantity < 1:
        raise OrderValidationError(
            "INVALID_QUANTITY", "quantity는 1 이상이어야 합니다."
        )

    holding = PortfolioItem.query.filter_by(
        user_id=user.id, stock_id=stock.id
    ).first()
    owned_quantity = holding.quantity if holding is not None else 0

    # 클라이언트의 price와 total_amount는 읽지 않고 서버 현재가로 재계산한다.
    price = stock.current_price
    total_amount = calculate_order_total(price=price, quantity=quantity)

    if transaction_type == "BUY" and total_amount > user.cash:
        raise OrderValidationError(
            "INSUFFICIENT_CASH", "예수금이 부족합니다."
        )
    if transaction_type == "SELL" and quantity > owned_quantity:
        raise OrderValidationError(
            "INSUFFICIENT_HOLDINGS", "보유 수량이 부족합니다."
        )

    return ValidatedOrder(
        user=user,
        stock=stock,
        transaction_type=transaction_type,
        quantity=quantity,
        price=price,
        total_amount=total_amount,
        owned_quantity=owned_quantity,
    )


def validate_order_request(*, user_id, http_request):
    """Flask 요청 파싱과 주문 검증을 함께 수행하는 진입점."""
    if isinstance(user_id, bool) or not isinstance(user_id, int):
        raise OrderValidationError(
            "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.", status_code=401
        )
    if db.session.get(User, user_id) is None:
        raise OrderValidationError(
            "AUTHENTICATION_REQUIRED", "로그인이 필요합니다.", status_code=401
        )
    return validate_order_payload(
        user_id=user_id,
        payload=parse_order_payload(http_request),
    )
