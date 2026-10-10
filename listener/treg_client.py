"""Minimal Treg (https://treg.to) HTTP client.

Only uses the public, documented surface:
  POST/GET https://treg.to/call/<endpoint-id>   with header X-Treg-Token
Cost is read from the authoritative response header X-Treg-Cost-Micro.
"""
import base64
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://treg.to"
USER_AGENT = "lead-signal-listener/0.1"


def token_org(token):
    """Identity tokens (JWT with aud=identity) must be sent with X-Treg-Org; read the org from the payload."""
    parts = (token or "").split(".")
    if len(parts) != 2 and len(parts) != 3:
        return None
    try:
        seg = parts[0] if len(parts) == 2 else parts[1]
        payload = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and payload.get("aud") == "identity":
        return payload.get("org") or None
    return None


def auth_headers(token, org=None):
    h = {"X-Treg-Token": token, "User-Agent": USER_AGENT}
    org = org or token_org(token)
    if org:
        h["X-Treg-Org"] = org
    return h


class TregError(Exception):
    def __init__(self, status, message, body=None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.detail = message
        self.body = body


class TregClient:
    def __init__(self, token, max_cost_usd=0.05, timeout=60, base_url=BASE_URL, org=None):
        if not token:
            raise ValueError("Treg token is required")
        self.token = token
        self.org = org
        self.max_cost_usd = max_cost_usd
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.spent_micro = 0
        self.calls = 0

    def call(self, endpoint_id, query=None, body=None, method=None, idempotency_seed=None):
        """Call a catalog endpoint. Returns (json_body, cost_micro)."""
        url = f"{self.base_url}/call/{endpoint_id}"
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        data = None
        headers = auth_headers(self.token, self.org)
        headers.update({"Accept": "application/json", "X-Treg-Route-Max-Cost": str(self.max_cost_usd)})
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_seed:
            # Same request within 24h is replayed for free instead of re-billed.
            headers["Idempotency-Key"] = hashlib.sha256(idempotency_seed.encode("utf-8")).hexdigest()[:48]
        method = method or ("POST" if body is not None else "GET")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                cost = int(resp.headers.get("X-Treg-Cost-Micro") or 0)
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            raise TregError(e.code, _error_message(e.code, raw), raw) from None
        except urllib.error.URLError as e:
            raise TregError(0, f"network error: {e.reason}") from None
        self.calls += 1
        self.spent_micro += cost
        try:
            return json.loads(raw), cost
        except json.JSONDecodeError:
            raise TregError(200, "response is not JSON", raw[:500]) from None


def _error_message(status, raw):
    detail = ""
    try:
        j = json.loads(raw)
        detail = j.get("detail") or j.get("error") or j.get("message") or ""
        if not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False)
    except (json.JSONDecodeError, AttributeError):
        detail = raw[:200]
    return detail.strip() or "request failed"
