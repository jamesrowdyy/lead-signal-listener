"""Signal sources. Each fetcher returns a list of normalized signal dicts:

  source, kind, external_id, url, title, text, author, author_url,
  community, created_utc, engagement, query

kind: "pain" (someone talking about a problem) | "hiring" | "funding"
"""
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .treg_client import TregClient

HN_API = "https://hn.algolia.com/api/v1/search_by_date"

# Catalog endpoint ids (verified against https://treg.to/catalog/endpoints/<id>).
ENDPOINTS = {
    "reddit": "scrapecreators.reddit.search.posts",
    "x": "treg.x.search.posts",
    "linkedin_posts": "anyapi.linkedin.search.posts",
    "linkedin_jobs": "anyapi.linkedin.search.jobs",
    "funding": "getleadsio.companies.funding.feed",
}

TAG_RE = re.compile(r"<[^>]+>")


def clean_text(s, limit=4000):
    if not s:
        return ""
    s = html.unescape(TAG_RE.sub(" ", str(s)))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def pick(d, *paths, default=None):
    """Return the first non-empty value among dotted paths, e.g. pick(d, "user.screen_name", "username")."""
    for p in paths:
        cur = d
        for part in p.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                cur = None
                break
        if cur not in (None, "", [], {}):
            return cur
    return default


def to_epoch(v):
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return int(v / 1000) if v > 10_000_000_000 else int(v)
    s = str(v).strip()
    if s.isdigit():
        return to_epoch(int(s))
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except ValueError:
            continue
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def unwrap(resp):
    """Treg responses come either raw from the provider or wrapped as {output, raw, _treg}."""
    if isinstance(resp, dict) and "output" in resp:
        out = resp["output"]
        if isinstance(out, dict) and isinstance(out.get("data"), (dict, list)):
            return out["data"]
        return out
    return resp


# ---------- parsers (pure functions, unit-tested offline) ----------

def parse_reddit(resp, query):
    data = unwrap(resp)
    posts = data.get("posts") if isinstance(data, dict) else data
    out = []
    for p in posts or []:
        if not isinstance(p, dict):
            continue
        pid = p.get("id") or p.get("name")
        if not pid:
            continue
        url = p.get("url") or ""
        if p.get("permalink"):
            url = "https://www.reddit.com" + p["permalink"]
        author = p.get("author") or ""
        out.append({
            "source": "reddit", "kind": "pain", "external_id": str(pid), "url": url,
            "title": clean_text(p.get("title"), 300), "text": clean_text(p.get("selftext")),
            "author": author, "author_url": f"https://www.reddit.com/user/{author}" if author else "",
            "community": "r/" + p["subreddit"] if p.get("subreddit") else "",
            "created_utc": to_epoch(p.get("created_utc") or p.get("created")),
            "engagement": int(p.get("score") or 0) + int(p.get("num_comments") or 0),
            "query": query,
        })
    return out


def parse_x(resp, query):
    data = unwrap(resp)
    posts = data.get("posts") if isinstance(data, dict) else data
    out = []
    for p in posts or []:
        if not isinstance(p, dict):
            continue
        pid = pick(p, "id_str", "rest_id", "tweet_id", "id", "legacy.id_str")
        text = pick(p, "full_text", "text", "content", "legacy.full_text", "note_tweet.text")
        if not pid or not text:
            continue
        handle = pick(p, "authorUsername", "author.username", "author.screen_name", "user.screen_name", "user.username",
                      "username", "screen_name", "author_handle", "core.user_results.result.legacy.screen_name",
                      default="")
        if isinstance(handle, dict):
            handle = ""
        url = pick(p, "url", "tweet_url", "link", default="")
        if not url or "/status/" not in str(url) or ("/i/web/" in str(url) and handle):
            url = f"https://x.com/{handle or 'i'}/status/{pid}"
        likes = pick(p, "likeCount", "favorite_count", "like_count", "likes", "public_metrics.like_count", "legacy.favorite_count", default=0)
        replies = pick(p, "replyCount", "reply_count", "replies", "public_metrics.reply_count", "legacy.reply_count", default=0)
        out.append({
            "source": "x", "kind": "pain", "external_id": str(pid), "url": url,
            "title": "", "text": clean_text(text),
            "author": handle, "author_url": f"https://x.com/{handle}" if handle else "",
            "community": "",
            "created_utc": to_epoch(pick(p, "createdUtc", "created_at", "createdAt", "legacy.created_at", "date")),
            "engagement": _int(likes) + _int(replies), "query": query,
        })
    return out


def parse_linkedin_posts(resp, query):
    data = unwrap(resp)
    posts = data.get("posts") if isinstance(data, dict) else data
    out = []
    for p in posts or []:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        out.append({
            "source": "linkedin", "kind": "pain", "external_id": str(p["id"]), "url": p.get("url", ""),
            "title": "", "text": clean_text(p.get("text")),
            "author": p.get("authorName", ""), "author_url": p.get("authorUrl", ""), "community": "",
            "created_utc": to_epoch(p.get("createdUtc")),
            "engagement": _int(p.get("reactionCount")) + _int(p.get("commentCount")), "query": query,
        })
    return out


