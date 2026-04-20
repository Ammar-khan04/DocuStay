"""
Bounded concurrency for utility background jobs (provider contact lookup, pending verification).
Jobs are run by a fixed-size thread pool; excess jobs are queued and run when a worker is free.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

_executor: ThreadPoolExecutor | None = None
_executor_lock = threading.Lock()


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _executor_lock:
            if _executor is None:
                from app.config import get_settings
                n = get_settings().utility_background_jobs_max_workers
                _executor = ThreadPoolExecutor(
                    max_workers=max(1, n),
                    thread_name_prefix="utility_bg",
                )
    return _executor


def submit_utility_job(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """
    Submit a job to the bounded utility-job pool. Runs in one of the worker threads;
    if all workers are busy, the job is queued and runs when a slot is free.
    Call this from BackgroundTasks.add_task so the request returns immediately and
    the actual work is limited by utility_background_jobs_max_workers.
    """
    _get_executor().submit(fn, *args, **kwargs)
