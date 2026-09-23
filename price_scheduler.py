from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from stock_price_updater import update_stock_prices


def start_price_scheduler(app):
    """매분 0초에 주가 갱신을 시도하는 백그라운드 스케줄러를 시작한다."""
    scheduler = BackgroundScheduler(timezone="UTC")

    def run_price_update():
        with app.app_context():
            try:
                updated = update_stock_prices()
                if updated:
                    app.logger.info("주가 자동 갱신 완료")
            except Exception:
                app.logger.exception("주가 자동 갱신 실패")

    scheduler.add_job(
        run_price_update,
        trigger=CronTrigger(minute="*", second=0, timezone="UTC"),
        id="stock-price-update",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=59,
    )
    scheduler.start()

    # 분 중간에 서버가 시작되거나 재시작되어도 현재 분의 갱신을 한 번 시도한다.
    run_price_update()
    return scheduler
