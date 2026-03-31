"""Utilitários mínimos de observabilidade: correlation_id (contextvar) e logs JSON (stdlib)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

logger = logging.getLogger("talent_rank.vacancy")


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(correlation_id: str | None) -> None:
    _correlation_id.set(correlation_id)


def ensure_correlation_id(existing: str | None = None) -> str:
    """correlation_id = existing or get_correlation_id() or new_correlation_id()."""
    cid = existing or get_correlation_id()
    if not cid:
        cid = new_correlation_id()
    set_correlation_id(cid)
    return cid


class Timer:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)


def log_event(event: str, **fields: object) -> None:
    payload: dict[str, object] = {"event": event}
    cid = get_correlation_id()
    if cid:
        payload["correlation_id"] = cid
    for k, v in fields.items():
        if v is not None:
            payload[k] = v
    logger.info(json.dumps(payload, ensure_ascii=False, default=str))
