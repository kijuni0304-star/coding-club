from dataclasses import dataclass
from database_write import begin_database_write

from models import PortfolioItem, Stock, Transaction, User, db
from order_validation import (
    MAX_DATABASE_INTEGER,
    OrderValidationError,
    calculate_order_total,
    validate_order_payload,
)


@dataclass(frozen=True)
class BuyOrderResult:
    transaction_id: int
    user_id: int
    stock_id: int
    company_name: str
    quantity: int
    price: int
    total_amount: int
    remaining_cash: int
    total_quantity: int
    average_price: int

    def to_dict(self):
        return {
            "transaction_id": self.transaction_id,
            "user_id": self.user_id,
            "stock_id": self.stock_id,
            "company_name": self.company_name,
            "transaction_type": "BUY",
            "quantity": self.quantity,
            "price": self.price,
            "price_display": f"{self.price:,}",
            "total_amount": self.total_amount,
            "remaining_cash": self.remaining_cash,
            "remaining_cash_display": f"{self.remaining_cash:,}",
            "total_quantity": self.total_quantity,
            "average_price": self.average_price,
        }


@dataclass(frozen=True)
class SellOrderResult:
    transaction_id: int
    user_id: int
    stock_id: int
    company_name: str
    quantity: int
    price: int
    total_amount: int
    remaining_cash: int
    remaining_quantity: int
    average_price: int

    def to_dict(self):
        return {
            "transaction_id": self.transaction_id,
            "user_id": self.user_id,
            "stock_id": self.stock_id,
            "company_name": self.company_name,
            "transaction_type": "SELL",
            "quantity": self.quantity,
            "price": self.price,
            "price_display": f"{self.price:,}",
            "total_amount": self.total_amount,
            "remaining_cash": self.remaining_cash,
            "remaining_cash_display": f"{self.remaining_cash:,}",
            "remaining_quantity": self.remaining_quantity,
            "average_price": self.average_price,
        }


def execute_buy_order(*, user_id, payload):
    """서버 현재가로 매수를 체결하고 관련 변경을 한 번에 커밋한다."""
    buy_payload = dict(payload) if isinstance(payload, dict) else payload
    if isinstance(buy_payload, dict):
        # 전용 BUY 엔드포인트이므로 클라이언트가 보낸 거래 종류도 신뢰하지 않는다.
        buy_payload["transaction_type"] = "BUY"

    try:
        begin_database_write()
        validated_order = validate_order_payload(
            user_id=user_id,
            payload=buy_payload,
        )

        # 지원 DB에서는 체결 중 사용자·종목·보유 행의 동시 변경을 막는다.
        user = db.session.execute(
            db.select(User)
            .where(User.id == validated_order.user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        stock = db.session.execute(
            db.select(Stock)
            .where(Stock.id == validated_order.stock.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        holding = db.session.execute(
            db.select(PortfolioItem)
            .where(
                PortfolioItem.user_id == user.id,
                PortfolioItem.stock_id == stock.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

        # 잠금을 얻은 뒤 최신 서버 가격과 예수금으로 다시 계산·검증한다.
        quantity = validated_order.quantity
        price = stock.current_price
        total_amount = calculate_order_total(price=price, quantity=quantity)
        if total_amount > user.cash:
            raise OrderValidationError(
                "INSUFFICIENT_CASH", "예수금이 부족합니다."
            )

        existing_quantity = holding.quantity if holding is not None else 0
        existing_average_price = (
            holding.average_price if holding is not None else 0
        )
        total_quantity = existing_quantity + quantity
        if total_quantity > MAX_DATABASE_INTEGER:
            raise OrderValidationError(
                "POSITION_TOO_LARGE",
                "보유 수량이 처리 가능한 범위를 초과했습니다.",
            )
        weighted_cost = (
            existing_average_price * existing_quantity
            + price * quantity
        )
        # average_price가 정수 원 단위이므로 가장 가까운 원으로 반올림한다.
        average_price = (
            weighted_cost + total_quantity // 2
        ) // total_quantity

        user.cash -= total_amount
        if holding is None:
            holding = PortfolioItem(
                user_id=user.id,
                stock_id=stock.id,
                quantity=total_quantity,
                average_price=average_price,
            )
            db.session.add(holding)
        else:
            holding.quantity = total_quantity
            holding.average_price = average_price

        transaction = Transaction(
            user_id=user.id,
            stock_id=stock.id,
            transaction_type="BUY",
            quantity=quantity,
            price=price,
            total_amount=total_amount,
        )
        db.session.add(transaction)
        db.session.flush()

        result = BuyOrderResult(
            transaction_id=transaction.id,
            user_id=user.id,
            stock_id=stock.id,
            company_name=stock.company_name,
            quantity=quantity,
            price=price,
            total_amount=total_amount,
            remaining_cash=user.cash,
            total_quantity=holding.quantity,
            average_price=holding.average_price,
        )
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise


def execute_sell_order(*, user_id, payload):
    """서버 현재가로 매도를 체결하고 관련 변경을 한 번에 커밋한다."""
    sell_payload = dict(payload) if isinstance(payload, dict) else payload
    if isinstance(sell_payload, dict):
        # 전용 SELL 엔드포인트이므로 클라이언트가 보낸 거래 종류도 신뢰하지 않는다.
        sell_payload["transaction_type"] = "SELL"

    try:
        begin_database_write()
        validated_order = validate_order_payload(
            user_id=user_id,
            payload=sell_payload,
        )

        user = db.session.execute(
            db.select(User)
            .where(User.id == validated_order.user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        stock = db.session.execute(
            db.select(Stock)
            .where(Stock.id == validated_order.stock.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        holding = db.session.execute(
            db.select(PortfolioItem)
            .where(
                PortfolioItem.user_id == user.id,
                PortfolioItem.stock_id == stock.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()

        # 잠금을 얻은 뒤 실제 보유량을 다시 확인해 공매도를 차단한다.
        quantity = validated_order.quantity
        if holding is None or holding.quantity < quantity:
            raise OrderValidationError(
                "INSUFFICIENT_HOLDINGS", "보유 수량이 부족합니다."
            )

        price = stock.current_price
        total_amount = calculate_order_total(price=price, quantity=quantity)
        if user.cash > MAX_DATABASE_INTEGER - total_amount:
            raise OrderValidationError(
                "BALANCE_TOO_LARGE",
                "예수금이 처리 가능한 범위를 초과했습니다.",
            )
        holding.quantity -= quantity
        if holding.quantity == 0:
            holding.average_price = 0

        user.cash += total_amount
        transaction = Transaction(
            user_id=user.id,
            stock_id=stock.id,
            transaction_type="SELL",
            quantity=quantity,
            price=price,
            total_amount=total_amount,
        )
        db.session.add(transaction)
        db.session.flush()

        result = SellOrderResult(
            transaction_id=transaction.id,
            user_id=user.id,
            stock_id=stock.id,
            company_name=stock.company_name,
            quantity=quantity,
            price=price,
            total_amount=total_amount,
            remaining_cash=user.cash,
            remaining_quantity=holding.quantity,
            average_price=holding.average_price,
        )
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise
