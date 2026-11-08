# NousViz — Agentic Analytics for your Hermes agent

Turn [Hermes Agent](https://github.com/NousResearch/hermes-agent) into a self-hosted,
model-agnostic **data analyst**. Connect it to one or more
[NousViz](https://github.com/nousviz/nousviz-app) installs (v1.0.6+) and your Hermes
agent can discover what data you have, answer questions in natural language (read-only
SQL across Postgres / ClickHouse / MySQL), and turn answers into dashboards and alerts
that outlive the conversation — agentic analytics on data you own, with no third party
holding your data or your model.

**NousViz is the system of record. Hermes is data in motion.** The agent explores
conversationally; when a view proves useful it becomes a permanent dashboard.

## What the agent can do

| Tool | What it does |
|---|---|
| `nousviz_catalog` | Discover which plugins, tables and columns exist before querying (progressive: index → plugin → table) |
| `nousviz_query` | Read-only SQL over the platform's datasets (Postgres / ClickHouse / MySQL) |
| `nousviz_push` | Land collected data via an inbound webhook endpoint |
| `nousviz_create_dashboard` | Turn an exploration into a persistent dashboard, returns the URL |
| `nousviz_create_alert` | Threshold / drop / rise / zero-check alerts on any numeric metric |
| `nousviz_create_annotation` | Record durable notes/insights onto the data timeline (the agent's write-back memory) |
| `nousviz_dashboard_link` | Return the URL of an existing dashboard |
| `nousviz_share_dashboard` | Create a public share link a human can open without signing in |

Every tool takes an optional `instance` argument to target one of several
configured NousViz servers (see [Multiple NousViz servers](#multiple-nousviz-servers)).

Plus `/nousviz` for connection status (`/nousviz list` and `/nousviz use <name>`
switch between configured servers), and optional **Mission Control telemetry**:
`post_tool_call` hooks stream the agent's own activity (tool name, status, duration —
never arguments or results) into a NousViz dashboard.

The plugin also bundles a **`nousviz:analyst` skill** that coaches the agent to
work as a data analyst — discover data with `nousviz_catalog` before writing SQL,
answer with read-only queries, then persist useful views as dashboards and
alerts. It triggers on plain-language data questions ("what data do you have?",
"trend of…", "build me a dashboard of…") so the agent looks at the real data
instead of answering generically.

## Widget cookbook

`nousviz_create_dashboard` takes real NousViz widget JSON (shapes verified against the
v1.0.6 renderer). A 12-column grid; each widget is `{id, type, config, layout:{x,y,w,h}}`.
Set the engine once per dashboard with `layout: {"db_engine": "postgres"|"clickhouse"|"mysql"}`
(default postgres) and write every widget's `custom_sql` in that dialect.

| Type | config | SQL contract |
|---|---|---|
| `kpi` | `{label, custom_sql, format?}` | one row, column named `value` |
| `line_chart` / `bar_chart` / `stacked_bar_chart` | `{title, custom_sql, x, y: [...], labels?}` | x column + one numeric column per `y` entry |
| `table` | `{title, custom_sql, columns: [{field,label}]}` | columns matching `field`s |
| `text` / `heading` / `divider` | `{text}` / `{text, level?}` / `{}` | none |

```json
{
  "name": "Signups",
  "layout": {"db_engine": "postgres"},
  "widgets": [
    {"id": "total", "type": "kpi",
     "config": {"label": "Signups (30d)",
                "custom_sql": "SELECT COUNT(*) AS value FROM signups WHERE day > now() - interval '30 days'"},
     "layout": {"x": 0, "y": 0, "w": 4, "h": 3}},
    {"id": "trend", "type": "line_chart",
     "config": {"title": "Daily signups", "x": "day", "y": ["signups"],
                "custom_sql": "SELECT day::text AS day, COUNT(*)::int AS signups FROM signups GROUP BY 1 ORDER BY 1"},
     "layout": {"x": 0, "y": 3, "w": 12, "h": 6}}
  ]
}
```

## The loop

1. *"Track our signups daily; alert me if they drop 10%."*
2. Hermes cron collects → `nousviz_push` stores → `nousviz_create_dashboard` charts →
   `nousviz_create_alert` watches.
3. The alert fires → NousViz's outbound webhook notifies Hermes → the agent
   investigates (deploys? traffic mix? competitor promo?) and messages you the *why*,
   with the chart.

Deterministic work stays deterministic (cron + alert engine). The agent does what
logic can't: setup from a sentence, open-ended diagnosis, and change by conversation.

## Install

```bash
hermes plugins install <this-repo-url>   # or by catalog name once listed
```

Configure in `~/.hermes/config.yaml`:

```yaml
plugins:
  entries:
    nousviz:
      settings:
        base_url: "https://your-nousviz.example.com"
        email: "hermes-agent@example.com"        # a NousViz account for the agent
        # optional — enables Mission Control telemetry:
        telemetry_webhook_slug: "hermes-telemetry"
        telemetry_webhook_secret: "..."
```

The NousViz account password is read from the Hermes secret scope as
`NOUSVIZ_PASSWORD` (never stored in plugin config). Create a dedicated NousViz user
for the agent (analyst role is enough: it needs `query.run`, `dashboards.write`,
`alerts.write`).

### Multiple NousViz servers

To connect one agent to several NousViz installs, use an `instances` map instead
of (or alongside) the flat `base_url`/`email`:

```yaml
plugins:
  entries:
    nousviz:
      settings:
        default_instance: "affiliate"     # optional; used when none is active
        instances:
          affiliate:
            base_url: "https://affiliate.example.com"
            email: "hermes-agent@example.com"
            # password_secret: "NOUSVIZ_PASSWORD_AFFILIATE"  # optional override
          complaints:
            base_url: "https://complaints.example.com"
            email: "hermes-agent@example.com"
```

Each instance's password comes from the secret scope: the `password_secret` key if
set, otherwise `NOUSVIZ_PASSWORD` for an instance literally named `default` and
`NOUSVIZ_PASSWORD_<NAME>` (name upper-cased, non-alphanumerics → `_`) for any other
— e.g. `NOUSVIZ_PASSWORD_AFFILIATE`. Switch the active instance with
`/nousviz use <name>` (remembered per Hermes profile), see them with
`/nousviz list`, or target one for a single call via each tool's `instance`
argument. The flat single-server form still works and is treated as an instance
named `default`.

## Requirements

- NousViz >= 1.0.6 (uses only stock endpoints: `/api/auth/login`, `/api/query`,
  `/api/dashboards/`, `/api/alerts`, `/api/webhooks/in/<slug>`)
- Network access from Hermes to your NousViz server (disclosed: this plugin makes
  HTTPS requests to the `base_url` you configure, and nowhere else)

## License

MIT
