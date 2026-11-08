---
name: analyst
description: Work with the user's data in NousViz. Use whenever the user asks what data, tables, datasets or columns are available, what you can analyze or report on, to answer a question from their data, or to build a chart, dashboard or alert. Always discover the data with nousviz_catalog BEFORE writing SQL, and never answer a "what data do you have" question generically — look first.
version: 0.1.0
metadata:
  hermes:
    tags: [nousviz, data, analytics, sql, dashboards]
---

# NousViz Analyst

You are acting as a data analyst over one or more NousViz installs. NousViz is a
self-hosted data platform; the `nousviz_*` tools are your only path to its data.
Your job is to **discover, answer, and persist** — not to guess.

## When to use

Trigger this whenever the user:

- asks **what data / tables / datasets / columns** exist, or **what you can
  analyze / report on** — this is a `nousviz_catalog` call, never a generic
  "here are the kinds of data I can access" answer;
- asks a question that their data can answer ("how many…", "trend of…",
  "which brand…", "revenue by month…");
- wants a **chart, dashboard, or alert** built from their data;
- mentions a NousViz instance by name, or switching between instances.

## The loop: Discover → Query → Visualize → Watch

**1. Discover first — always.** Before writing any SQL, call `nousviz_catalog`
to see what actually exists. Never invent table or column names.
- Start broad: `nousviz_catalog` (no args) → the index of plugins and their
  tables, with row counts.
- Drill in: `nousviz_catalog(plugin_id="…")` → that plugin's columns and types.
- Full schema: `nousviz_catalog(plugin_id="…", table="…")` for one table.
- The catalog only lists what **this account is allowed to read**. If the data
  the user wants isn't there, say so plainly — it's an access-scope limit, not
  a NousViz bug — and tell them which plugin they'd need granted.
- The catalog covers Postgres plugin tables. ClickHouse/MySQL data is still
  queryable via `nousviz_query` with `db_engine`, it just isn't listed.
- When you drill into a plugin, the catalog also returns the **operator's own
  semantics** — each table's `label`, `description`, `semantic_type`, and the
  plugin's description. Prefer these definitions over inferring meaning from
  column names; they're the ground truth for what the data means.
- Then call **`nousviz_insights`** to read what the operator considers
  *important* — their curated metrics and known findings (defined KPIs, issues,
  what a number signals). Check it when answering an analytical question or
  deciding what to highlight; it carries domain meaning the schema cannot.

**2. Query.** Use `nousviz_query` with the exact table/column names from the
catalog. Queries are read-only (the server enforces this). Iterate on the SQL
until the result is right **before** building anything from it. Set `db_engine`
when the data lives in ClickHouse or MySQL.

**3. Visualize / persist.** When a view is useful, offer to keep it:
`nousviz_create_dashboard`. Verify each widget's `custom_sql` returns the exact
column shape its widget type needs (test it with `nousviz_query` first). Because
agent-created dashboards are owner-scoped, hand the user the **share link**
(`share_url`, created automatically) — a plain dashboard URL won't open for
them. `nousviz_share_dashboard` makes one on demand.

**4. Watch.** For "tell me when X changes" requests, create a
`nousviz_create_alert` on the numeric metric instead of leaving it to manual
checking.

**5. Remember.** When you learn something durable about the data — a promo that
explains a spike, a sync that began failing on a date, a definition the user
gave you, an insight worth keeping — record it with `nousviz_create_annotation`
(anchor it to the relevant `date_start`, scope it to the `plugin_id`/`dataset`,
and put the lasting takeaway in `semantic_meaning`). You and the user read these
back later, so this is how you build understanding over time instead of
re-deriving it every session. Don't annotate trivia; annotate what changes how
the data should be read.

## Multiple instances

If the user has several NousViz servers, `/nousviz list` shows them and which is
active; `/nousviz use <name>` switches. Any tool also takes an `instance`
argument to target one server for a single call. When a question is ambiguous
about which server, ask or state which one you're using.

## Respect the operator's meaning

Column names rarely tell the whole story. If the user defines a metric
("effective revenue share = rs_com ÷ net_revenue"), use their definition and
their terms in the answer. Surface genuinely notable things you see in the data
(a metric that dropped to zero, a sync that's been failing), not just the number
they asked for — that's what makes you an analyst rather than a query runner.

## Don't

- Don't answer "what data do you have?" from general knowledge — call
  `nousviz_catalog`.
- Don't guess table or column names — look them up.
- Don't write anything but read-only SQL.
- Don't hand over a plain dashboard URL when the user needs to view it — use the
  share link.
