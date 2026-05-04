"""BUG-022: boot-time scheduler collision self-check."""
from unittest.mock import MagicMock
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import structlog.testing
import core.scheduler as sched_module


def _make_job(job_id: str, trigger) -> MagicMock:
    job = MagicMock()
    job.id = job_id
    job.trigger = trigger
    return job


def test_no_collision_warns_nothing():
    """Jobs spaced >= 5 min apart produce no warning."""
    jobs = [
        _make_job("job_a", CronTrigger(hour=3, minute=0)),
        _make_job("job_b", CronTrigger(hour=3, minute=30)),
        _make_job("job_c", CronTrigger(hour=4, minute=0)),
    ]
    sched_module.scheduler = MagicMock()
    sched_module.scheduler.get_jobs.return_value = jobs

    with structlog.testing.capture_logs() as captured:
        sched_module._check_scheduler_collisions()

    collisions = [e for e in captured if e.get("event") == "scheduler.time_slot_collision"]
    assert len(collisions) == 0


def test_collision_detected():
    """Two jobs 3 min apart trigger a warning."""
    jobs = [
        _make_job("job_a", CronTrigger(hour=3, minute=0)),
        _make_job("job_b", CronTrigger(hour=3, minute=3)),
    ]
    sched_module.scheduler = MagicMock()
    sched_module.scheduler.get_jobs.return_value = jobs

    with structlog.testing.capture_logs() as captured:
        sched_module._check_scheduler_collisions()

    collisions = [e for e in captured if e.get("event") == "scheduler.time_slot_collision"]
    assert len(collisions) == 1
    assert collisions[0]["job_a"] == "job_a"
    assert collisions[0]["job_b"] == "job_b"
    assert collisions[0]["gap_minutes"] == 3


def test_interval_trigger_skipped():
    """Interval triggers are ignored."""
    jobs = [
        _make_job("job_a", IntervalTrigger(minutes=5)),
        _make_job("job_b", IntervalTrigger(hours=1)),
    ]
    sched_module.scheduler = MagicMock()
    sched_module.scheduler.get_jobs.return_value = jobs

    with structlog.testing.capture_logs() as captured:
        sched_module._check_scheduler_collisions()

    assert not any(e.get("event") == "scheduler.time_slot_collision" for e in captured)


def test_weekly_job_skipped():
    """Weekly jobs (day_of_week != '*') are ignored."""
    jobs = [
        _make_job("job_a", CronTrigger(day_of_week="sun", hour=2, minute=0)),
        _make_job("job_b", CronTrigger(day_of_week="sun", hour=2, minute=3)),
    ]
    sched_module.scheduler = MagicMock()
    sched_module.scheduler.get_jobs.return_value = jobs

    with structlog.testing.capture_logs() as captured:
        sched_module._check_scheduler_collisions()

    assert not any(e.get("event") == "scheduler.time_slot_collision" for e in captured)


def test_five_minute_gap_not_a_collision():
    """Exactly 5 min apart is NOT a collision (threshold is strictly < 5)."""
    jobs = [
        _make_job("job_a", CronTrigger(hour=3, minute=50)),
        _make_job("job_b", CronTrigger(hour=3, minute=55)),
    ]
    sched_module.scheduler = MagicMock()
    sched_module.scheduler.get_jobs.return_value = jobs

    with structlog.testing.capture_logs() as captured:
        sched_module._check_scheduler_collisions()

    assert not any(e.get("event") == "scheduler.time_slot_collision" for e in captured)
