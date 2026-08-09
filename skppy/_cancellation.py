# SPDX-License-Identifier: MIT
"""Internal cooperative cancellation shared by parser implementations."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .exceptions import LoadCancelledError

CancellationCheck = Callable[[], bool]

_active_check: ContextVar[CancellationCheck | None] = ContextVar("skppy_cancellation_check", default=None)


def check_cancelled() -> None:
    """Raise when the active loader operation requested cancellation."""
    check = _active_check.get()
    if check is not None and check():
        raise LoadCancelledError("SKP loading was cancelled")


@contextmanager
def cancellation_scope(check: CancellationCheck | None) -> Iterator[None]:
    """Install one cancellation callback for the current parsing context."""
    token = _active_check.set(check)
    try:
        check_cancelled()
        yield
    finally:
        _active_check.reset(token)
