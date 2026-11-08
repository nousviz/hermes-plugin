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
# The factory accepts an optional instance name (multi-instance support).
_get_client: Optional[Callable[..., NousVizClient]] = None


def set_client_factory(factory: Callable[..., NousVizClient]) -> None:
    global _get_client
    _get_client = factory


def _ok(data: Any) -> str:
    return json.dumps({"ok": True, "result": data}, default=str)


def _err(message: str) -> str:
    return json.dumps({"ok": False, "error": message})


def _client(instance: Optional[str] = None) -> NousVizClient:
    if _get_client is None:
        raise NousVizError("nousviz plugin not initialised")
    return _get_client(instance)


# ── schemas ──────────────────────────────────────────────────────────

def _str(description: str) -> dict:
    return {"type": "string", "description": description}


# Optional target-instance selector shared by every tool. Omit to use the
# active instance (set with /nousviz use <name>). See /nousviz list.
_INSTANCE_PROP = {
    "instance": _str(
        "Optional NousViz instance name to target when several are configured "
        "(see /nousviz list). Defaults to the active instance.")
}


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
     "max_rows": {"type": "integer", "description": "Row cap for the result. Server enforces its own maximum."},
     **_INSTANCE_PROP},
    required=["sql"],
)

CATALOG_SCHEMA = _schema(
    "nousviz_catalog",
    "Discover what data exists in NousViz before querying it. Call this FIRST whenever you are "
    "unsure which tables or columns are available — it saves you from guessing SQL. Progressive "
    "detail: with no arguments it returns a terse index (each plugin and its table names, row "
    "counts, and column count); pass plugin_id to get that plugin's tables with their columns "
    "and types; pass plugin_id AND table to get one table's full column schema. Results are "
    "limited by this account's per-plugin access, so you only ever see data you may read. "
    "Covers NousViz's Postgres-backed plugin tables; data in ClickHouse or MySQL engines is "
    "queryable via nousviz_query with db_engine but is not listed here. This is read-only "
    "metadata — it never returns row data.",
    {"plugin_id": _str("Optional plugin slug to drill into (from the index). Omit for the "
                       "top-level index of all accessible plugins."),
     "table": _str("Optional table name for a full column schema; requires plugin_id."),
     **_INSTANCE_PROP},
)

PUSH_SCHEMA = _schema(
    "nousviz_push",
    "Send a JSON payload into a NousViz inbound webhook endpoint, storing it as a data event. "
    "Use this to land collected data (scraped numbers, API results, metrics) in NousViz so it "
    "can be dashboarded and alerted on. The endpoint slug comes from the NousViz Webhooks page.",
    {"slug": _str("The inbound webhook endpoint slug (from NousViz > Webhooks). Required."),
     "payload": {"type": "object", "description": "The JSON object to store. Required.",
                 "additionalProperties": True},
     "secret": _str("Optional endpoint secret; when set, the request is HMAC-signed."),
     **_INSTANCE_PROP},
    required=["slug", "payload"],
)

_WIDGET_ITEM_SCHEMA = {
    "type": "object",
    "description": "One widget. Shape verified against the NousViz v1.0.6 renderer.",
    "properties": {
        "id": {"type": "string", "description": "Unique kebab-case id within the dashboard."},
        "type": {"type": "string",
                 "enum": ["heading", "text", "divider", "kpi", "table",
                          "line_chart", "bar_chart", "stacked_bar_chart"]},
        "config": {
            "type": "object",
            "description":
                "Per-type config. kpi: {label, custom_sql, format?: currency|number|percent} — "
                "SQL must return ONE row with a column named exactly `value`. "
                "line_chart/bar_chart/stacked_bar_chart: {title, custom_sql, x: '<col>', "
                "y: ['<col>', ...], labels?: ['<display name>', ...]} — SQL returns the x column "
                "plus one numeric column per y entry, ordered by x. "
                "table: {title, custom_sql, columns: [{field, label}, ...]}. "
                "text: {text} (plain text, newlines ok). heading: {text, level?: h1|h2|h3}. "
                "divider: {}. custom_sql must be read-only SELECT, written in the dashboard's "
                "db_engine dialect.",
            "additionalProperties": True,
        },
        "layout": {
            "type": "object",
            "description": "Grid placement on a 12-column grid: {x, y, w, h}. x+w must be <= 12. "
                           "Typical: KPIs w=4 h=3, charts w=6 h=6, full-width text w=12 h=3-4.",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                           "w": {"type": "integer"}, "h": {"type": "integer"}},
            "additionalProperties": True,
        },
    },
    "required": ["id", "type", "config", "layout"],
    "additionalProperties": True,
}

