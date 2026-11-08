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
                "Feedback delivery isn't configured. Add a `feedback` block under "
                "plugins.entries.nousviz.settings with slack_webhook_secret and/or "
                "resend.{api_key_secret,from,to}, and provide the secrets.")
        text = self._text(payload)
        results: dict[str, str] = {}

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
