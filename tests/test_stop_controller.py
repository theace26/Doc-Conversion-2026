"""
Tests for core/stop_controller.py — global stop flag, task registry, reset.
"""

import asyncio

import pytest

from core.stop_controller import (
    get_stop_state,
    register_task,
    request_stop,
    reset_stop,
    should_stop,
    unregister_task,
)


@pytest.fixture(autouse=True)
def _always_reset():
    """Ensure stop state is clean before and after each test."""
    reset_stop()
    yield
    reset_stop()


def test_should_stop_default_false():
    """should_stop() returns False by default."""
    assert should_stop() is False


def test_request_stop_sets_flag():
    """request_stop() sets the flag and returns stopped jobs list."""
    result = request_stop(reason="test_stop")
    assert should_stop() is True
    assert "stopped_jobs" in result
    assert "at" in result


def test_reset_stop_clears_flag():
    """reset_stop() clears the flag."""
    request_stop("test")
    assert should_stop() is True
    reset_stop()
    assert should_stop() is False


def test_get_stop_state_structure():
    """get_stop_state() returns correct structure."""
    state = get_stop_state()
    assert "stop_requested" in state
    assert "stop_requested_at" in state
    assert "stop_reason" in state
    assert "registered_tasks" in state
    assert state["stop_requested"] is False
    assert state["registered_tasks"] == []


def test_get_stop_state_after_stop():
    """get_stop_state() reflects stop state after request_stop()."""
    request_stop(reason="admin_test")
    state = get_stop_state()
    assert state["stop_requested"] is True
    assert state["stop_reason"] == "admin_test"
    assert state["stop_requested_at"] is not None


@pytest.mark.asyncio
async def test_registered_task_cancelled_on_stop():
    """Registered task is cancelled when request_stop() is called."""
    cancelled = False

    async def mock_job():
        nonlocal cancelled
        try:
            await asyncio.sleep(100)
        except asyncio.CancelledError:
            cancelled = True

    task = asyncio.create_task(mock_job())
    register_task("test-job-1", task)

    # Yield so the task starts running and enters sleep
    await asyncio.sleep(0)

    result = request_stop(reason="test")
    assert "test-job-1" in result["stopped_jobs"]

    # Give the event loop multiple ticks to process cancellation
    for _ in range(10):
        await asyncio.sleep(0.01)
        if cancelled:
            break
    assert cancelled is True


def test_unregister_task():
    """unregister_task() removes task from registry."""
    loop = asyncio.new_event_loop()
    task = loop.create_task(asyncio.sleep(0))
    register_task("test-job-2", task)

    state = get_stop_state()
    assert "test-job-2" in state["registered_tasks"]

    unregister_task("test-job-2")
    state = get_stop_state()
    assert "test-job-2" not in state["registered_tasks"]

    loop.close()


def test_request_stop_with_no_tasks():
    """request_stop() works fine with no registered tasks."""
    result = request_stop(reason="empty")
    assert result["stopped_jobs"] == []
    assert should_stop() is True
