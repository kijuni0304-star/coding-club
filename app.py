"""한빛 모의주식 Flask 애플리케이션."""

import os
import hmac
import secrets
from functools import wraps
from fractions import Fraction
from datetime import timedelta
from sqlalchemy.orm import contains_eager
from sqlalchemy.exc import OperationalError
from werkzeug.exceptions import HTTPException

from flask import (
    abort,
    Flask,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from models import PortfolioItem, PriceUpdateRun, Stock, Transaction, User, db
from database_write import begin_database_write
from order_service import execute_buy_order, execute_sell_order
from order_validation import OrderValidationError, validate_order_request
from order_validation import MAX_DATABASE_INTEGER, parse_order_payload
from portfolio_service import build_portfolio_items, calculate_portfolio_summary
from transaction_history_service import build_transaction_history
from manager_auth import HASH_FILE, verify_manager_password


PREDEFINED_USERS = tuple(f"user{number}" for number in range(1, 11))
MANAGER_ID = "manager"
INITIAL_CASH = 1_000_000
INITIAL_STOCK_PRICES = {
    "회사 A": 10_000,
    "회사 B": 13_500,
    "회사 C": 18_000,
    "회사 D": 24_500,
    "회사 E": 32_000,
    "회사 F": 41_000,
    "회사 G": 53_500,
    "회사 H": 67_000,
    "회사 I": 82_000,
    "회사 J": 98_000,
}


def stock_display_data(stock):
    """템플릿에서 사용할 종목 가격·등락 표시 데이터를 만든다."""
    change_amount = stock.current_price - stock.previous_price
    change_rate = (
        (change_amount / stock.previous_price) * 100
        if stock.previous_price
        else 0
    )

    if change_amount > 0:
        direction = "up"
        change_amount_display = f"▲ +{change_amount:,}"
        change_rate_display = f"+{change_rate:.2f}%"
    elif change_amount < 0:
        direction = "down"
        change_amount_display = f"▼ -{abs(change_amount):,}"
        change_rate_display = f"{change_rate:.2f}%"
    else:
        direction = "flat"
        change_amount_display = "— 0"
        change_rate_display = "0.00%"

    return {
        "id": stock.id,
        "company_name": stock.company_name,
        "current_price": stock.current_price,
        "previous_price": stock.previous_price,
        "current_price_display": f"{stock.current_price:,}",
        "previous_price_display": f"{stock.previous_price:,}",
        "change_amount": change_amount,
        "change_rate": change_rate,
        "change_percent": round(change_rate, 2),
        "change_amount_display": change_amount_display,
        "change_rate_display": change_rate_display,
        "change_percent_display": change_rate_display,
        "direction": direction,
        "change_class": {
            "up": "text-red",
            "down": "text-blue",
            "flat": "text-neutral",
        }[direction],
    }


def reset_application_data():
    """모든 모의 거래 데이터를 지우고 기본 사용자·종목 상태로 복구한다."""
    try:
        begin_database_write()
        # 거래 참조를 먼저 지운 뒤 보유, 사용자, 종목 순으로 비운다.
        db.session.query(Transaction).delete(synchronize_session=False)
        db.session.query(PortfolioItem).delete(synchronize_session=False)
        db.session.query(PriceUpdateRun).delete(synchronize_session=False)
        db.session.query(User).delete(synchronize_session=False)
        db.session.query(Stock).delete(synchronize_session=False)
        db.session.expunge_all()

        db.session.add_all(
            User(nickname=nickname, cash=INITIAL_CASH)
            for nickname in PREDEFINED_USERS
        )
        db.session.add_all(
            Stock(
                company_name=company_name,
                current_price=initial_price,
                previous_price=initial_price,
            )
            for company_name, initial_price in INITIAL_STOCK_PRICES.items()
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def ranked_stock_display_data():
    """등락률 순으로 정렬한 공용 주가 표시 데이터를 반환한다."""
    stocks = [stock_display_data(stock) for stock in Stock.query.all()]
    stocks.sort(key=lambda stock: (
        -Fraction(stock["change_amount"], stock["previous_price"] or 1),
        stock["company_name"],
    ))
    return stocks


def create_app(test_config=None):
    """애플리케이션을 만들고 필요한 초기 데이터를 안전하게 준비한다."""
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE") == "1",
        MAX_CONTENT_LENGTH=16 * 1024,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        # 기존 DB는 create_all()로 스키마 변경이 불가능하므로 보존하고,
        # FK 기반 거래 모델은 새 DB에서 시작한다.
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", "sqlite:///trading.db"
        ),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    if test_config:
        app.config.update(test_config)

    if not app.config.get("MANAGER_PASSWORD_HASH") and HASH_FILE.is_file():
        app.config["MANAGER_PASSWORD_HASH"] = HASH_FILE.read_text(
            encoding="utf-8"
        ).strip()

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "SECRET_KEY 환경변수를 설정해야 합니다. README의 실행 방법을 확인하세요."
        )

    db.init_app(app)

    with app.app_context():
        initialize_database()

    def csrf_token():
        if not isinstance(session.get("csrf_token"), str):
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    def valid_csrf(token):
        expected = session.get("csrf_token")
        return (isinstance(expected, str) and isinstance(token, str)
                and hmac.compare_digest(expected.encode(), token.encode()))

    @app.context_processor
    def security_context():
        return {"csrf_token_value": csrf_token}

    @app.before_request
    def protect_session_forms():
        if request.method == "POST" and request.endpoint in {
            "login", "logout", "manager_reset"
        }:
            if not valid_csrf(request.form.get("csrf_token")):
                abort(403)

    @app.after_request
    def protect_private_responses(response):
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(success=False, error={
                "code": error.name.upper().replace(" ", "_"),
                "message": "요청 형식 또는 크기를 확인해 주세요.",
            }), error.code
        return error

    def get_session_user():
        """세션의 사용자 ID가 유효할 때만 실제 User를 반환한다."""
        user_id = session.get("user_id")
        if (type(user_id) is not int or not 1 <= user_id <= MAX_DATABASE_INTEGER):
            session.clear()
            return None

        user = db.session.get(User, user_id)
        if user is None or user.nickname not in PREDEFINED_USERS:
            session.clear()
            return None
        if not isinstance(session.get("csrf_token"), str):
            session["csrf_token"] = secrets.token_urlsafe(32)
        return user

    def is_manager_session():
        return (
            session.get("is_manager") is True
            and session.get("nickname") == MANAGER_ID
        )

    def login_required(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if is_manager_session():
                return redirect(url_for("manager_console"))
            current_user = get_session_user()
            if current_user is None:
                return redirect(url_for("login"))
            g.current_user = current_user
            return view(*args, **kwargs)

        return wrapped_view

    def manager_required(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if not is_manager_session():
                if get_session_user() is None:
                    return redirect(url_for("login"))
                abort(403)
            return view(*args, **kwargs)

        return wrapped_view

    def api_session_required(view):
        """API 요청에 유효한 로그인 세션과 POST CSRF 토큰을 요구한다."""
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if is_manager_session():
                return (
                    jsonify(
                        success=False,
                        error={
                            "code": "AUTHENTICATION_REQUIRED",
                            "message": "학생 계정으로 로그인해 주세요.",
                        },
                    ),
                    401,
                )
            current_user = get_session_user()
            if current_user is None:
                return (
                    jsonify(
                        success=False,
                        error={
                            "code": "AUTHENTICATION_REQUIRED",
                            "message": "로그인이 필요합니다.",
                        },
                    ),
                    401,
                )

            if request.method == "POST":
                supplied_token = request.headers.get("X-CSRF-Token")
                if not valid_csrf(supplied_token):
                    return (
                        jsonify(
                            success=False,
                            error={
                                "code": "INVALID_CSRF_TOKEN",
                                "message": "요청을 확인할 수 없습니다. 다시 로그인해 주세요.",
                            },
                        ),
                        403,
                    )

            g.current_user = current_user
            return view(*args, **kwargs)

        return wrapped_view

    @app.route("/", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            nickname_value = request.form.get("nickname", "")
            password_value = request.form.get("password", "")
            input_nickname = (
                nickname_value.strip()
                if isinstance(nickname_value, str) and len(nickname_value) <= 80
                else ""
            )
            input_password = (
                password_value
                if isinstance(password_value, str) and len(password_value) <= 128
                else ""
            )
            if input_nickname == MANAGER_ID and verify_manager_password(
                input_password, app.config.get("MANAGER_PASSWORD_HASH")
            ):
                session.clear()
                session.permanent = True
                session["is_manager"] = True
                session["nickname"] = MANAGER_ID
                session["csrf_token"] = secrets.token_urlsafe(32)
                return redirect(url_for("manager_console"))

            user = (
                User.query.filter_by(nickname=input_nickname).first()
                if input_nickname in PREDEFINED_USERS
                else None
            )

            expected_password = (
                f"resu{input_nickname[4:]}!@" if user is not None else ""
            )
            if user is not None and hmac.compare_digest(
                input_password.encode("utf-8"), expected_password.encode("utf-8")
            ):
                session.clear()
                session.permanent = True
                session["user_id"] = user.id
                session["nickname"] = user.nickname
                session["csrf_token"] = secrets.token_urlsafe(32)
                return redirect(url_for("portfolio"))

            return render_template(
                "login.html", error_msg="아이디 또는 비밀번호가 올바르지 않습니다."
            )

        return render_template("login.html", error_msg=None)

    @app.get("/manager")
    @manager_required
    def manager_console():
        return render_template(
            "manager.html",
            reset_done=request.args.get("reset") == "1",
            error_msg=None,
            stats={
                "users": User.query.count(),
                "stocks": Stock.query.count(),
                "holdings": PortfolioItem.query.count(),
                "transactions": Transaction.query.count(),
                "price_updates": PriceUpdateRun.query.count(),
            },
        )

    @app.post("/manager/reset")
    @manager_required
    def manager_reset():
        if request.form.get("confirmation") != "전체 초기화":
            return (
                render_template(
                    "manager.html",
                    reset_done=False,
                    error_msg="확인 문구가 올바르지 않습니다.",
                    stats={
                        "users": User.query.count(),
                        "stocks": Stock.query.count(),
                        "holdings": PortfolioItem.query.count(),
                        "transactions": Transaction.query.count(),
                        "price_updates": PriceUpdateRun.query.count(),
                    },
                ),
                403,
            )

        reset_application_data()
        return redirect(url_for("manager_console", reset="1"))

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/ranking")
    @login_required
    def ranking():
        return render_template("ranking.html", stocks=ranked_stock_display_data())

    @app.get("/api/stocks")
    @api_session_required
    def stocks_api():
        """브라우저가 공용 Stock 테이블 가격을 조회하는 읽기 전용 API."""
        return jsonify(stocks=ranked_stock_display_data())

    @app.post("/api/orders/validate")
    @api_session_required
    def validate_order_api():
        """현재 DB 상태로 주문을 검증하되 어떤 데이터도 변경하지 않는다."""
        try:
            validated_order = validate_order_request(
                user_id=g.current_user.id,
                http_request=request,
            )
        except OrderValidationError as error:
            return (
                jsonify(
                    valid=False,
                    error={"code": error.code, "message": error.message},
                ),
                error.status_code,
            )

        return jsonify(valid=True, order=validated_order.to_dict())

    @app.post("/api/orders/buy")
    @api_session_required
    def buy_order_api():
        """서버 현재가로 매수 주문을 체결한다."""
        try:
            payload = parse_order_payload(request)
            result = execute_buy_order(user_id=g.current_user.id, payload=payload)
        except OrderValidationError as error:
            return (
                jsonify(
                    success=False,
                    error={"code": error.code, "message": error.message},
                ),
                error.status_code,
            )
        except HTTPException:
            raise
        except OperationalError:
            db.session.rollback()
            return jsonify(success=False, error={
                "code": "DATABASE_BUSY",
                "message": "주문을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            }), 503
        except Exception:
            db.session.rollback()
            app.logger.exception("매수 주문 처리 중 오류 발생")
            return (
                jsonify(
                    success=False,
                    error={
                        "code": "ORDER_PROCESSING_FAILED",
                        "message": "주문 처리 중 오류가 발생했습니다.",
                    },
                ),
                500,
            )

        return jsonify(
            success=True,
            message=f"{result.company_name} {result.quantity}주 매수가 완료되었습니다.",
            order=result.to_dict(),
        )

    @app.post("/api/orders/sell")
    @api_session_required
    def sell_order_api():
        """서버 현재가로 매도 주문을 체결한다."""
        try:
            payload = parse_order_payload(request)
            result = execute_sell_order(user_id=g.current_user.id, payload=payload)
        except OrderValidationError as error:
            return (
                jsonify(
                    success=False,
                    error={"code": error.code, "message": error.message},
                ),
                error.status_code,
            )
        except HTTPException:
            raise
        except OperationalError:
            db.session.rollback()
            return jsonify(success=False, error={
                "code": "DATABASE_BUSY",
                "message": "주문을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
            }), 503
        except Exception:
            db.session.rollback()
            app.logger.exception("매도 주문 처리 중 오류 발생")
            return (
                jsonify(
                    success=False,
                    error={
                        "code": "ORDER_PROCESSING_FAILED",
                        "message": "주문 처리 중 오류가 발생했습니다.",
                    },
                ),
                500,
            )

        return jsonify(
            success=True,
            message=f"{result.company_name} {result.quantity}주 매도가 완료되었습니다.",
            order=result.to_dict(),
        )

    @app.get("/order")
    @login_required
    def order():
        stock_id = request.args.get("stock_id", type=int)
        if "stock_id" in request.args and (
            stock_id is None or not 1 <= stock_id <= MAX_DATABASE_INTEGER
        ):
            abort(404)
        if stock_id is not None:
            return redirect(url_for("order_detail", stock_id=stock_id))

        stock = Stock.query.order_by(Stock.company_name).first()
        if stock is None:
            abort(404)

        return redirect(url_for("order_detail", stock_id=stock.id))

    @app.get("/order/<int:stock_id>")
    @login_required
    def order_detail(stock_id):
        if not 1 <= stock_id <= MAX_DATABASE_INTEGER:
            abort(404)
        stock = db.session.get(Stock, stock_id)
        if stock is None:
            abort(404)

        return render_template(
            "trade.html",
            stock=stock_display_data(stock),
            csrf_token=session["csrf_token"],
        )

    @app.get("/portfolio")
    @login_required
    def portfolio():
        # 한 SELECT에서 예수금·보유량·주가를 읽어 주문 중에도 같은 스냅샷을 표시한다.
        current_user = (
            User.query.filter(User.id == g.current_user.id)
            .outerjoin(PortfolioItem, (PortfolioItem.user_id == User.id)
                       & (PortfolioItem.quantity > 0))
            .outerjoin(Stock, Stock.id == PortfolioItem.stock_id)
            .options(contains_eager(User.portfolio_items).contains_eager(PortfolioItem.stock))
            .populate_existing()
            .order_by(Stock.company_name)
            .one()
        )
        my_stocks = build_portfolio_items(current_user.portfolio_items)
        portfolio_summary = calculate_portfolio_summary(
            cash=current_user.cash,
            holdings=my_stocks,
        )

        return render_template(
            "portfolio.html",
            current_user=current_user.nickname,
            my_stocks=my_stocks,
            portfolio_summary=portfolio_summary,
        )

    @app.get("/history")
    @login_required
    def history():
        """로그인 사용자 본인의 거래 기록만 최신 체결 순으로 표시한다."""
        current_user = g.current_user

        transactions = (
            Transaction.query.filter_by(user_id=current_user.id)
            .join(Transaction.stock)
            .options(contains_eager(Transaction.stock))
            .order_by(Transaction.created_at.desc(), Transaction.id.desc())
            .all()
        )
        return render_template(
            "history.html",
            transactions=build_transaction_history(transactions),
        )

    return app


def initialize_database():
    """기본 사용자와 종목을 중복 없이 생성한다."""
    try:
        begin_database_write()
        # 테이블 생성도 같은 연결/잠금 안에서 처리해 최초 동시 시작에 안전하다.
        db.metadata.create_all(bind=db.session.connection())
        for nickname in PREDEFINED_USERS:
            if User.query.filter_by(nickname=nickname).first() is None:
                db.session.add(User(nickname=nickname, cash=INITIAL_CASH))

        for company_name, initial_price in INITIAL_STOCK_PRICES.items():
            if Stock.query.filter_by(company_name=company_name).first() is None:
                db.session.add(
                    Stock(
                        company_name=company_name,
                        current_price=initial_price,
                        previous_price=initial_price,
                    )
                )

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


app = create_app()


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG") == "1"
    is_reloader_worker = os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    scheduler = None

    # 디버그 리로더의 감시용 부모 프로세스에서는 스케줄러를 시작하지 않는다.
    if not debug_mode or is_reloader_worker:
        from price_scheduler import start_price_scheduler

        scheduler = start_price_scheduler(app)

    try:
        app.run(
            port=int(os.environ.get("PORT", "5000")),
            debug=debug_mode,
        )
    finally:
        if scheduler is not None and scheduler.running:
            scheduler.shutdown(wait=False)
