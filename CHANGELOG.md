# Changelog

## 0.11.0 — builder feedback destination goes live

- The builder feedback destination (`BUILDER_FEEDBACK_URL` in `feedback.py`) is
  now wired to a hosted collector, so `nousviz_feedback` routes a thumbs
  up/down plus a note from **every** install to the plugin builder. The
  collector forwards to Slack and emails via Resend; both credentials stay
  server-side (the public repo ships only the collector URL and a revocable
  `X-Feedback-Token`, never a Slack webhook or Resend key). No per-install
  `feedback` config block is required anymore — it still works as an override
  for operators who want their own destination.

## 0.10.0 — onboard new users + builder feedback destination

- `/nousviz` now greets new users with a getting-started line, and a new
  **`/nousviz coach`** scores your data's **semantic coverage** (how many tables
  carry a `datasets:` description) and names the biggest gaps to document — so a
  new operator knows exactly how to make the agent understand their data.
- `nousviz_feedback` can now ship to a **builder destination** baked into the
  plugin (`BUILDER_FEEDBACK_URL` in `feedback.py`), so feedback reaches the
  plugin builder from *every* install — not just the local operator. The posted
  JSON carries a Slack-renderable `text` plus structured fields, so the URL can
  be a Slack incoming webhook (quick) or a collector you host that forwards to
  Slack + email via Resend (recommended — keeps the Resend key server-side; a
  Resend API key must never ship in a public plugin). Optional
  `BUILDER_FEEDBACK_TOKEN` is sent as `X-Feedback-Token` for a collector.

## 0.9.0 — feedback to the plugin builder

- New `nousviz_feedback` tool: the agent routes a thumbs up/down plus a note to
  the plugin builder's channels, so what users and the agent learn in chat flows
  back to whoever maintains the plugin (a noisy alert, a mislabeled field, a
  missing definition). Complements fixing the issue in the moment — e.g. tune a
  noisy alert now AND send feedback so the default improves for everyone.
- Delivery is opt-in via a `feedback` settings block, routing to **Slack**
  (incoming webhook) and/or **email via Resend** — any configured channel is
  delivered to:

  ```yaml
  feedback:
    slack_webhook_secret: SLACK_FEEDBACK_WEBHOOK   # secret-scope key w/ the Slack URL
    resend:
      api_key_secret: RESEND_API_KEY               # secret-scope key w/ the Resend API key
      from: "NousViz Feedback <feedback@your-verified-domain>"
      to: "you@example.com"
  ```

  Secrets (the token-bearing Slack URL and the Resend key) come from the Hermes
  secret scope, never plugin config. The tool is a clear no-op with a helpful
  message until configured.

## 0.8.0 — manage alerts by conversation + read annotations back

- Full conversational alert management: `nousviz_list_alerts`,
  `nousviz_test_alert` (dry-run — "Would fire on N of M rows", no notification),
  `nousviz_update_alert`, `nousviz_delete_alert`. A user can now describe an
  alert, have the agent build it (`nousviz_create_alert`), **test** it, **tune**
  it and **edit/remove** it entirely from chat.
- Anti-noise tuning is first-class: `nousviz_update_alert` surfaces
  `min_baseline` (a drop/rise alert fires only when the baseline average exceeds
  it — stops sparse data like a program with one FTD last week from triggering)
  and `cooldown_hours`. Verified against the evaluator (`run_alerts.py`).
- `nousviz_list_annotations` closes the learning loop: the agent can now READ
  back the notes/insights it recorded with `nousviz_create_annotation`
  (`GET /api/annotations`, `annotations.read`), so corrections persist across
  sessions instead of evaporating when the chat ends. Rich filters (plugin,
  dataset, date, category, semantic_score, pinned).
- Alerts remain Postgres-only + single-metric by the engine's design; the agent
  tools don't change that, they make what the engine supports fully editable
  by conversation.

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
