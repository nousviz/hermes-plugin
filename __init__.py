"""nousviz — give Hermes a data platform.

Connects Hermes to one or more self-hosted NousViz (>= 1.0.6) installs:

- ``nousviz_catalog``          discover plugins/tables/columns + operator semantics
- ``nousviz_insights``         read the operator's curated metrics/findings
- ``nousviz_query``            SQL over the platform's data (read-only)
- ``nousviz_push``             land collected data via inbound webhooks
- ``nousviz_create_dashboard`` turn an exploration into a persistent dashboard
- ``nousviz_create_alert``     get notified (and called back) when numbers move
- ``nousviz_list/test/update/delete_alert`` manage alerts by conversation (dry-run,
                               tune min_baseline/cooldown to kill noise, edit, remove)
- ``nousviz_create_annotation`` record durable notes/insights onto the data timeline
- ``nousviz_list_annotations`` read prior notes/insights back (the learning loop)
- ``nousviz_feedback``         route user/agent feedback to the plugin builder
                               (Slack / Resend email)
- ``nousviz_dashboard_link``   share a dashboard URL
- ``nousviz_share_dashboard``  public share link a human can open
- ``/nousviz``                 connection status + instance switching
- ``nousviz:analyst`` skill    coaches catalog-first data analysis
- optional telemetry hooks     stream the agent's own tool activity into a
                               NousViz "Mission Control" dashboard

Config (``plugins.entries.nousviz.settings``). Two forms, both supported:

- Single server (legacy): ``base_url`` + ``email``; password in the Hermes
  secret scope as ``NOUSVIZ_PASSWORD``. Treated as an instance named ``default``.
- Multiple servers: an ``instances`` map, ``{<name>: {base_url, email,
  password_secret?}}``, plus optional ``default_instance``. Each instance's
  password comes from the secret scope: ``password_secret`` if set, else
  ``NOUSVIZ_PASSWORD`` for ``default`` and ``NOUSVIZ_PASSWORD_<NAME>`` otherwise.

Passwords never live in plugin config. The active instance is remembered
per Hermes profile and switched with ``/nousviz use <name>``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .nousviz_client import NousVizClient, NousVizError
from . import tools as nv_tools
from .telemetry import Telemetry
from .feedback import FeedbackSender

logger = logging.getLogger(__name__)

_clients: dict[str, NousVizClient] = {}
_ctx = None

# Bundled "NousViz Analyst" skill. Registered as `nousviz:analyst` (namespace =
# manifest name). Its frontmatter `description` is the trigger the model sees in
# <available_skills>, so we parse it from the file rather than duplicate it here.
_SKILL_MD = Path(__file__).resolve().parent / "skills" / "analyst" / "SKILL.md"
_ANALYST_FALLBACK_DESC = (
    "Work with the user's data in NousViz: discover tables with nousviz_catalog, "
    "answer questions with read-only SQL, and build dashboards and alerts. Use for "
    "any 'what data do you have' or data-analysis request.")


def _parse_frontmatter(path: Path) -> dict:
    """Minimal YAML-frontmatter reader: top-level single-line ``key: value``
    pairs between the opening and closing ``---``. Enough for name/description/
    version; nested blocks (e.g. metadata) are ignored."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    fm: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if not line or line[0] in " \t#" or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def _secret(name: str) -> str | None:
    from agent.secret_scope import get_secret
    try:
        return get_secret(name)
    except Exception:  # pragma: no cover - secret scope absent in some contexts
        return None


def _secret_key_for(instance: str) -> str:
    """Default secret-scope key for an instance: ``NOUSVIZ_PASSWORD`` for the
    ``default`` instance, ``NOUSVIZ_PASSWORD_<NAME>`` for any other."""
    if instance == "default":
        return "NOUSVIZ_PASSWORD"
    slug = re.sub(r"[^A-Z0-9]+", "_", instance.upper()).strip("_")
    return f"NOUSVIZ_PASSWORD_{slug}"


def _instances_config() -> dict[str, dict]:
    """Resolve configured instances to ``{name: {base_url, email, password_secret?}}``.

    Merges the legacy flat ``base_url``/``email`` (as an instance named
    ``default``) with an optional ``instances`` map.
    """
    if _ctx is None:
        return {}
    out: dict[str, dict] = {}
    base_url = _ctx.get_config("base_url")
    email = _ctx.get_config("email")
    if base_url and email:
        out["default"] = {"base_url": base_url, "email": email}
    instances = _ctx.get_config("instances") or {}
    if isinstance(instances, dict):
        for name, spec in instances.items():
            if isinstance(spec, dict) and spec.get("base_url") and spec.get("email"):
                out[str(name)] = {
                    "base_url": spec["base_url"],
                    "email": spec["email"],
                    "password_secret": spec.get("password_secret"),
                }
    return out


