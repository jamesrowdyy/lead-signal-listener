"""Local config stored at data/config.json. The Treg token can also come from env TREG_TOKEN
(env wins and is never written to disk)."""
import copy
import json
import os
import threading

from .scoring import DEFAULT_RULES

PAIN_QUERIES = [
    "AI Overviews traffic drop",
    "ChatGPT doesn't mention our brand",
    "how to show up in ChatGPT",
    "GEO agency recommendation",
    "organic traffic dropped AI search",
    "AI search visibility",
]

DEFAULT_CONFIG = {
    "treg_token": "",
    "treg_org": "",
    "lang": "en",
    # One sentence describing who you're looking for; shown on the Leads page.
    "focus": "",
    "lookback_days": 7,
    "max_cost_per_call_usd": 0.05,
    "max_cost_per_run_usd": 1.0,
    "schedule_hours": 0,
    "min_score_to_keep": 10,
    "sources": {
        "hn": {"enabled": True, "queries": ["AI Overviews", "ChatGPT SEO", "LLM visibility",
                                            "customer acquisition"]},
        "reddit": {"enabled": True, "queries": PAIN_QUERIES},
        "x": {"enabled": True, "queries": PAIN_QUERIES[:4]},
        "linkedin_posts": {"enabled": False, "queries": PAIN_QUERIES[:3]},
        "linkedin_jobs": {"enabled": True, "location": "United States",
                          "queries": ["Head of Growth", "Growth Marketing Manager", "SEO Manager GEO"]},
        "funding": {"enabled": False, "region": "US"},
    },
    # Free: any RSS/Atom feed. Optional keyword filter (match any; empty = keep everything).
    "rss": {"enabled": False, "keywords": [],
            "feeds": ["https://hnrss.org/newest?q=%22AI+Overviews%22",
                      "https://www.reddit.com/r/SaaS/new/.rss"]},
    # Any Treg catalog endpoint. Find ids with: python app.py --catalog "what you want".
    # params: GET -> query string, POST -> JSON body; "{q}" is replaced by each query, "{days}" by lookback.
    # fields (optional): map signal fields to response paths, "a.b|c" = alternatives. items_path optional.
    "custom_sources": [
        {"name": "google_news", "enabled": False, "kind": "mention",
         "endpoint": "treg.google.serp.news", "method": "POST",
         "params": {"q": "{q}", "limit": 20}, "queries": ["AI search visibility agency"]},
        {"name": "youtube", "enabled": False, "kind": "pain",
         "endpoint": "treg.youtube.search.videos", "method": "POST",
         "params": {"q": "{q}"}, "queries": ["ChatGPT not recommending my brand"],
         "url_template": "https://www.youtube.com/watch?v={id}",
         "fields": {"id": "video_id", "author": "author", "created": "published_time"}},
    ],
    "rules": DEFAULT_RULES,
}


class Config:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _merge(self.data, json.load(f))
        else:
            self.save()

    def token(self):
        return os.environ.get("TREG_TOKEN") or self.data.get("treg_token") or ""

    def token_source(self):
        if os.environ.get("TREG_TOKEN"):
            return "env"
        return "file" if self.data.get("treg_token") else "none"

    def public(self):
        """Config safe to send to the browser: token masked."""
        d = copy.deepcopy(self.data)
        t = self.token()
        d["treg_token"] = (t[:9] + "…" + t[-4:]) if len(t) > 16 else ("set" if t else "")
        d["token_source"] = self.token_source()
        return d

    def update(self, patch):
        with self.lock:
            patch = dict(patch)
            token = patch.pop("treg_token", None)
            patch.pop("token_source", None)
            # Only overwrite the token when a real new value is submitted (not the masked echo).
            if token is not None and "…" not in token and token not in ("set", "已设置"):
                self.data["treg_token"] = token.strip()
            _merge(self.data, patch)
            self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)


def _merge(dst, src):
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict) and k not in ("rules",):
            _merge(dst[k], v)
        else:
            dst[k] = v
