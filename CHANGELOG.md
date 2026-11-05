# Changelog

## 0.1.0 — scaffold (unreleased)

- Five tools: `nousviz_query`, `nousviz_push`, `nousviz_create_dashboard`,
  `nousviz_create_alert`, `nousviz_dashboard_link`.
- `/nousviz` status command.
- Optional Mission Control telemetry (`post_tool_call` → inbound webhook,
  flushed every 25 events and at session end; metadata only, never
  tool arguments or results).
- Session-token auth against stock NousViz >= 1.0.6; password via the
  Hermes secret scope (`NOUSVIZ_PASSWORD`).