def _resolve_instance(explicit: str | None = None) -> str:
    """Pick the instance name to use: explicit arg, else the remembered active
    one, else config ``default_instance``, else ``default``, else the first."""
    instances = _instances_config()
    if not instances:
        raise NousVizError(
            "NousViz is not configured. Set plugins.entries.nousviz.settings.base_url "
            "and .email (single server), or a settings.instances map (multiple "
            "servers), in config.yaml, and provide the matching password secret.")
    if explicit:
        if explicit not in instances:
            raise NousVizError(
                f"Unknown NousViz instance '{explicit}'. Configured: "
                f"{', '.join(sorted(instances))}.")
        return explicit
    active = _ctx.state.get("active_instance") if _ctx else None
    if active in instances:
        return active
    cfg_default = _ctx.get_config("default_instance") if _ctx else None
    if cfg_default in instances:
        return cfg_default
    if "default" in instances:
        return "default"
    return sorted(instances)[0]


def _get_client(instance: str | None = None) -> NousVizClient:
    """Build (once per instance) a client from config + secret scope."""
    name = _resolve_instance(instance)
    if name not in _clients:
        spec = _instances_config()[name]
        secret_key = spec.get("password_secret") or _secret_key_for(name)
        password = _secret(secret_key)
        if not password:
            raise NousVizError(
                f"No password for NousViz instance '{name}'. Provide the "
                f"'{secret_key}' secret in the Hermes secret scope.")
        _clients[name] = NousVizClient(
            base_url=spec["base_url"], email=spec["email"], password=password)
    return _clients[name]


def _set_active(name: str) -> None:
    instances = _instances_config()
    if name not in instances:
        raise NousVizError(
            f"Unknown NousViz instance '{name}'. Configured: "
            f"{', '.join(sorted(instances))}.")
    if _ctx is not None:
        _ctx.state.set("active_instance", name)


def _instances_listing() -> str:
    try:
        instances = _instances_config()
    except NousVizError as e:
        return f"❌ {e}"
    if not instances:
        return ("No NousViz instances configured. Set base_url + email, or an "
                "instances map, under plugins.entries.nousviz.settings.")
    active = None
    try:
        active = _resolve_instance()
    except NousVizError:
        pass
    rows = []
    for name in sorted(instances):
        mark = "→" if name == active else "  "
        spec = instances[name]
        rows.append(f"{mark} {name}: {spec['base_url']} ({spec['email']})")
    return ("NousViz instances:\n" + "\n".join(rows) +
            "\n(switch with /nousviz use <name>)")


def _meter(pct: int, cells: int = 10) -> str:
    """A fixed-width ASCII bar for a 0–100 percentage (text-only, no color — it
    renders the same in the CLI, Telegram and ChatGPT surfaces)."""
    filled = max(0, min(cells, round(pct * cells / 100)))
    return "█" * filled + "░" * (cells - filled)


def _coach() -> str:
    """Score how well-documented the connected data is (the agent is only as good
    as the semantics it can read) and point at the biggest gaps to fix."""
    try:
        client = _get_client()
        catalog = client.catalog()
    except NousVizError as e:
        return f"❌ {e}"
    plugins = catalog.get("plugins", []) if isinstance(catalog, dict) else []
    if not plugins:
        return ("No data is visible to the agent yet. Install and sync at least one NousViz "
                "plugin, then run /nousviz coach again. The agent reads your plugins' tables "
                "and the semantics you give them.")
    total = documented = 0
    rows, gaps = [], []
    for p in plugins:
        pid = p.get("id")
        tables = [t.get("name") for t in p.get("tables", []) if t.get("name")]
        if not tables:
            continue
        described: set[str] = set()
        try:
            detail = client.plugin_detail(pid)
            for ds in (detail.get("datasets") or []):
                if isinstance(ds, dict) and ds.get("name") and ds.get("description"):
                    described.add(ds["name"])
        except NousVizError:
            pass
        n_doc = len(described & set(tables))
        total += len(tables)
        documented += n_doc
        p_pct = round(100 * n_doc / len(tables))
        rows.append(f"  {_meter(p_pct)} {p_pct:>3}%  {pid}: {n_doc}/{len(tables)} tables documented")
        for t in tables:
            if t not in described:
                gaps.append(f"{pid}.{t}")
    pct = round(100 * documented / total) if total else 0
    out = [f"📊 Semantic coverage  {_meter(pct)} {pct:>3}%  "
           f"({documented}/{total} tables documented)", *rows]
    if gaps:
        out.append("Biggest wins — add a `datasets:` entry (label + description with a "
                   "column glossary + semantic_type) for:")
        out.append("  " + ", ".join(gaps[:8]) + (" …" if len(gaps) > 8 else ""))
        out.append("The more you document, the better the agent understands your data instead "
                   "of guessing from column names.")
    else:
        out.append("Every visible table is documented — the agent is working from your "
                   "definitions. 🎯")
    return "\n".join(out)


