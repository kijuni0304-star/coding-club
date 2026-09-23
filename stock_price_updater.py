import random
from datetime import timezone

from sqlalchemy.exc import IntegrityError

from database_write import begin_database_write
from models import PriceUpdateRun, Stock, db, utc_now
from order_validation import MAX_DATABASE_INTEGER


MIN_CHANGE_RATE = -0.20
MAX_CHANGE_RATE = 0.20


def update_stock_prices(*, update_time=None, rate_generator=None):
    """현재 UTC 분의 모든 종목 가격을 정확히 한 번 갱신한다.

    같은 분에 먼저 실행된 트랜잭션이 있으면 ``False``를 반환한다.
    테스트에서는 ``update_time``과 인자 없는 ``rate_generator``를 주입할 수 있다.
    """
    update_time = update_time or utc_now()
    if update_time.tzinfo is None:
        update_time = update_time.replace(tzinfo=timezone.utc)
    else:
        update_time = update_time.astimezone(timezone.utc)

    minute_key = update_time.strftime("%Y-%m-%dT%H:%MZ")
    rate_generator = rate_generator or (
        lambda: random.uniform(MIN_CHANGE_RATE, MAX_CHANGE_RATE)
    )

    try:
        begin_database_write()
        # minute_key의 DB 유일 제약이 여러 프로세스의 동시 실행도 막는다.
        db.session.add(PriceUpdateRun(minute_key=minute_key))
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        if PriceUpdateRun.query.filter_by(minute_key=minute_key).first() is not None:
            db.session.rollback()
            return False
        raise
    except Exception:
        db.session.rollback()
        raise

    try:
        stocks = Stock.query.order_by(Stock.id).with_for_update().all()
        for stock in stocks:
            rate = rate_generator()
            if not MIN_CHANGE_RATE <= rate <= MAX_CHANGE_RATE:
                raise ValueError("주가 변동률은 -0.20 이상 0.20 이하여야 합니다.")

            old_price = stock.current_price
            stock.previous_price = old_price
            stock.current_price = max(1, round(old_price * (1 + rate)))
            if stock.current_price > MAX_DATABASE_INTEGER:
                raise ValueError("주가가 DB 정수 범위를 초과했습니다.")
            stock.updated_at = update_time

        # 실행 기록과 모든 종목 가격을 하나의 트랜잭션으로 확정한다.
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        raise
