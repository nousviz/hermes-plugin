"""Agent Mission Control telemetry: stream Hermes tool activity into NousViz.

Registered only when ``telemetry_webhook_slug`` is configured. Events are
buffered in memory and flushed to the NousViz inbound webhook endpoint every
``FLUSH_EVERY`` events and at session end. Failures are swallowed — telemetry
must never break the agent loop.

Privacy: by default only tool name, status, duration and ids are recorded —
never tool arguments or results.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

from .nousviz_client import NousVizClient

logger = logging.getLogger(__name__)

FLUSH_EVERY = 25


class Telemetry:
    """Reads ``telemetry_webhook_slug`` live from plugin config, so telemetry is a
    no-op until configured and can be enabled without code changes."""

    def __init__(self, client_factory: Callable[[], NousVizClient],
                 get_config: Callable[[str], Optional[str]]):
        self._client_factory = client_factory
        self._get_config = get_config
        self._buffer: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def _slug(self) -> Optional[str]:
        try:
            return self._get_config("telemetry_webhook_slug")
        except Exception:
            return None

    # Hook: signature-inspected by Hermes — declare only the fields we use.
    def post_tool_call(self, tool_name: str = "", status: Optional[str] = None,
                       duration_ms: int = 0, session_id: Optional[str] = None,
                       task_id: Optional[str] = None, **_kw) -> None:
        if not self._slug():
            return
        event = {
            "ts": time.time(), "type": "tool_call", "tool": tool_name,
            "status": status, "duration_ms": duration_ms,
            "session_id": session_id, "task_id": task_id,
        }
        with self._lock:
            self._buffer.append(event)
            should_flush = len(self._buffer) >= FLUSH_EVERY
        if should_flush:
            self.flush()

    def on_session_end(self, **_kw) -> None:
        self.flush()

    def flush(self) -> None:
        slug = self._slug()
        with self._lock:
            if not self._buffer:
                return
            events, self._buffer = self._buffer, []
        if not slug:
            return
        try:
            secret = None
            try:
                secret = self._get_config("telemetry_webhook_secret")
            except Exception:
                pass
            self._client_factory().push(
                slug, {"source": "hermes-agent", "events": events}, secret=secret)
            logger.debug("nousviz telemetry: flushed %d events", len(events))
        except Exception as e:  # never raise into hook dispatch
            logger.debug("nousviz telemetry flush failed (%d events dropped): %s",
                         len(events), e)