def _status_command(raw_args: str) -> str:
    """/nousviz — status; 'list' — instances; 'use <name>' — switch;
    'mission-control' — provision the agent-activity dashboard."""
    arg = (raw_args or "").strip()
    low = arg.lower()

    if low == "mission-control":
        try:
            from . import mission_control
            result = mission_control.provision(_get_client())
            return (f"📊 Mission Control {result['provisioned']}: {result['url']}\n"
                    f"It charts this agent's telemetry (tool calls, errors, sessions). "
                    f"Telemetry streams when telemetry_webhook_slug is configured.")
        except NousVizError as e:
            return f"❌ Mission Control provisioning failed: {e}"

    if low == "coach":
        return _coach()

    if low in ("list", "instances"):
        return _instances_listing()

    if low == "use" or low.startswith("use "):
        parts = arg.split(None, 1)
        name = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            return "Usage: /nousviz use <instance-name>  (see /nousviz list)"
        try:
            _set_active(name)
            info = _get_client().check_connection()
            return (f"✅ Active NousViz instance is now '{name}' — "
                    f"{info['base_url']} as {info['email']}.")
        except NousVizError as e:
            return f"❌ {e}"

    try:
        instances = _instances_config()
        active = _resolve_instance()
        info = _get_client().check_connection()
        tool_names = ", ".join(name for name, *_ in nv_tools.TOOLS)
        lines = [f"✅ Connected to NousViz instance '{active}' at "
                 f"{info['base_url']} as {info['email']}."]
        if len(instances) > 1:
            others = ", ".join(n for n in sorted(instances) if n != active)
            lines.append(f"Other instances: {others}  (switch with /nousviz use <name>)")
        lines.append(f"Tools: {tool_names}.")
        lines.append("Commands: /nousviz list · /nousviz use <name> · "
                     "/nousviz mission-control.")
        lines.append(
            "New here? Try \"What data do you have access to?\" to explore, then ask a "
            "question or say \"build me a dashboard of …\". Tip: the richer your plugins' "
            "dataset labels and descriptions, the better the answers — see /nousviz coach.")
        return "\n".join(lines)
    except NousVizError as e:
        return f"❌ NousViz connection failed: {e}"


def register(ctx) -> None:
    """Called once by the Hermes plugin loader."""
    global _ctx
    _ctx = ctx
    nv_tools.set_client_factory(_get_client)
    # Feedback delivery (Slack / Resend) — no-op tool until a `feedback` block
    # is configured; the handler reports that clearly if called unconfigured.
    nv_tools.set_feedback_sender(FeedbackSender(ctx.get_config, _secret).send)

    for name, schema, handler, emoji in nv_tools.TOOLS:
        ctx.register_tool(name=name, toolset="nousviz", schema=schema,
                          handler=handler, emoji=emoji)

    ctx.register_command(
        name="nousviz", handler=_status_command,
        args_hint="[list | use <name> | coach | mission-control]",
        description="NousViz connection status; 'list'/'use <name>' switch between "
                    "instances; 'coach' scores your data's semantic coverage and names the "
                    "gaps to document; 'mission-control' provisions the agent-activity dashboard")

    # Bundled "NousViz Analyst" skill -> nousviz:analyst. Coaches catalog-first
    # data work so plain-language data questions don't fall through to generic
    # handling. Best-effort: a missing/garbled file must not break the plugin.
    try:
        fm = _parse_frontmatter(_SKILL_MD)
        ctx.register_skill(
            name="analyst", path=_SKILL_MD,
            description=fm.get("description") or _ANALYST_FALLBACK_DESC,
            frontmatter=fm)
    except Exception as exc:  # pragma: no cover - defensive, mirrors loader
        logger.warning("nousviz: analyst skill not registered: %s", exc)

    # Telemetry no-ops until telemetry_webhook_slug is configured (read live).
    telemetry = Telemetry(_get_client, ctx.get_config)
    ctx.register_hook("post_tool_call", telemetry.post_tool_call)
    ctx.register_hook("on_session_end", telemetry.on_session_end)