CREATE_DASHBOARD_SCHEMA = _schema(
    "nousviz_create_dashboard",
    "Create a dashboard in NousViz with the given widgets and return its slug and URL. Use "
    "after exploring data with nousviz_query, to turn a useful view into a persistent "
    "dashboard the user keeps. Workflow: explore with nousviz_query, verify each widget's SQL "
    "returns the exact column shape its type needs, then create. The dashboard queries the "
    "engine named in layout.db_engine (postgres default, or clickhouse/mysql) — write every "
    "widget's custom_sql in that engine's dialect, and test it via nousviz_query with the same "
    "db_engine first.",
    {"name": _str("Dashboard name. Required."),
     "description": _str("One-line description of what the dashboard shows."),
     "widgets": {"type": "array", "description": "Widget definitions (see item schema).",
                 "items": _WIDGET_ITEM_SCHEMA},
     "layout": {"type": "object",
                "description": "Dashboard-level options. Set {\"db_engine\": \"postgres\"|"
                               "\"clickhouse\"|\"mysql\"} to pick which engine ALL widget "
                               "custom_sql runs against (default postgres). One engine per "
                               "dashboard.",
                "additionalProperties": True},
     "sources": {"type": "array", "description": "Data sources the dashboard reads (optional metadata).",
                 "items": {"type": "object"}},
     **_INSTANCE_PROP},
    required=["name", "widgets"],
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
                         "description": "Delivery channels (email / webhook ids)."},
     **_INSTANCE_PROP},
    required=["name", "label", "plugin_id", "dataset", "metric", "condition_type"],
)

DASHBOARD_LINK_SCHEMA = _schema(
    "nousviz_dashboard_link",
    "Return the full URL for an existing NousViz dashboard slug. Note: dashboards the agent "
    "creates are owned by the agent's account, so a plain dashboard URL will not open for other "
    "users — use nousviz_share_dashboard to get a link the user can actually view.",
    {"slug": _str("The dashboard slug. Required."),
     **_INSTANCE_PROP},
    required=["slug"],
)

SHARE_DASHBOARD_SCHEMA = _schema(
    "nousviz_share_dashboard",
    "Create a public share link for a dashboard so the user (or their team) can view it without "
    "signing in. Returns a {base}/shared/{id} URL. Use this whenever the user wants to SEE a "
    "dashboard the agent built — a plain dashboard URL won't open for them because the agent owns "
    "it. Optionally password-protect or set an expiry.",
    {"slug": _str("The dashboard slug to share. Required."),
     "title": _str("Optional title shown on the shared page."),
     "password": _str("Optional password to protect the link."),
     "expires_hours": {"type": "integer", "description": "Link lifetime in hours (default 168 = 7 days)."},
     **_INSTANCE_PROP},
    required=["slug"],
)


# ── handlers ─────────────────────────────────────────────────────────

def handle_query(args: dict, **_kw) -> str:
    try:
        return _ok(_client(args.get("instance")).query(
            sql=args["sql"], db_engine=args.get("db_engine"),
            database=args.get("database"), max_rows=args.get("max_rows")))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def _terse_index(raw: dict) -> dict:
    """Shrink GET /api/catalog/tables to a token-cheap index: per plugin, each
    table's name, estimated row count, and column count — but not the columns
    themselves. The agent drills into a plugin/table for columns on demand."""
    plugins = []
    for p in raw.get("plugins", []):
        tables = []
        for t in p.get("tables", []):
            tables.append({
                "table": t.get("name"),
                "rows": t.get("row_count_estimate"),
                "columns": len(t.get("columns") or []),
            })
        plugins.append({"plugin_id": p.get("id"), "tables": tables})
    return {
        "plugins": plugins,
        "hint": "Call nousviz_catalog with plugin_id to see a plugin's columns, "
                "then plugin_id+table for one table's full schema.",
    }