def parse_linkedin_jobs(resp, query):
    data = unwrap(resp)
    items = data.get("items") if isinstance(data, dict) else data
    out = []
    for j in items or []:
        if not isinstance(j, dict) or not j.get("id"):
            continue
        company = j.get("company", "")
        out.append({
            "source": "linkedin_jobs", "kind": "hiring", "external_id": str(j["id"]), "url": j.get("url", ""),
            "title": clean_text(j.get("title"), 300),
            "text": clean_text(f"{company} is hiring: {j.get('title', '')} ({j.get('location', '')})"),
            "author": company, "author_url": j.get("companyUrl", ""), "community": j.get("location", ""),
            "created_utc": to_epoch(j.get("createdUtc")), "engagement": 0, "query": query,
        })
    return out


def parse_hn(resp, query):
    out = []
    for h in (resp or {}).get("hits", []):
        oid = h.get("objectID")
        if not oid:
            continue
        is_comment = bool(h.get("comment_text"))
        # Comments carry their thread's title; keep it as context so rows don't look like duplicates.
        title = "" if is_comment else (h.get("title") or "")
        text = h.get("comment_text") or h.get("story_text") or ""
        if not (title or text):
            continue
        thread = clean_text(h.get("story_title"), 120)
        out.append({
            "source": "hn", "kind": "pain", "external_id": str(oid),
            "url": f"https://news.ycombinator.com/item?id={oid}",
            "title": clean_text(title, 300), "text": clean_text(text),
            "author": h.get("author", ""),
            "author_url": f"https://news.ycombinator.com/user?id={h.get('author', '')}" if h.get("author") else "",
            "community": f"HN comment · {thread}" if is_comment and thread else "Hacker News", "created_utc": to_epoch(h.get("created_at_i")),
            "engagement": _int(h.get("points")) + _int(h.get("num_comments")), "query": query,
        })
    return out


def parse_funding(resp, query=""):
    data = resp.get("data") if isinstance(resp, dict) else resp
    out = []
    for f in data or []:
        if not isinstance(f, dict) or not f.get("company_name"):
            continue
        key = f"{f['company_name']}|{f.get('round', '')}|{f.get('announced_date', '')}"
        amount = f.get("amount")
        amount_s = f"{f.get('currency', 'USD')} {amount:,.0f}" if isinstance(amount, (int, float)) else ""
        out.append({
            "source": "funding", "kind": "funding", "external_id": key, "url": f.get("url") or f.get("source_url") or "",
            "title": clean_text(f"{f['company_name']} raised {f.get('round', '')} {amount_s}", 300),
            "text": clean_text(json.dumps(f, ensure_ascii=False)),
            "author": f["company_name"], "author_url": "", "community": f.get("region", ""),
            "created_utc": to_epoch(f.get("announced_date")), "engagement": 0, "query": query,
        })
    return out


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# ---------- fetchers ----------

def fetch_hn(query, days=7, timeout=30):
    since = int(time.time()) - days * 86400
    params = urllib.parse.urlencode({
        "query": query, "tags": "(story,comment)",
        "numericFilters": f"created_at_i>{since}", "hitsPerPage": 50,
    })
    req = urllib.request.Request(f"{HN_API}?{params}", headers={"User-Agent": "lead-signal-listener/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return parse_hn(json.loads(r.read().decode("utf-8")), query)


def _bucket(days):
    # Idempotency seed bucket: identical query within the same hour is replayed for free.
    return f"{days}:{int(time.time() // 3600)}"


def fetch_reddit(client: TregClient, query, days=7):
    timeframe = "day" if days <= 1 else "week" if days <= 7 else "month" if days <= 31 else "year"
    resp, _ = client.call(ENDPOINTS["reddit"], query={"query": query, "sort": "relevance", "timeframe": timeframe,
                                                       "filter": "posts", "trim": "true"},
                          idempotency_seed=f"reddit|{query}|{_bucket(days)}")
    return parse_reddit(resp, query)


def fetch_x(client: TregClient, query, days=7):
    resp, _ = client.call(ENDPOINTS["x"], body={"q": query}, idempotency_seed=f"x|{query}|{_bucket(days)}")
    return parse_x(resp, query)


def fetch_linkedin_posts(client: TregClient, query, days=7):
    date_posted = "last-day" if days <= 1 else "last-week" if days <= 7 else "last-month" if days <= 31 else "last-year"
    resp, _ = client.call(ENDPOINTS["linkedin_posts"], body={"query": query, "datePosted": date_posted},
                          idempotency_seed=f"lip|{query}|{_bucket(days)}")
    return parse_linkedin_posts(resp, query)


def fetch_linkedin_jobs(client: TregClient, query, days=7, location="United States"):
    posted = "24h" if days <= 1 else "week" if days <= 7 else "month"
    resp, _ = client.call(ENDPOINTS["linkedin_jobs"], body={"query": query, "location": location, "postedLimit": posted},
                          idempotency_seed=f"lij|{query}|{location}|{_bucket(days)}")
    return parse_linkedin_jobs(resp, query)


def fetch_funding(client: TregClient, days=7, region="US", limit=50):
    since = datetime.fromtimestamp(time.time() - days * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
    resp, _ = client.call(ENDPOINTS["funding"], query={"since": since, "region": region, "limit": limit},
                          idempotency_seed=f"fund|{region}|{since}|{limit}")
    return parse_funding(resp, f"funding:{region}")
