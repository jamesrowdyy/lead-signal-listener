"""Server-side messages (run log, token check, errors). UI strings live in static/index.html."""

MESSAGES = {
    "en": {
        "busy": "A run is already in progress",
        "skip_no_token": "[skip] {name} · {q}: Treg token not set",
        "skip_disabled": "[skip] {name} · {q}: Treg disabled for this run",
        "skip_budget": "[skip] {name} · {q}: run budget ${budget:.2f} reached",
        "ok": "[ok] {name} · {q}: fetched {got}, kept {kept}, new {new}",
        "error": "[error] {name} · {q}: {err}",
        "stop": "[stop] Invalid token or insufficient balance; remaining Treg calls cancelled",
        "done": "[done] fetched {fetched}, new leads {new}, Treg calls {calls}, cost ${cost:.4f}",
        "token_ok": "Token is valid",
        "token_bad": "Token check failed (HTTP {code})",
        "token_net": "Cannot reach treg.to: {reason}",
        "token_missing": "Token not set",
        "http_401": "Invalid or missing token",
        "http_402": "Insufficient balance or per-call cost cap exceeded",
        "http_429": "Upstream rate limit, try again later",
        "http_503": "Upstream unavailable, try again later",
        "http_other": "Request failed",
    },
    "zh": {
        "busy": "已有任务在运行",
        "skip_no_token": "[skip] {name} · {q}：未设置 Treg token",
        "skip_disabled": "[skip] {name} · {q}：本次运行已停用 Treg",
        "skip_budget": "[skip] {name} · {q}：已达单次运行预算 ${budget:.2f}",
        "ok": "[ok] {name} · {q}：抓取 {got}，保留 {kept}，新增 {new}",
        "error": "[error] {name} · {q}：{err}",
        "stop": "[stop] Token 无效或余额不足，后续 Treg 调用已取消",
        "done": "[done] 抓取 {fetched}，新增线索 {new}，Treg 调用 {calls} 次，花费 ${cost:.4f}",
        "token_ok": "Token 有效",
        "token_bad": "Token 校验失败（HTTP {code}）",
        "token_net": "无法连接 treg.to：{reason}",
        "token_missing": "未设置 token",
        "http_401": "Token 无效或缺失",
        "http_402": "余额不足或超过单次花费上限",
        "http_429": "上游限流，稍后再试",
        "http_503": "上游暂不可用，稍后再试",
        "http_other": "请求失败",
    },
}


def t(lang, key, **kw):
    table = MESSAGES.get(lang) or MESSAGES["en"]
    return table.get(key, MESSAGES["en"].get(key, key)).format(**kw)


def http_hint(lang, status):
    key = f"http_{status}" if f"http_{status}" in MESSAGES["en"] else "http_other"
    return t(lang, key)