def _terse_plugin(raw: dict) -> dict:
    """Shrink one plugin's tables to name + {column: type} maps (drops
    nullable/default, which the single-table view still carries)."""
    tables = []
    for t in raw.get("tables", []):
        tables.append({
            "table": t.get("name"),
            "rows": t.get("row_count_estimate"),
            "columns": {c.get("name"): c.get("data_type")
                        for c in (t.get("columns") or [])},
        })
    out: dict[str, Any] = {"plugin_id": raw.get("plugin_id"), "tables": tables}
    if raw.get("manifest_drift"):
        out["manifest_drift"] = raw["manifest_drift"]
    return out


def handle_catalog(args: dict, **_kw) -> str:
    try:
        plugin_id = args.get("plugin_id")
        table = args.get("table")
        client = _client(args.get("instance"))
        raw = client.catalog(plugin_id=plugin_id, table=table)
        if plugin_id and table:
            return _ok(raw)              # full single-table schema, as-is
        if plugin_id:
            return _ok(_terse_plugin(raw))
        return _ok(_terse_index(raw))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_push(args: dict, **_kw) -> str:
    try:
        return _ok(_client(args.get("instance")).push(
            slug=args["slug"], payload=args["payload"], secret=args.get("secret")))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_create_dashboard(args: dict, **_kw) -> str:
    try:
        client = _client(args.get("instance"))
        result = client.create_dashboard(
            name=args["name"], description=args.get("description"),
            widgets=args.get("widgets"), layout=args.get("layout"),
            sources=args.get("sources"))
        slug = result.get("slug")
        if slug:
            result["url"] = client.dashboard_url(slug)
            # Agent-created dashboards are owned by the agent account, so a plain
            # URL 404s for other users. Attach a share link (best effort) so the
            # human can actually open it.
            try:
                share = client.create_share(slug, title=args.get("name"))
                result["share_url"] = share.get("url")
            except NousVizError:
                pass
        return _ok(result)
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_share_dashboard(args: dict, **_kw) -> str:
    try:
        return _ok(_client(args.get("instance")).create_share(
            slug=args["slug"], title=args.get("title"),
            password=args.get("password"),
            expires_hours=int(args.get("expires_hours") or 168)))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_create_alert(args: dict, **_kw) -> str:
    try:
        # Pass through only what the agent provided; the server validates the rest.
        # 'instance' selects the target server and is not part of the alert body.
        fields = {k: v for k, v in args.items() if v is not None and k != "instance"}
        return _ok(_client(args.get("instance")).create_alert(fields))
    except NousVizError as e:
        return _err(str(e))


def handle_dashboard_link(args: dict, **_kw) -> str:
    try:
        return _ok({"url": _client(args.get("instance")).dashboard_url(args["slug"])})
    except (NousVizError, KeyError) as e:
        return _err(str(e))


TOOLS = (
    ("nousviz_catalog",          CATALOG_SCHEMA,          handle_catalog,          "🗂️"),
    ("nousviz_query",            QUERY_SCHEMA,            handle_query,            "🔍"),
    ("nousviz_push",             PUSH_SCHEMA,             handle_push,             "📥"),
    ("nousviz_create_dashboard", CREATE_DASHBOARD_SCHEMA, handle_create_dashboard, "📊"),
    ("nousviz_create_alert",     CREATE_ALERT_SCHEMA,     handle_create_alert,     "🔔"),
    ("nousviz_dashboard_link",   DASHBOARD_LINK_SCHEMA,   handle_dashboard_link,   "🔗"),
    ("nousviz_share_dashboard",  SHARE_DASHBOARD_SCHEMA,  handle_share_dashboard,  "🌐"),
)
