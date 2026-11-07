# Changelog

## 0.1.0 — scaffold (unreleased)

- Six tools: `nousviz_query`, `nousviz_push`, `nousviz_create_dashboard`,
  `nousviz_create_alert`, `nousviz_dashboard_link`, `nousviz_share_dashboard`.
- `nousviz_create_dashboard` carries the verified v1.0.6 widget schema
  (kpi / table / line_chart / bar_chart / stacked_bar_chart / heading /
  text / divider) and a per-dashboard `layout.db_engine`
  (postgres / clickhouse / mysql).
- Agent-created dashboards are owner-scoped, so `create_dashboard`
  auto-creates a public share link and returns `share_url`;
  `nousviz_share_dashboard` creates one on demand (optional password /
  expiry).
- `/nousviz` status command (tool list derived dynamically so it can't
  drift); `/nousviz mission-control` provisions an agent-activity
  dashboard.
- Optional Mission Control telemetry (`post_tool_call` → inbound webhook,
  flushed every 25 events and at session end; metadata only — tool name,
  status, duration, ids — never tool arguments or results). No-op until
  `telemetry_webhook_slug` is configured.
- `scripts/create-agent-user.py` — create the NousViz service account
  directly, bypassing the email-invite flow.
- Session-token auth against stock NousViz >= 1.0.6; password via the
  Hermes secret scope (`NOUSVIZ_PASSWORD`).
