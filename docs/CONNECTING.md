# Connect your Hermes agent to NousViz

Give your Hermes agent a self-hosted data platform: ask questions in natural
language, build dashboards and alerts by chat, and keep your data and your model
your own. This is the full setup, start to finish.

## What you need

1. **Hermes Agent** installed and working (`hermes` runs).
2. **A NousViz install, v1.0.6 or newer**, reachable from the machine Hermes runs
   on (e.g. `http://localhost:5173`, or a Tailscale/VPN address), **with data in
   it** — at least one plugin installed and synced. The agent reads your data; it
   can't analyze an empty install.
3. **A NousViz account for the agent** — email + password, **analyst** role
   (analyst can read data, run queries, and build dashboards/alerts/annotations).
   - Self-hosting with no email/SMTP? Create it directly with the bundled
     `scripts/create-agent-user.py` (prints a one-time password).
   - Otherwise, have your NousViz admin invite an account and give it analyst.

## 1. Install the plugin

Once it's in the Hermes catalog:
```bash
hermes plugins install nousviz
hermes plugins enable nousviz
```
(Before it's listed: clone `github.com/nousviz/nousviz-agentic-analytics`, symlink
the folder into `~/.hermes/plugins/nousviz`, then `hermes plugins enable nousviz`.)

## 2. Point it at your NousViz (`~/.hermes/config.yaml`)

```yaml
plugins:
  enabled: [nousviz]
  entries:
    nousviz:
      settings:
        base_url: "http://localhost:5173"      # your NousViz URL
        email: "hermes-agent@yourcompany.com"   # the agent's analyst account
```

## 3. Set the password (a secret — never in config)

In `~/.hermes/.env`:
```
NOUSVIZ_PASSWORD=the-agent-accounts-password
```

## 4. Load it

Config changes are read by the Hermes gateway at start, so:
```bash
hermes gateway restart
```

## 5. Verify

In a Hermes chat:
```
/nousviz
```
You should see **Connected to NousViz … as <your agent email>**, plus the tool
list. If it fails, re-check `base_url` (reachable from this machine?), the email,
and `NOUSVIZ_PASSWORD`.

## 6. First things to ask

- "What data do you have access to?" — it inspects your catalog and lists it.
- "What does the <X> dataset mean?" — it reads the operator's semantics.
- "Show me <metric> over the last 3 months and save it as a dashboard."
- "Alert me when <a Postgres metric> drops, but ignore tiny volumes."

## Connect more than one NousViz server (optional)

```yaml
settings:
  default_instance: "main"
  instances:
    main: { base_url: "http://localhost:5173", email: "agent@you.com" }
    other: { base_url: "http://127.0.0.1:5280", email: "agent@you.com" }
```
Passwords: `NOUSVIZ_PASSWORD` for the instance named `default`, otherwise
`NOUSVIZ_PASSWORD_<NAME>` (uppercase) — e.g. `NOUSVIZ_PASSWORD_OTHER`. Switch with
`/nousviz use <name>`; every tool also takes an optional `instance` argument.

## Get the most out of it

The agent is only as good as what your NousViz install tells it about the data.
For the best results, make sure each plugin's tables carry **semantics** — a
`datasets:` block in the plugin manifest with a `label`, a `description` (include
a short column glossary), and a `semantic_type` per table. The richer that is,
the better the agent understands your data instead of guessing.
