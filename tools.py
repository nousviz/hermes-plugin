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

# Set by register() when feedback delivery is wired (Slack / Resend).
_feedback_send: Optional[Callable[[dict], dict]] = None


def set_client_factory(factory: Callable[..., NousVizClient]) -> None:
    global _get_client
    _get_client = factory


def set_feedback_sender(fn: Optional[Callable[[dict], dict]]) -> None:
    global _feedback_send
    _feedback_send = fn


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
    "metadata — it never returns row data. When you drill into a plugin (pass plugin_id), the "
    "result also carries the operator's own semantics where they defined them — each table's "
    "label, description and semantic_type, plus the plugin's description — so prefer those "
    "meanings over guessing from column names. Datasets the catalog can't introspect (e.g. "
    "ClickHouse- or MySQL-backed, which the Postgres-only catalog doesn't list) still appear "
    "under `documented_datasets` with their labels/descriptions and `db` engine, so you learn "
    "they exist and what they mean even though their columns aren't listed — query them with "
    "nousviz_query using that db_engine. For curated metrics and findings, also see "
    "nousviz_insights.",
    {"plugin_id": _str("Optional plugin slug to drill into (from the index). Omit for the "
                       "top-level index of all accessible plugins."),
     "table": _str("Optional table name for a full column schema; requires plugin_id."),
     **_INSTANCE_PROP},
)

