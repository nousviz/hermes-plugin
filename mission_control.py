"""Hermes Mission Control — a provisioned NousViz dashboard over the plugin's telemetry.

Pure data: provisioning creates (or refreshes) a normal user dashboard via the
stock API. No NousViz-side code. The SQL reads the webhooks plugin's
webhook_events table and filters on payload source 'hermes-agent', so it works
on any install regardless of endpoint slug. Postgres dialect (webhook_events
lives in the core Postgres).
"""

from __future__ import annotations

from .nousviz_client import NousVizClient

NAME = "Hermes Mission Control"
DESCRIPTION = ("Live view of the Hermes agent's activity: tool calls, errors, "
               "sessions, and recent actions. Provisioned by the nousviz Hermes "
               "plugin; data arrives via telemetry webhooks. Created by Hermes 🤖")

_EV = ("FROM webhook_events w, jsonb_array_elements(w.payload::jsonb->'events') e "
       "WHERE w.payload::jsonb->>'source'='hermes-agent'")

WIDGETS = [
    {"id": "mc-heading", "type": "heading",
     "config": {"text": "Hermes Mission Control", "level": "h2"},
     "layout": {"x": 0, "y": 0, "w": 12, "h": 1}},
    {"id": "mc-about", "type": "text",
     "config": {"text": "Your agent's activity, streamed here by the nousviz Hermes "
                        "plugin. Only metadata is recorded — tool names, status, "
                        "timing — never arguments or results."},
     "layout": {"x": 0, "y": 1, "w": 12, "h": 2}},
    {"id": "mc-total-calls", "type": "kpi",
     "config": {"label": "Tool calls (all time)",
                "custom_sql": f"SELECT count(*) AS value {_EV}"},
     "layout": {"x": 0, "y": 3, "w": 4, "h": 3}},
    {"id": "mc-errors", "type": "kpi",
     "config": {"label": "Errored calls",
                "custom_sql": f"SELECT count(*) AS value {_EV} AND e->>'status' = 'error'"},
     "layout": {"x": 4, "y": 3, "w": 4, "h": 3}},
    {"id": "mc-sessions", "type": "kpi",
     "config": {"label": "Sessions seen",
                "custom_sql": f"SELECT count(DISTINCT e->>'session_id') AS value {_EV} "
                              "AND e->>'session_id' IS NOT NULL"},
     "layout": {"x": 8, "y": 3, "w": 4, "h": 3}},
    {"id": "mc-calls-per-day", "type": "line_chart",
     "config": {"title": "Tool calls per day", "x": "day", "y": ["calls"],
                "custom_sql": "SELECT to_char(to_timestamp((e->>'ts')::double precision),"
                              f"'YYYY-MM-DD') AS day, count(*)::int AS calls {_EV} "
                              "GROUP BY 1 ORDER BY 1"},
     "layout": {"x": 0, "y": 6, "w": 6, "h": 6}},
    {"id": "mc-top-tools", "type": "bar_chart",
     "config": {"title": "Top tools", "x": "tool", "y": ["calls"],
                "custom_sql": f"SELECT e->>'tool' AS tool, count(*)::int AS calls {_EV} "
                              "GROUP BY 1 ORDER BY 2 DESC LIMIT 10"},
     "layout": {"x": 6, "y": 6, "w": 6, "h": 6}},
    {"id": "mc-recent", "type": "table",
     "config": {"title": "Recent activity",
                "columns": [{"field": "time", "label": "Time"},
                            {"field": "tool", "label": "Tool"},
                            {"field": "status", "label": "Status"},
                            {"field": "duration_ms", "label": "ms"}],
                "custom_sql": "SELECT to_char(to_timestamp((e->>'ts')::double precision),"
                              "'MM-DD HH24:MI:SS') AS time, e->>'tool' AS tool, "
                              "COALESCE(e->>'status','') AS status, "
                              f"COALESCE((e->>'duration_ms')::int, 0) AS duration_ms {_EV} "
                              "ORDER BY (e->>'ts')::double precision DESC LIMIT 20"},
     "layout": {"x": 0, "y": 12, "w": 12, "h": 7}},
]


def provision(client: NousVizClient) -> dict:
    """Create the Mission Control dashboard, or refresh its widgets if it exists.

    Idempotent by name: an existing dashboard keeps its slug (and any shared
    links) and gets the current widget template via PUT.
    """
    existing = client._request("GET", "/api/dashboards/")
    rows = existing.get("dashboards", existing) if isinstance(existing, dict) else existing
    slug = next((d.get("slug") for d in rows or [] if d.get("name") == NAME), None)

    body = dict(name=NAME, description=DESCRIPTION, widgets=WIDGETS,
                layout={"db_engine": "postgres"}, sources=[])
    if slug:
        result = client.update_dashboard(slug, **body)
        result["provisioned"] = "refreshed"
    else:
        result = client.create_dashboard(**body)
        result["provisioned"] = "created"
    result["url"] = client.dashboard_url(result.get("slug", slug))
    return result
