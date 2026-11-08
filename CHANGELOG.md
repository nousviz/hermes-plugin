# Changelog

## 0.7.0 — ClickHouse/MySQL datasets become visible

- `nousviz_catalog` now surfaces manifest `datasets:` entries the catalog
  **can't introspect** — ClickHouse- and MySQL-backed tables — under a new
  `documented_datasets` list, with their `label`, `description`,
  `semantic_type` and `db` engine. The Postgres-only catalog never listed these
  tables, so for stats plugins whose figures live in ClickHouse the agent was
  blind to them; now it learns they exist and what they mean (columns aren't
  introspected — it queries them with `nousviz_query` + the right `db_engine`).
- Reads the raw manifest via `GET /api/plugins/{id}` (not the Postgres-only
  `_enrich_datasets` path), so a `datasets:` entry for a ClickHouse table is no
  longer dropped. Put a short column glossary in each dataset `description` to
  give the agent column-level meaning the catalog can't provide for ClickHouse.

## 0.6.0 — the agent reads the operator's meaning

- `nousviz_catalog` now layers the operator's **manifest semantics** onto the
  structural catalog when you drill into a plugin: each table's `label`,
  `description`, `grain` and `semantic_type` (from the plugin's `datasets:`
  block), plus the plugin's own `description`/`long_description`. Reads
  `GET /api/plugins/{id}` (`plugins.read`, which the analyst role has). The
  agent now prefers the operator's definitions over guessing from column names.
- New `nousviz_insights` tool reads `GET /api/insights/` (`dashboards.read`) —
  the curated metrics and findings defined in plugins' `insights.yaml` (Tier 1)
  and `/insights` endpoints (Tier 2), each with a severity and description.
  Optional `plugin_id` filter. This is where "what MATTERS" lives.
- Both are best-effort and safe: semantics enrichment degrades to
  structure-only if a server lacks the endpoint, and neither tool can reach
  connection secrets (those sit behind `plugins.configure`/admin, which the
  agent's role does not hold).
- The `nousviz:analyst` skill now tells the agent to read these meanings first.

## 0.5.0 — annotations (the agent's write-back memory)

- New `nousviz_create_annotation` tool: the agent can record durable notes and
  insights onto NousViz's timeline (`POST /api/annotations`, `annotations.write`
  — the analyst role has it). Pins a note to a date, optionally scoped to a
  plugin/dataset, with the semantic fields (`semantic_meaning`,
  `semantic_score`, `semantic_note`, `impact_scope`) that make it an analytical
  record, not just a sticky note.
- This closes the learning loop: the agent discovers data (`nousviz_catalog`),
  analyzes it, and writes back what it learned — which it (and the user, in
  NousViz) read next time. Lasting understanding instead of re-derivation.
- The `nousviz:analyst` skill now coaches a "Remember" step: save durable
  findings as annotations.
- Required fields `title` + `date_start` are checked in the handler; everything
  else passes through to the server's `AnnotationCreate` validation.

## 0.4.0 — NousViz Analyst skill

- Bundles a `nousviz:analyst` skill (registered at load via
  `ctx.register_skill`, namespace = plugin name). It coaches the agent to work
  as a data analyst: **discover with `nousviz_catalog` before writing SQL**,
  answer with read-only queries, then persist useful views as dashboards and
  alerts — and to never answer "what data do you have?" generically.
- Fixes the common failure where a plain-language data question ("what data do
  you have access to?") fell through to generic capability handling and never
  touched NousViz.
- The skill's trigger is parsed from its SKILL.md frontmatter, so the text the
  model sees can't drift from the file. Registration is best-effort — a
  missing skill file logs a warning and never breaks the plugin.

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
