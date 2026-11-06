"""Tool schemas + handlers for the nousviz Hermes plugin.

Handler contract (verified against hermes-agent v0.22.5):
``fn(args: dict, **kw) -> str`` returning a JSON string. Schema shape matches
plugins/google_meet/tools.py: {"name", "description", "parameters": {...}}.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from .nousviz_client import NousVizClient, NousVizError

logger = logging.getLogger(__name__)

# Set by register() in __init__.py so handlers can reach config/secrets.
_get_client: Optional[Callable[[], NousVizClient]] = None


def set_client_factory(factory: Callable[[], NousVizClient]) -> None:
    global _get_client
    _get_client = factory


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "result": data}, default=str)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message})


def _client() -> NousVizClient:
    if _get_client is None:
        raise NousVizError("nousviz plugin not initialised")
    return _get_client()


# ── schemas ──────────────────────────────────────────────────────────

def _str(description: str) -> dict:
    return {"type": "string", "description": description}


def _schema(name: str, description: str, properties: dict, required: list | None = None) -> dict:
    params: dict[str, Any] = {"type": "object", "properties": properties,
                              "additionalProperties": False}
    if required:
        params["required"] = required
    return {"name": name, "description": description, "parameters": params}


QUERY_SCHEMA = _schema(
    "nousviz_query",
    "Run a read-only SQL query against the connected NousViz data platform and get rows back "
    "as JSON. Use this to explore datasets, answer data questions, and iterate on a query "
    "before building a dashboard from it. Keep queries read-only; the server enforces this.",
    {"sql": _str("The SQL to execute. Required."),
     "db_engine": {"type": "string", "enum": ["postgres", "clickhouse", "mysql"],
                   "description": "Engine to run against. Default postgres."},
     "database": _str("Optional database name for engines that need one."),
     "max_rows": {"type": "integer", "description": "Row cap for the result. Server enforces its own maximum."}},
    required=["sql"],
)

PUSH_SCHEMA = _schema(
    "nousviz_push",
    "Send a JSON payload into a NousViz inbound webhook endpoint, storing it as a data event. "
    "Use this to land collected data (scraped numbers, API results, metrics) in NousViz so it "
    "can be dashboarded and alerted on. The endpoint slug comes from the NousViz Webhooks page.",
    {"slug": _str("The inbound webhook endpoint slug (from NousViz > Webhooks). Required."),
     "payload": {"type": "object", "description": "The JSON object to store. Required.",
                 "additionalProperties": True},
     "secret": _str("Optional endpoint secret; when set, the request is HMAC-signed.")},
    required=["slug", "payload"],
)

CREATE_DASHBOARD_SCHEMA = _schema(
    "nousviz_create_dashboard",
    "Create a dashboard in NousViz with the given widgets and layout, and return its slug and "
    "URL. Use after exploring data with nousviz_query, to turn a useful view into a persistent "
    "dashboard the user keeps. Widgets/layout/sources use NousViz's dashboard JSON shapes.",
    {"name": _str("Dashboard name. Required."),
     "description": _str("One-line description of what the dashboard shows."),
     "widgets": {"type": "array", "description": "NousViz widget definitions.", "items": {"type": "object"}},
     "layout": {"type": "object", "description": "Grid layout keyed by widget id.",
                "additionalProperties": True},
     "sources": {"type": "array", "description": "Data sources the dashboard reads.", "items": {"type": "object"}}},
    required=["name"],
)

CREATE_ALERT_SCHEMA = _schema(
    "nousviz_create_alert",
    "Create an alert rule in NousViz on a numeric metric (threshold drop/rise/absolute or "
    "zero-check), delivered by email or webhook. Use so the user is notified — and the agent "
    "can be called back via an outbound webhook — when the numbers move. Alerts watch a "
    "plugin dataset: data pushed via nousviz_push lives in plugin_id 'webhooks', dataset "
    "'webhook_events'.",
    {"name": _str("Internal alert name. Required."),
     "label": _str("Human-readable label shown in notifications. Required."),
     "description": _str("What this alert watches and why."),
     "plugin_id": _str("NousViz plugin id that owns the dataset."),
     "dataset": _str("Dataset to watch."),
     "metric": _str("Numeric column/metric to evaluate. Required."),
     "aggregation": _str("Aggregation applied to the metric (e.g. sum, avg)."),
     "condition_type": _str("Condition: e.g. drop, rise, absolute, zero. Required."),
     "threshold": {"type": "number", "description": "Threshold value for the condition."},
     "check_frequency": _str("How often to evaluate (as accepted by NousViz)."),
     "check_period": _str("Comparison window (as accepted by NousViz)."),
     "cooldown_hours": {"type": "integer", "description": "Hours to suppress repeats after firing."},
     "notify_channels": {"type": "array", "items": {"type": "string"},
                         "description": "Delivery channels (email / webhook ids)."}},
    required=["name", "label", "plugin_id", "dataset", "metric", "condition_type"],
)

DASHBOARD_LINK_SCHEMA = _schema(
    "nousviz_dashboard_link",
    "Return the full URL for an existing NousViz dashboard slug, to share with the user.",
    {"slug": _str("The dashboard slug. Required.")},
    required=["slug"],
)


# ── handlers ─────────────────────────────────────────────────────────

def handle_query(args: dict, **_kw) -> str:
    try:
        return _ok(_client().query(
            sql=args["sql"], db_engine=args.get("db_engine"),
            database=args.get("database"), max_rows=args.get("max_rows")))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_push(args: dict, **_kw) -> str:
    try:
        return _ok(_client().push(
            slug=args["slug"], payload=args["payload"], secret=args.get("secret")))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_create_dashboard(args: dict, **_kw) -> str:
    try:
        client = _client()
        result = client.create_dashboard(
            name=args["name"], description=args.get("description"),
            widgets=args.get("widgets"), layout=args.get("layout"),
            sources=args.get("sources"))
        slug = result.get("slug")
        if slug:
            result["url"] = client.dashboard_url(slug)
        return _ok(result)
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_create_alert(args: dict, **_kw) -> str:
    try:
        # Pass through only what the agent provided; the server validates the rest.
        return _ok(_client().create_alert({k: v for k, v in args.items() if v is not None}))
    except NousVizError as e:
        return _err(str(e))


def handle_dashboard_link(args: dict, **_kw) -> str:
    try:
        return _ok({"url": _client().dashboard_url(args["slug"])})
    except (NousVizError, KeyError) as e:
        return _err(str(e))


TOOLS = (
    ("nousviz_query",            QUERY_SCHEMA,            handle_query,            "🔍"),
    ("nousviz_push",             PUSH_SCHEMA,             handle_push,             "📥"),
    ("nousviz_create_dashboard", CREATE_DASHBOARD_SCHEMA, handle_create_dashboard, "📊"),
    ("nousviz_create_alert",     CREATE_ALERT_SCHEMA,     handle_create_alert,     "🔔"),
    ("nousviz_dashboard_link",   DASHBOARD_LINK_SCHEMA,   handle_dashboard_link,   "🔗"),
)
