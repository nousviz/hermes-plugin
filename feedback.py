"""Feedback delivery — route user/agent feedback to the plugin builder.

Opt-in. Configure under ``plugins.entries.nousviz.settings.feedback``::

    feedback:
      slack_webhook_secret: SLACK_FEEDBACK_WEBHOOK   # secret-scope key holding
                                                     # the Slack incoming-webhook URL
      resend:
        api_key_secret: RESEND_API_KEY               # secret-scope key for the Resend key
        from: "NousViz Feedback <feedback@your-verified-domain>"
        to: "you@example.com"

Secrets (the Slack URL — it embeds a token — and the Resend API key) come from
the Hermes secret scope, never plugin config. Non-secret fields (from/to) live
in config. Any configured channel is delivered to; the rest are skipped.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 15

# ── Builder feedback destination ──────────────────────────────────────────────
# Feedback from EVERY install is routed here, to the plugin builder. Paste ONE
# URL before publishing — either:
#   * a Slack incoming-webhook URL (quickest: feedback lands in your channel), or
#   * a collector you host (recommended: a tiny endpoint that forwards to Slack
#     AND emails via Resend, keeping those credentials server-side — never ship
#     a Resend API key in this public repo).
# The posted JSON carries a `text` field (so a Slack webhook renders it directly)
# plus structured fields (so a collector can parse them). Leaving this empty
# disables builder-bound feedback. A shipped webhook URL is public — treat it as
# spammable-but-revocable, or prefer a collector URL with a token.
BUILDER_FEEDBACK_URL = "https://nousviz-feedback.johnwrightgaming.workers.dev"   # collector → Slack + Resend
BUILDER_FEEDBACK_TOKEN = "Tji82fjiehbiwd7R@389bnw#2225"   # sent as the X-Feedback-Token header to the collector
SOURCE = "nousviz-agentic-analytics"   # so your collector knows which plugin sent it


class FeedbackError(Exception):
    """Raised when feedback can't be delivered (unconfigured or all channels failed)."""


class FeedbackSender:
    def __init__(self, get_config: Callable[..., Any],
                 get_secret: Callable[[str], Optional[str]]):
        self._get_config = get_config
        self._get_secret = get_secret

    def _config(self) -> dict:
        fb = self._get_config("feedback")
        return fb if isinstance(fb, dict) else {}

    def is_configured(self) -> bool:
        if BUILDER_FEEDBACK_URL:
            return True
        fb = self._config()
        return bool(fb.get("slack_webhook_secret") or (fb.get("resend") or {}).get("api_key_secret"))

    @staticmethod
    def _subject(p: dict) -> str:
        bits = [p.get("rating") or "feedback", "on", p.get("subject") or "nousviz"]
        if p.get("plugin_id"):
            bits.append(f"({p['plugin_id']})")
        return "[NousViz feedback] " + " ".join(bits)

    @staticmethod
    def _text(p: dict) -> str:
        icon = {"up": "👍", "down": "👎"}.get((p.get("rating") or "").lower(), "💬")
        lines = [f"{icon} Feedback [{p.get('subject') or 'general'}]"]
        if p.get("plugin_id"):
            lines[0] += f" · plugin: {p['plugin_id']}"
        if p.get("note"):
            lines.append(f"Note: {p['note']}")
        if p.get("suggested_fix"):
            lines.append(f"Suggested fix: {p['suggested_fix']}")
        if p.get("context"):
            lines.append(f"Context: {p['context']}")
        return "\n".join(lines)

    def send(self, payload: dict) -> dict:
        fb = self._config()
        if not self.is_configured():
            raise FeedbackError(
                "Feedback delivery isn't configured. Either set BUILDER_FEEDBACK_URL in "
                "feedback.py (ships to the plugin builder from every install), or add a "
                "`feedback` block under plugins.entries.nousviz.settings "
                "(slack_webhook_secret and/or resend.{api_key_secret,from,to}) with the secrets.")
        text = self._text(payload)
        results: dict[str, str] = {}

        # Builder destination (baked into the plugin) — reaches the plugin builder
        # from every install. Payload has `text` (Slack-renderable) + structured
        # fields (collector-parseable).
        if BUILDER_FEEDBACK_URL:
            body = {"text": text, "source": SOURCE,
                    **{k: payload.get(k) for k in
                       ("rating", "subject", "note", "plugin_id", "suggested_fix", "context")
                       if payload.get(k) is not None}}
            headers = {"X-Feedback-Token": BUILDER_FEEDBACK_TOKEN} if BUILDER_FEEDBACK_TOKEN else None
            try:
                r = requests.post(BUILDER_FEEDBACK_URL, json=body, headers=headers, timeout=_TIMEOUT)
                results["builder"] = "ok" if r.status_code < 300 else f"error {r.status_code}"
            except Exception as e:  # pragma: no cover - network
                results["builder"] = f"error {e}"

        slack_secret = fb.get("slack_webhook_secret")
        if slack_secret:
            url = self._get_secret(slack_secret)
            if not url:
                results["slack"] = f"skipped — secret '{slack_secret}' is empty"
            else:
                try:
                    r = requests.post(url, json={"text": text}, timeout=_TIMEOUT)
                    results["slack"] = "ok" if r.status_code < 300 else f"error {r.status_code}"
                except Exception as e:  # pragma: no cover - network
                    results["slack"] = f"error {e}"

        resend = fb.get("resend") or {}
        if resend.get("api_key_secret"):
            key = self._get_secret(resend["api_key_secret"])
            if not key:
                results["resend"] = f"skipped — secret '{resend['api_key_secret']}' is empty"
            elif not (resend.get("from") and resend.get("to")):
                results["resend"] = "skipped — resend.from and resend.to are required"
            else:
                try:
                    r = requests.post(
                        "https://api.resend.com/emails",
                        headers={"Authorization": f"Bearer {key}"},
                        json={"from": resend["from"], "to": resend["to"],
                              "subject": self._subject(payload), "text": text},
                        timeout=_TIMEOUT)
                    results["resend"] = ("ok" if r.status_code < 300
                                         else f"error {r.status_code}: {r.text[:200]}")
                except Exception as e:  # pragma: no cover - network
                    results["resend"] = f"error {e}"

        if not any(v == "ok" for v in results.values()):
            raise FeedbackError(f"Feedback not delivered: {results}")
        return {"delivered": results}
