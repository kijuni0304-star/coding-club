"""선택 실행: 격리 DB와 로컬 서버에서 Playwright UI 통합 검사."""
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import logging

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "browser-test-only-secret"

from werkzeug.serving import make_server
from app import create_app
from manager_auth import hash_manager_password
from models import db, Stock
from order_service import execute_buy_order


def main():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    with TemporaryDirectory() as directory:
        app = create_app({"TESTING": True,
                          "MANAGER_PASSWORD_HASH": hash_manager_password("test-manager-password"),
                          "SQLALCHEMY_DATABASE_URI":
                          "sqlite:///" + (Path(directory) / "browser.db").as_posix()})
        with app.app_context():
            execute_buy_order(user_id=1, payload={"stock_id": 1, "quantity": 2})
            db.session.get(Stock, 1).current_price = 11_200
            db.session.get(Stock, 10).current_price = 1_001_000_000
            db.session.commit()
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            return subprocess.call(["node", str(ROOT / "tests" / "browser_check.cjs"),
                                    f"http://127.0.0.1:{server.server_port}"], cwd=ROOT)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
            with app.app_context():
                db.session.remove()
                db.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
