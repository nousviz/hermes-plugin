# Changelog

## 0.3.0 — data catalog

- New `nousviz_catalog` tool: the agent can discover what data exists
  before writing SQL, instead of guessing table and column names. Reads
  NousViz's live catalog (`/api/catalog/*`, viewer-level `datasets.read`).
- Progressive detail to keep context small: no args returns a terse index
  (each plugin → its table names, row counts, column counts); `plugin_id`
  returns that plugin's tables with `{column: type}` maps; `plugin_id` +
  `table` returns one table's full column schema. The agent drills in only
  as far as the question needs.
- Results are scoped to the plugins the agent's account may read
  (per-plugin ACL), so the catalog never exposes data the agent can't query.
- Covers NousViz's Postgres-backed plugin tables; ClickHouse/MySQL data
  stays queryable via `nousviz_query` with `db_engine` but isn't enumerated.

## 0.2.0 — multiple servers

- One agent can now connect to several NousViz installs. Configure an
  `instances` map (`{<name>: {base_url, email, password_secret?}}`) with an
  optional `default_instance`; each instance's password comes from the secret
  scope (`NOUSVIZ_PASSWORD` for `default`, `NOUSVIZ_PASSWORD_<NAME>` otherwise,
  or a per-instance `password_secret`).
- `/nousviz list` shows configured instances and which is active;
  `/nousviz use <name>` switches the active instance, remembered per Hermes
  profile (via profile-scoped plugin state).
- Every tool accepts an optional `instance` argument to target one server for a
  single call without switching the active one.
- The flat single-server config (`base_url` + `email` + `NOUSVIZ_PASSWORD`) is
  unchanged and is treated as an instance named `default` — fully backward
  compatible.

## 0.1.0 — scaffold

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
