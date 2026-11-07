"""nousviz — give Hermes a data platform.

Connects Hermes to a self-hosted NousViz (>= 1.0.6) install:

- ``nousviz_query``            SQL over the platform's data (read-only)
- ``nousviz_push``             land collected data via inbound webhooks
- ``nousviz_create_dashboard`` turn an exploration into a persistent dashboard
- ``nousviz_create_alert``     get notified (and called back) when numbers move
- ``nousviz_dashboard_link``   share a dashboard URL
- ``/nousviz``                 connection status
- optional telemetry hooks     stream the agent's own tool activity into a
                               NousViz "Mission Control" dashboard

Config (``plugins.entries.nousviz.settings``): ``base_url``, ``email``,
optional ``telemetry_webhook_slug`` + ``telemetry_webhook_secret``.
Password comes from the Hermes secret scope as ``NOUSVIZ_PASSWORD`` —
never from plugin config.
"""

from __future__ import annotations

import logging

from .nousviz_client import NousVizClient, NousVizError
from . import tools as nv_tools
from .telemetry import Telemetry

logger = logging.getLogger(__name__)

_client: NousVizClient | None = None
_ctx = None


def _get_client() -> NousVizClient:
    """Build (once) a client from plugin config + secret scope."""
    global _client
    if _client is None:
        base_url = _ctx.get_config("base_url") if _ctx else None
        email = _ctx.get_config("email") if _ctx else None
        from agent.secret_scope import get_secret
        password = get_secret("NOUSVIZ_PASSWORD")
        if not base_url or not email or not password:
            raise NousVizError(
                "NousViz is not configured. Set plugins.entries.nousviz.settings.base_url "
                "and .email in config.yaml, and provide the NOUSVIZ_PASSWORD secret.")
        _client = NousVizClient(base_url=base_url, email=email, password=password)
    return _client


def _status_command(raw_args: str) -> str:
    """/nousviz — connection status; /nousviz mission-control — provision the dashboard."""
    arg = (raw_args or "").strip().lower()
    if arg == "mission-control":
        try:
            from . import mission_control
            result = mission_control.provision(_get_client())
            return (f"📊 Mission Control {result['provisioned']}: {result['url']}\n"
                    f"It charts this agent's telemetry (tool calls, errors, sessions). "
                    f"Telemetry streams when telemetry_webhook_slug is configured.")
        except NousVizError as e:
            return f"❌ Mission Control provisioning failed: {e}"
    try:
        info = _get_client().check_connection()
        tool_names = ", ".join(name for name, *_ in nv_tools.TOOLS)
        return (f"✅ Connected to NousViz at {info['base_url']} as {info['email']}.\n"
                f"Tools: {tool_names}.\n"
                f"Commands: /nousviz mission-control — provision the agent-activity dashboard.")
    except NousVizError as e:
        return f"❌ NousViz connection failed: {e}"


def register(ctx) -> None:
    """Called once by the Hermes plugin loader."""
    global _ctx
    _ctx = ctx
    nv_tools.set_client_factory(_get_client)

    for name, schema, handler, emoji in nv_tools.TOOLS:
        ctx.register_tool(name=name, toolset="nousviz", schema=schema,
                          handler=handler, emoji=emoji)

    ctx.register_command(
        name="nousviz", handler=_status_command, args_hint="[mission-control]",
        description="NousViz connection status; 'mission-control' provisions the agent-activity dashboard")

    # Telemetry no-ops until telemetry_webhook_slug is configured (read live).
    telemetry = Telemetry(_get_client, ctx.get_config)
    ctx.register_hook("post_tool_call", telemetry.post_tool_call)
    ctx.register_hook("on_session_end", telemetry.on_session_end)
