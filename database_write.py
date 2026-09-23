"""SQLite 쓰기 작업의 프로세스 간 직렬화. 호출자는 commit/rollback을 소유한다."""

from sqlalchemy import text

from models import db


def begin_database_write():
    """검증 조회 전에 쓰기 예약 잠금을 얻고 오래된 ORM 상태를 버린다.

    인증용 읽기가 먼저 시작됐어도 새 트랜잭션에서 최신 상태를 읽는다.
    호출 전에 아직 저장하지 않은 변경이 있으면 임의로 버리지 않는다.
    SQLite의 DB 잠금이 주문과 주가 갱신 및 여러 프로세스 모두에 적용된다.
    """
    if db.session.new or db.session.dirty or db.session.deleted:
        raise RuntimeError("쓰기 서비스 호출 전에 미저장 변경을 확정해야 합니다.")
    db.session.rollback()
    if db.engine.dialect.name == "sqlite":
        db.session.execute(text("BEGIN IMMEDIATE"))
