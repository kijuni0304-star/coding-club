"""선택 실행: 실제 다음 분 경계까지 기다려 스케줄러 동작을 검증한다."""
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SECRET_KEY"] = "scheduler-test-only"

from apscheduler.events import EVENT_JOB_EXECUTED
from app import create_app
from models import db, PriceUpdateRun
from price_scheduler import start_price_scheduler


def main():
    with TemporaryDirectory() as directory:
        app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI":
                          "sqlite:///" + (Path(directory) / "market.db").as_posix()})
        completed = Event()
        scheduler = start_price_scheduler(app)
        scheduler.add_listener(lambda event: completed.set(), EVENT_JOB_EXECUTED)
        try:
            with app.app_context():
                initial = PriceUpdateRun.query.count()
                assert initial >= 1
            assert completed.wait(65), "다음 분 경계의 갱신 작업이 실행되지 않았습니다."
            with app.app_context():
                runs = PriceUpdateRun.query.order_by(PriceUpdateRun.id).all()
                assert len(runs) >= 2
                assert len({r.minute_key for r in runs}) == len(runs)
                print("Real scheduler passed: startup + next minute", [r.minute_key for r in runs])
        finally:
            scheduler.shutdown(wait=True)
            with app.app_context():
                db.session.remove()
                db.engine.dispose()


if __name__ == "__main__":
    main()