INSIGHTS_SCHEMA = _schema(
    "nousviz_insights",
    "Read the operator's curated insights from NousViz — the metrics and findings they (or the "
    "plugin authors) defined as worth surfacing, each with a severity and a human description. "
    "Use this to learn what MATTERS in the data, not just what exists: it's where domain meaning "
    "the schema can't tell you lives (defined KPIs, known issues, what a number signals). Good to "
    "check alongside nousviz_catalog when answering an analytical question or deciding what to "
    "highlight. Read-only.",
    {"plugin_id": _str("Optional plugin slug to show only that plugin's insights."),
     "limit": {"type": "integer", "description": "Max insights to return (default 20)."},
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

CREATE_ANNOTATION_SCHEMA = _schema(
    "nousviz_create_annotation",
    "Write an annotation onto NousViz's timeline — a durable note pinned to a date, optionally "
    "scoped to a plugin/dataset. Use this to RECORD what you learn so it survives the "
    "conversation: a known promo that explains a spike, a sync that started failing on a date, a "
    "definition the user gave you, or an insight worth keeping. Annotations are read back later "
    "(by you and by the user in NousViz), so this is how the agent builds lasting understanding "
    "of the data rather than re-deriving it every session. Needs the annotations.write permission "
    "(the analyst role has it).",
    {"title": _str("Short title for the annotation. Required."),
     "date_start": _str("ISO date (YYYY-MM-DD) or datetime the annotation anchors to on the "
                        "timeline. Required."),
     "date_end": _str("Optional end date/datetime for a range (ISO)."),
     "description": _str("Fuller note body — what happened and why it matters."),
     "plugin_id": _str("Optional plugin slug this annotation is about (from nousviz_catalog)."),
     "dataset": _str("Optional dataset/table the annotation is about."),
     "category": _str("Kind of note, e.g. note (default), event, promo, incident, definition."),
     "severity": _str("info (default), warning, critical, good, or tip."),
     "color": _str("Optional display color (hex or token)."),
     "tags": {"type": "array", "items": {"type": "string"},
              "description": "Optional labels for filtering."},
     "pinned": {"type": "boolean", "description": "Pin to the top of the timeline."},
     "semantic_meaning": _str("What this annotation means for interpreting the data — the "
                              "durable insight the next session should know."),
     "semantic_score": {"type": "string", "enum": ["useful", "neutral", "useless"],
                        "description": "How useful this signal is for analysis."},
     "semantic_note": _str("Extra semantic context."),
     "impact_scope": {"type": "array", "items": {"type": "string"},
                      "description": "Which metrics/areas this affects."},
     "scope_filters": {"type": "object", "additionalProperties": True,
                       "description": "Optional structured filters narrowing what the annotation "
                                      "applies to."},
     **_INSTANCE_PROP},
    required=["title", "date_start"],
)

LIST_ALERTS_SCHEMA = _schema(
    "nousviz_list_alerts",
    "List the alert rules configured in NousViz, so you can show the user what's watching their "
    "data and reference an alert by id to test, edit or delete it. Optional filters by plugin or "
    "enabled-only.",
    {"plugin_id": _str("Only alerts on this plugin's data."),
     "enabled_only": {"type": "boolean", "description": "Only enabled alerts."},
     **_INSTANCE_PROP},
)

TEST_ALERT_SCHEMA = _schema(
    "nousviz_test_alert",
    "Dry-run an existing alert and report whether it WOULD fire right now (e.g. 'Would fire on 3 "
    "of 40 rows') — no notification is sent and nothing is recorded. Use this right after "
    "creating or editing an alert so the user can see its behaviour before trusting it, and to "
    "tune out noise: if it would fire on meaningless low-volume rows, raise min_baseline or the "
    "threshold with nousviz_update_alert and test again.",
    {"alert_id": _str("The alert id to test (from nousviz_list_alerts). Required."),
     **_INSTANCE_PROP},
    required=["alert_id"],
)

UPDATE_ALERT_SCHEMA = _schema(
    "nousviz_update_alert",
    "Edit an existing alert conversationally — change its threshold, sensitivity or on/off state, "
    "then re-test. KEY anti-noise knobs: `min_baseline` makes a drop/rise alert fire only when the "
    "baseline average exceeds it (set this so sparse data — e.g. a program with one FTD last week "
    "— doesn't trigger meaningless alerts); `cooldown_hours` suppresses repeat-firing. Only the "
    "fields you pass are changed.",
    {"alert_id": _str("The alert id to update (from nousviz_list_alerts). Required."),
     "threshold": {"type": "number", "description": "Condition threshold (e.g. -20 for a 20% drop)."},
     "min_baseline": {"type": "number", "description": "Minimum baseline average required before "
                      "a drop/rise alert can fire — the main noise filter for low-volume data."},
     "cooldown_hours": {"type": "integer", "description": "Hours to suppress repeats after firing."},
     "enabled": {"type": "boolean", "description": "Turn the alert on/off."},
     "condition_type": _str("threshold_drop | threshold_rise | absolute_above | absolute_below | zero."),
     "aggregation": _str("sum | avg | etc. applied to the metric."),
     "metric": _str("Numeric column/metric to evaluate."),
     "check_frequency": _str("How often to evaluate (e.g. daily)."),
     "check_period": _str("Window to evaluate (e.g. yesterday)."),
     "label": _str("Human-readable label."),
     "description": _str("What this alert watches and why."),
     **_INSTANCE_PROP},
    required=["alert_id"],
)

DELETE_ALERT_SCHEMA = _schema(
    "nousviz_delete_alert",
    "Delete an alert rule. Use when the user no longer wants it. Irreversible — confirm the id "
    "with nousviz_list_alerts first.",
    {"alert_id": _str("The alert id to delete. Required."),
     **_INSTANCE_PROP},
    required=["alert_id"],
)

LIST_ANNOTATIONS_SCHEMA = _schema(
    "nousviz_list_annotations",
    "Read annotations back from NousViz — the durable notes and insights you (or the user) "
    "previously recorded with nousviz_create_annotation. Call this EARLY when working with a "
    "plugin's data so you recall what was already learned (known promos, data caveats, "
    "definitions, prior findings) instead of re-deriving it. Filter by plugin, dataset, date "
    "range, category or semantic_score.",
    {"plugin_id": _str("Only annotations about this plugin's data."),
     "dataset": _str("Only annotations about this dataset/table."),
     "category": _str("Filter by category (e.g. note, promo, incident, definition)."),
     "date_from": _str("ISO date lower bound."),
     "date_to": _str("ISO date upper bound."),
     "semantic_score": {"type": "string", "enum": ["useful", "neutral", "useless"],
                        "description": "Filter by how useful the annotation was scored."},
     "pinned": {"type": "boolean", "description": "Only pinned annotations."},
     "limit": {"type": "integer", "description": "Max to return (default 200, server max 1000)."},
     **_INSTANCE_PROP},
)

FEEDBACK_SCHEMA = _schema(
    "nousviz_feedback",
    "Send feedback to the plugin builder — a thumbs up/down plus a note — so what users and you "
    "learn in chat flows back to whoever maintains the plugin. Use it when the user rates an "
    "answer, when an alert or insight was noisy or wrong, or when you spot a data/semantic gap "
    "worth fixing at the source (a mislabeled field, a missing definition). Delivered to the "
    "builder's configured channels (Slack and/or email via Resend). This complements fixing the "
    "immediate issue — e.g. still tune a noisy alert now, AND send feedback so the default "
    "improves for everyone.",
    {"rating": {"type": "string", "enum": ["up", "down"],
                "description": "Thumbs up or down."},
     "subject": {"type": "string",
                 "enum": ["alert", "insight", "semantic", "data", "answer", "general"],
                 "description": "What the feedback is about."},
     "note": _str("What was good or wrong, in the user's words where possible. Required."),
     "plugin_id": _str("The plugin this is about (from nousviz_catalog), if specific."),
     "suggested_fix": _str("A concrete improvement, if you or the user has one "
                           "(e.g. 'add a column glossary for rs_com', 'raise default min_baseline')."),
     "context": _str("Optional extra context (the dataset, the alert id, the question asked).")},
    required=["note"],
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


_SEMANTIC_KEYS = ("label", "description", "grain", "semantic_type")


def _manifest_datasets(detail: Optional[dict]) -> dict:
    """Map dataset name -> full manifest dataset dict from a GET /api/plugins/{id}
    response. This is the RAW manifest `datasets:` block (un-enriched), so it
    includes ClickHouse/MySQL datasets the Postgres-only catalog can't see."""
    out: dict[str, dict] = {}
    for ds in (detail or {}).get("datasets") or []:
        if isinstance(ds, dict) and ds.get("name"):
            out[ds["name"]] = ds
    return out


def _sem_fields(ds: dict) -> dict:
    """Pick just the semantic annotations from a manifest dataset dict."""
    return {k: ds[k] for k in _SEMANTIC_KEYS if ds.get(k)}


# Back-compat helper: dataset name -> semantic fields.
def _dataset_semantics(detail: Optional[dict]) -> dict:
    return {name: s for name, ds in _manifest_datasets(detail).items()
            if (s := _sem_fields(ds))}


def _terse_plugin(raw: dict, detail: Optional[dict] = None) -> dict:
    """One plugin's catalog tables as name + {column: type} maps, with the
    operator's manifest semantics layered on, the plugin's own description
    surfaced, AND any manifest datasets the catalog can't introspect (e.g.
    ClickHouse/MySQL-backed) surfaced as `documented_datasets` so the agent
    still learns they exist and what they mean."""
    ds_by_name = _manifest_datasets(detail)
    tables = []
    catalog_names: set[str] = set()
    for t in raw.get("tables", []):
        name = t.get("name")
        catalog_names.add(name)
        entry: dict[str, Any] = {
            "table": name,
            "rows": t.get("row_count_estimate"),
            "columns": {c.get("name"): c.get("data_type")
                        for c in (t.get("columns") or [])},
        }
        entry.update(_sem_fields(ds_by_name.get(name, {})))  # label/description/grain/semantic_type
        tables.append(entry)

    # Manifest datasets with no Postgres catalog table — typically ClickHouse/
    # MySQL. Columns aren't introspectable here; surface name + meaning + engine
    # so the agent knows to query them (nousviz_query with the right db_engine).
    documented = []
    for name, ds in ds_by_name.items():
        if name in catalog_names:
            continue
        d: dict[str, Any] = {
            "table": name,
            "introspected": False,
            "note": "Not a Postgres catalog table (columns not introspected). "
                    "Query it with nousviz_query using the right db_engine.",
        }
        if ds.get("db"):
            d["db"] = ds["db"]
        d.update(_sem_fields(ds))
        documented.append(d)

    out: dict[str, Any] = {"plugin_id": raw.get("plugin_id"), "tables": tables}
    if documented:
        out["documented_datasets"] = documented
    if detail:
        if detail.get("description"):
            out["plugin_description"] = detail["description"]
        if detail.get("long_description"):
            out["plugin_long_description"] = detail["long_description"]
    if raw.get("manifest_drift"):
        out["manifest_drift"] = raw["manifest_drift"]
    return out


def handle_catalog(args: dict, **_kw) -> str:
    try:
        plugin_id = args.get("plugin_id")
        table = args.get("table")
        client = _client(args.get("instance"))
        raw = client.catalog(plugin_id=plugin_id, table=table)
        if not plugin_id:
            return _ok(_terse_index(raw))   # structural index, no semantics
        # Drilling into a plugin -> layer in operator semantics (best effort;
        # a server that lacks the endpoint or the perm just omits them).
        try:
            detail = client.plugin_detail(plugin_id)
        except NousVizError:
            detail = None
        if table:
            # full single-table schema + this dataset's semantics, if any
            sem = _dataset_semantics(detail).get(table)
            if sem and isinstance(raw, dict):
                raw = {**raw, **sem}
            return _ok(raw)
        return _ok(_terse_plugin(raw, detail))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_insights(args: dict, **_kw) -> str:
    try:
        data = _client(args.get("instance")).insights(limit=int(args.get("limit") or 20))
        rows = data.get("insights", data if isinstance(data, list) else [])
        wanted = args.get("plugin_id")
        if wanted:
            rows = [r for r in rows if r.get("plugin_id") == wanted]
        terse = [{k: r.get(k) for k in ("plugin_id", "title", "description", "severity")
                  if r.get(k) is not None} for r in rows]
        return _ok({"insights": terse, "total": data.get("total", len(terse))})
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


def handle_create_annotation(args: dict, **_kw) -> str:
    try:
        if not args.get("title") or not args.get("date_start"):
            return _err("nousviz_create_annotation requires 'title' and 'date_start'.")
        # Pass through what the agent set; the server validates the rest.
        # 'instance' selects the target server and is not part of the body.
        fields = {k: v for k, v in args.items() if v is not None and k != "instance"}
        return _ok(_client(args.get("instance")).create_annotation(fields))
    except NousVizError as e:
        return _err(str(e))


def _terse_alert(a: dict) -> dict:
    keys = ("id", "name", "label", "plugin_id", "dataset", "metric", "aggregation",
            "condition_type", "threshold", "min_baseline", "cooldown_hours",
            "check_frequency", "enabled")
    return {k: a.get(k) for k in keys if a.get(k) is not None}


def handle_list_alerts(args: dict, **_kw) -> str:
    try:
        data = _client(args.get("instance")).list_alerts(
            plugin_id=args.get("plugin_id"), enabled_only=bool(args.get("enabled_only")))
        rows = data.get("alerts", data if isinstance(data, list) else [])
        return _ok({"alerts": [_terse_alert(a) for a in rows]})
    except NousVizError as e:
        return _err(str(e))


def handle_test_alert(args: dict, **_kw) -> str:
    try:
        return _ok(_client(args.get("instance")).test_alert(args["alert_id"]))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_update_alert(args: dict, **_kw) -> str:
    try:
        fields = {k: v for k, v in args.items()
                  if v is not None and k not in ("instance", "alert_id")}
        if not fields:
            return _err("nousviz_update_alert: pass at least one field to change.")
        return _ok(_client(args.get("instance")).update_alert(args["alert_id"], fields))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_delete_alert(args: dict, **_kw) -> str:
    try:
        return _ok(_client(args.get("instance")).delete_alert(args["alert_id"]))
    except (NousVizError, KeyError) as e:
        return _err(str(e))


def handle_list_annotations(args: dict, **_kw) -> str:
    try:
        filters = {k: v for k, v in args.items() if v is not None and k != "instance"}
        return _ok(_client(args.get("instance")).list_annotations(**filters))
    except NousVizError as e:
        return _err(str(e))


def handle_feedback(args: dict, **_kw) -> str:
    try:
        if _feedback_send is None:
            return _err("Feedback isn't configured. Ask the operator to add a `feedback` block "
                        "(slack_webhook_secret and/or resend) to the nousviz plugin settings.")
        if not args.get("note"):
            return _err("nousviz_feedback requires a 'note'.")
        payload = {k: v for k, v in args.items() if v is not None}
        return _ok(_feedback_send(payload))
    except NousVizError as e:
        return _err(str(e))
    except Exception as e:  # feedback delivery errors (FeedbackError, network)
        return _err(str(e))


def handle_dashboard_link(args: dict, **_kw) -> str:
    try:
        return _ok({"url": _client(args.get("instance")).dashboard_url(args["slug"])})
    except (NousVizError, KeyError) as e:
        return _err(str(e))


TOOLS = (
    ("nousviz_catalog",          CATALOG_SCHEMA,          handle_catalog,          "🗂️"),
    ("nousviz_insights",         INSIGHTS_SCHEMA,         handle_insights,         "💡"),
    ("nousviz_query",            QUERY_SCHEMA,            handle_query,            "🔍"),
    ("nousviz_push",             PUSH_SCHEMA,             handle_push,             "📥"),
    ("nousviz_create_dashboard", CREATE_DASHBOARD_SCHEMA, handle_create_dashboard, "📊"),
    ("nousviz_create_alert",     CREATE_ALERT_SCHEMA,     handle_create_alert,     "🔔"),
    ("nousviz_list_alerts",      LIST_ALERTS_SCHEMA,      handle_list_alerts,      "📋"),
    ("nousviz_test_alert",       TEST_ALERT_SCHEMA,       handle_test_alert,       "🧪"),
    ("nousviz_update_alert",     UPDATE_ALERT_SCHEMA,     handle_update_alert,     "🔧"),
    ("nousviz_delete_alert",     DELETE_ALERT_SCHEMA,     handle_delete_alert,     "🗑️"),
    ("nousviz_create_annotation", CREATE_ANNOTATION_SCHEMA, handle_create_annotation, "📝"),
    ("nousviz_list_annotations", LIST_ANNOTATIONS_SCHEMA, handle_list_annotations, "📖"),
    ("nousviz_feedback",         FEEDBACK_SCHEMA,         handle_feedback,         "📣"),
    ("nousviz_dashboard_link",   DASHBOARD_LINK_SCHEMA,   handle_dashboard_link,   "🔗"),
    ("nousviz_share_dashboard",  SHARE_DASHBOARD_SCHEMA,  handle_share_dashboard,  "🌐"),
)
