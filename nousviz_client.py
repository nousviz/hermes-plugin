"""Minimal HTTP client for a NousViz >= 1.0.6 server.

Every endpoint used here was verified against nousviz-app v1.0.6 source:

- POST /api/auth/login            {email, password} -> {token, expires_at, user}
  (routes/auth.py; auth header on all later calls: X-Session-Token)
- POST /api/query                 {sql, db_engine?, database?, max_rows?}
                                  -> {columns, types, rows, row_count}   (routes/query.py)
- GET  /api/catalog/tables        -> {plugins: [{id, tables: [{name, plugin_id,
                                  table_type, row_count_estimate, columns}]}]}
- GET  /api/catalog/plugins/{id}/tables           one plugin (+ manifest_drift)
- GET  /api/catalog/plugins/{id}/tables/{table}   full column schema (routes/catalog.py,
                                  all datasets.read / viewer-level; Postgres tables only)
- GET  /api/plugins/{id}          manifest + semantics (description, long_description,
                                  datasets[label/description/grain/semantic_type]);
                                  plugins.read / viewer-level (routes/plugins.py)
- GET  /api/insights/             {insights, total} aggregated insight cards;
                                  dashboards.read (routes/insights.py)
- POST /api/dashboards/           {name, description?, widgets, layout?, sources}
                                  (routes/dashboards.py, needs dashboards.write)
- PUT  /api/dashboards/{slug}     same body, full replace
- POST /api/alerts                AlertCreate fields (routes/alerts.py, needs alerts.write)
- GET  /api/alerts                list alerts (alerts.read; plugin_id/enabled_only filter)
- PUT  /api/alerts/{id}           AlertUpdate (alerts.write) — edit threshold/min_baseline/...
- DELETE /api/alerts/{id}         delete an alert (alerts.write)
- POST /api/alerts/{id}/test      dry-run: "Would fire on N of M rows" (alerts.write)
- POST /api/annotations           AnnotationCreate (routes/annotations.py, needs
                                  annotations.write; required title + date_start)
- GET  /api/annotations           list annotations (annotations.read; rich filters)
- POST /api/webhooks/in/{slug}    raw JSON body; optional HMAC-SHA256 of the body
                                  in the x-webhook-signature header
                                  (plugins/utilities/webhooks/api/routes.py)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
import urllib.parse
from typing import Any, Optional

import requests


def _qs(params: dict) -> str:
    """Build a ``?a=b&c=d`` query string from non-None params (url-encoded)."""
    items = {k: v for k, v in params.items() if v is not None}
    return ("?" + urllib.parse.urlencode(items)) if items else ""

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 20  # seconds


class NousVizError(Exception):
    """Raised for auth/config problems and non-2xx API responses."""


class NousVizClient:
    """Session-token client. Logs in lazily, re-logs-in once on a 401."""

    def __init__(self, base_url: str, email: str, password: str):
        if not base_url:
            raise NousVizError("NousViz base_url is not configured")
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self._token: Optional[str] = None
        self._lock = threading.Lock()

    # ── auth ──────────────────────────────────────────────────────────

    def _login(self) -> str:
        resp = requests.post(
            f"{self.base_url}/api/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            raise NousVizError(f"NousViz login failed ({resp.status_code}): {resp.text[:300]}")
        token = resp.json().get("token")
        if not token:
            raise NousVizError("NousViz login response had no token")
        return token

    def _request(self, method: str, path: str, *, json_body: Any = None,
                 _retry: bool = True) -> Any:
        with self._lock:
            if self._token is None:
                self._token = self._login()
            token = self._token
        resp = requests.request(
            method, f"{self.base_url}{path}",
            json=json_body,
            headers={"X-Session-Token": token},
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code == 401 and _retry:
            with self._lock:
                self._token = None
            return self._request(method, path, json_body=json_body, _retry=False)
        if resp.status_code >= 400:
            raise NousVizError(f"{method} {path} -> {resp.status_code}: {resp.text[:500]}")
        try:
            return resp.json()
        except ValueError:
            return {"raw": resp.text}

    def check_connection(self) -> dict:
        """Login (or reuse the session) and report who we are."""
        with self._lock:
            self._token = self._login()
        return {"ok": True, "base_url": self.base_url, "email": self.email}

    # ── data ──────────────────────────────────────────────────────────

    def query(self, sql: str, db_engine: Optional[str] = None,
              database: Optional[str] = None, max_rows: Optional[int] = None) -> dict:
        body: dict[str, Any] = {"sql": sql}
        if db_engine:
            body["db_engine"] = db_engine
        if database:
            body["database"] = database
        if max_rows:
            body["max_rows"] = max_rows
        return self._request("POST", "/api/query", json_body=body)

    # ── catalog ───────────────────────────────────────────────────────

    def catalog(self, plugin_id: Optional[str] = None,
                table: Optional[str] = None) -> dict:
        """Read the NousViz data catalog (Postgres plugin tables).

        Three levels of detail, matching the three catalog routes
        (all require only viewer-level ``datasets.read``):

        - no args          -> GET /api/catalog/tables
                              every plugin the caller can access, grouped.
        - plugin_id        -> GET /api/catalog/plugins/{plugin_id}/tables
                              one plugin's tables (+ manifest_drift).
        - plugin_id+table  -> GET /api/catalog/plugins/{plugin_id}/tables/{table}
                              full column schema for one table.

        The server scopes results to plugins the account is granted
        (per-plugin ACL), so this never returns more than this agent may read.
        """
        if plugin_id and table:
            return self._request(
                "GET", f"/api/catalog/plugins/{plugin_id}/tables/{table}")
        if plugin_id:
            return self._request(
                "GET", f"/api/catalog/plugins/{plugin_id}/tables")
        return self._request("GET", "/api/catalog/tables")

    def plugin_detail(self, plugin_id: str) -> dict:
        """GET /api/plugins/{plugin_id} (needs viewer-level ``plugins.read``).

        Returns the plugin manifest, including its author-written semantics:
        ``description``, ``long_description``, and a ``datasets`` list whose
        entries carry ``name, label, description, grain, semantic_type``. Used
        to layer meaning onto the structural catalog. Does NOT expose connection
        secrets — those live behind ``plugins.configure`` (admin), which the
        agent's analyst role lacks.
        """
        return self._request("GET", f"/api/plugins/{plugin_id}")

    def insights(self, limit: int = 20) -> dict:
        """GET /api/insights/ (needs ``dashboards.read``) -> {insights, total}.

        Aggregates Tier-1 (insights.yaml SQL cards) + Tier-2 (plugin /insights
        endpoints) across installed plugins, sorted by severity.
        """
        return self._request("GET", f"/api/insights/?limit={int(limit)}")

    def push(self, slug: str, payload: Any, secret: Optional[str] = None) -> dict:
        """Send JSON to an inbound webhook endpoint (no session token needed)."""
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["x-webhook-signature"] = hmac.new(
                secret.encode(), body, hashlib.sha256).hexdigest()
        resp = requests.post(f"{self.base_url}/api/webhooks/in/{slug}",
                             data=body, headers=headers, timeout=DEFAULT_TIMEOUT)
        if resp.status_code >= 400:
            raise NousVizError(f"webhook push -> {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    # ── dashboards ────────────────────────────────────────────────────

    def create_dashboard(self, name: str, description: Optional[str] = None,
                         widgets: Optional[list] = None, layout: Optional[dict] = None,
                         sources: Optional[list] = None) -> dict:
        return self._request("POST", "/api/dashboards/", json_body={
            "name": name, "description": description,
            "widgets": widgets or [], "layout": layout, "sources": sources or [],
        })

    def update_dashboard(self, slug: str, name: str, description: Optional[str] = None,
                         widgets: Optional[list] = None, layout: Optional[dict] = None,
                         sources: Optional[list] = None) -> dict:
        return self._request("PUT", f"/api/dashboards/{slug}", json_body={
            "name": name, "description": description,
            "widgets": widgets or [], "layout": layout, "sources": sources or [],
        })

    def dashboard_url(self, slug: str) -> str:
        return f"{self.base_url}/dashboards/{slug}"

    def create_share(self, slug: str, title: Optional[str] = None,
                     password: Optional[str] = None, expires_hours: int = 168) -> dict:
        """Create a public share link for a dashboard. Returns {share_id, url, expires_at}.

        The public URL is {base_url}/shared/{share_id} — on a production install the
        API and UI share one origin, so this opens directly. (On split dev ports the
        UI origin differs; configure web_base_url to override.)
        """
        resp = self._request("POST", "/api/shares", json_body={
            "page_path": f"/dashboards/{slug}",
            "resource_type": "dashboard",
            "title": title,
            "password": password,
            "expires_hours": expires_hours,
        })
        share_id = resp.get("share_id")
        resp["url"] = f"{self.base_url}/shared/{share_id}" if share_id else None
        return resp

    # ── alerts ────────────────────────────────────────────────────────

    def create_alert(self, fields: dict) -> dict:
        """Pass-through to POST /api/alerts; the server validates AlertCreate fields."""
        return self._request("POST", "/api/alerts", json_body=fields)

    def list_alerts(self, plugin_id: Optional[str] = None,
                    enabled_only: bool = False) -> dict:
        """GET /api/alerts (alerts.read). Optional plugin_id / enabled_only filter."""
        return self._request("GET", "/api/alerts" + _qs(
            {"plugin_id": plugin_id, "enabled_only": "true" if enabled_only else None}))

    def update_alert(self, alert_id: str, fields: dict) -> dict:
        """PUT /api/alerts/{id} (alerts.write); server validates AlertUpdate fields."""
        return self._request("PUT", f"/api/alerts/{alert_id}", json_body=fields)

    def delete_alert(self, alert_id: str) -> dict:
        """DELETE /api/alerts/{id} (alerts.write)."""
        return self._request("DELETE", f"/api/alerts/{alert_id}")

    def test_alert(self, alert_id: str) -> dict:
        """POST /api/alerts/{id}/test (alerts.write) — dry-run; no notify/record.
        Returns a message like 'Would fire on N of M rows'."""
        return self._request("POST", f"/api/alerts/{alert_id}/test", json_body={})

    # ── annotations ───────────────────────────────────────────────────

    def list_annotations(self, **filters: Any) -> dict:
        """GET /api/annotations (annotations.read). Filters: plugin_id, dataset,
        category, date_from, date_to, semantic_score, pinned, include_archived,
        limit (<=1000)."""
        return self._request("GET", "/api/annotations" + _qs(filters))

    # ── annotations ───────────────────────────────────────────────────

    def create_annotation(self, fields: dict) -> dict:
        """Pass-through to POST /api/annotations (needs annotations.write).

        Verified AnnotationCreate (routes/annotations.py): required ``title`` and
        ``date_start``; optional ``description, category, severity, color,
        plugin_id, dataset, date_end, scope_filters, tags, pinned`` and the
        semantic fields ``semantic_meaning, impact_scope, semantic_score
        (useful|neutral|useless), semantic_note``.
        """
        return self._request("POST", "/api/annotations", json_body=fields)
