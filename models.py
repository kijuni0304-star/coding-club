import sqlite3
from datetime import datetime, timezone

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine


db = SQLAlchemy()


@event.listens_for(Engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """SQLite에서도 선언한 외래키 제약을 실제로 강제한다."""
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def utc_now():
    """DB 기본값에서 사용할 timezone-aware UTC 현재 시각을 반환한다."""
    return datetime.now(timezone.utc)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(80), unique=True, nullable=False, index=True)
    cash = db.Column(
        db.Integer,
        nullable=False,
        default=1_000_000,
        server_default="1000000",
    )

    portfolio_items = db.relationship(
        "PortfolioItem",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    transactions = db.relationship("Transaction", back_populates="user")

    __table_args__ = (
        db.CheckConstraint("cash >= 0", name="ck_user_cash_non_negative"),
    )


class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(
        db.String(50), unique=True, nullable=False, index=True
    )
    current_price = db.Column(db.Integer, nullable=False)
    previous_price = db.Column(db.Integer, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    portfolio_items = db.relationship(
        "PortfolioItem",
        back_populates="stock",
        cascade="all, delete-orphan",
    )
    transactions = db.relationship("Transaction", back_populates="stock")

    __table_args__ = (
        db.CheckConstraint(
            "current_price > 0", name="ck_stock_current_price_positive"
        ),
        db.CheckConstraint(
            "previous_price > 0", name="ck_stock_previous_price_positive"
        ),
    )


class PriceUpdateRun(db.Model):
    """한 분에 한 번만 주가 갱신 트랜잭션을 허용하는 실행 기록."""

    id = db.Column(db.Integer, primary_key=True)
    minute_key = db.Column(db.String(17), unique=True, nullable=False, index=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )


class PortfolioItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stock_id = db.Column(
        db.Integer,
        db.ForeignKey("stock.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    average_price = db.Column(
        db.Integer, nullable=False, default=0, server_default="0"
    )

    user = db.relationship("User", back_populates="portfolio_items")
    stock = db.relationship("Stock", back_populates="portfolio_items")

    __table_args__ = (
        db.UniqueConstraint(
            "user_id", "stock_id", name="uq_portfolio_item_user_stock"
        ),
        db.CheckConstraint(
            "quantity >= 0", name="ck_portfolio_item_quantity_non_negative"
        ),
        db.CheckConstraint(
            "average_price >= 0",
            name="ck_portfolio_item_average_price_non_negative",
        ),
        db.CheckConstraint(
            "(quantity = 0 AND average_price = 0) "
            "OR (quantity > 0 AND average_price > 0)",
            name="ck_portfolio_item_quantity_average_price_consistent",
        ),
    )


class Transaction(db.Model):
    # TRANSACTION 키워드와 충돌하지 않도록 복수형 테이블명을 사용한다.
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    stock_id = db.Column(
        db.Integer,
        db.ForeignKey("stock.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    transaction_type = db.Column(db.String(4), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Integer, nullable=False)
    total_amount = db.Column(db.Integer, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )

    user = db.relationship("User", back_populates="transactions")
    stock = db.relationship("Stock", back_populates="transactions")

    __table_args__ = (
        db.CheckConstraint(
            "transaction_type IN ('BUY', 'SELL')",
            name="ck_transaction_type",
        ),
        db.CheckConstraint(
            "quantity > 0", name="ck_transaction_quantity_positive"
        ),
        db.CheckConstraint("price > 0", name="ck_transaction_price_positive"),
        db.CheckConstraint(
            "total_amount = quantity * price",
            name="ck_transaction_total_amount",
        ),
    )
