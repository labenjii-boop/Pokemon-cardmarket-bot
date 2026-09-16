from app.scheduler import build_scheduler
from app.ws import ConnectionManager


def test_build_scheduler_registers_expected_jobs():
    scheduler = build_scheduler(ConnectionManager())
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"sync_fx", "refresh_catalog", "poll_snapshots", "poll_tcgdex_snapshots"}
