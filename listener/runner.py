"""One listening run: fetch every enabled source/query, score, de-dupe, store."""
import threading
import time

from . import generic, sources
from .i18n import http_hint, t
from .scoring import score_signal
from .treg_client import TregClient, TregError

# Pages fetched per query for paged sources unless a source sets "max_pages".
DEFAULT_PAGES = 3

TREG_SOURCES = {
    "reddit": sources.fetch_reddit,
    "x": sources.fetch_x,
    "linkedin_posts": sources.fetch_linkedin_posts,
    "facebook_posts": sources.fetch_facebook_posts,
    "facebook_groups": sources.fetch_facebook_group,
    "instagram_hashtags": sources.fetch_instagram_hashtag,
    "instagram_reels": sources.fetch_instagram_reels,
}


class Runner:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        self.lock = threading.Lock()
        self.running = False
        self.last_log = []

    def run(self):
        if not self.lock.acquire(blocking=False):
            return {"ok": False, "error": t(self.config.data.get("lang", "en"), "busy")}
        self.running = True
        try:
            return self._run()
        finally:
            self.running = False
            self.lock.release()

    def _run(self):
        cfg = self.config.data
        lang = cfg.get("lang", "en")
        days = int(cfg.get("lookback_days", 7))
        budget_micro = int(float(cfg.get("max_cost_per_run_usd", 1.0)) * 1e6)
        min_keep = int(cfg.get("min_score_to_keep", 0))
        rules = cfg.get("rules")
        src_cfg = cfg.get("sources", {})
        started = int(time.time())
        log, fetched, new = [], 0, 0
        token = self.config.token()
        client = TregClient(token, max_cost_usd=float(cfg.get("max_cost_per_call_usd", 0.05)),
                            org=cfg.get("treg_org") or None) if token else None

        def keep(batch):
            nonlocal fetched, new
            fetched += len(batch)
            kept = []
            for s in batch:
                s["score"], s["persona"], s["matched"] = score_signal(s, rules)
                if s["score"] >= min_keep:
                    kept.append(s)
            n = self.store.upsert_signals(kept)
            new += n
            return len(batch), len(kept), n

        disabled = client is None

        def over_budget():
            return client is not None and client.spent_micro >= budget_micro

        def pages_for(cfg_block):
            try:
                return max(1, min(10, int(cfg_block.get("max_pages", DEFAULT_PAGES))))
            except (TypeError, ValueError):
                return DEFAULT_PAGES

        def single(fn):
            # Wrap a non-paged fetcher into the paged signature.
            return lambda cursor: (fn(), None)

        # job = (name, query, fetch(cursor) -> (signals, next_cursor), max_pages)
        jobs = []
        if src_cfg.get("hn", {}).get("enabled"):
            for q in src_cfg["hn"].get("queries", []):
                jobs.append(("hn", q, single(lambda q=q: sources.fetch_hn(q, days)), 1))
        for name, fn in TREG_SOURCES.items():
            sc = src_cfg.get(name, {})
            if sc.get("enabled"):
                for q in sc.get("queries", []):
                    jobs.append((name, q, lambda cursor, fn=fn, q=q: fn(client, q, days, cursor), pages_for(sc)))
        jc = src_cfg.get("linkedin_jobs", {})
        if jc.get("enabled"):
            for q in jc.get("queries", []):
                jobs.append(("linkedin_jobs", q, lambda cursor, q=q: sources.fetch_linkedin_jobs(
                    client, q, days, cursor, jc.get("location") or "United States"), pages_for(jc)))
        rc = cfg.get("rss") or {}
        if rc.get("enabled"):
            for url in rc.get("feeds", []):
                jobs.append(("rss", url, single(lambda url=url: generic.fetch_rss(url, rc.get("keywords"))), 1))
        for cs in cfg.get("custom_sources") or []:
            if not cs.get("enabled") or not cs.get("endpoint"):
                continue
            for q in cs.get("queries") or [""]:
                jobs.append((cs.get("name") or cs["endpoint"], q,
                             single(lambda cs=cs, q=q: generic.fetch_custom(client, cs, q, days)), 1))
        fc = src_cfg.get("funding", {})
        if fc.get("enabled"):
            jobs.append(("funding", fc.get("region", "US"),
                         single(lambda: sources.fetch_funding(client, days, fc.get("region", "US"))), 1))

        free = {"hn", "rss"}
        for name, q, fetch, max_pages in jobs:
            if name not in free and disabled:
                log.append(t(lang, "skip_no_token" if client is None else "skip_disabled", name=name, q=q))
                continue
            if name not in free and over_budget():
                log.append(t(lang, "skip_budget", name=name, q=q, budget=budget_micro / 1e6))
                continue
            got = kept = n = pages = 0
            cursor = None
            try:
                while pages < max_pages:
                    if pages and name not in free and over_budget():
                        break
                    rows, cursor = fetch(cursor)
                    pages += 1
                    g, k, nn = keep(rows)
                    got, kept, n = got + g, kept + k, n + nn
                    if not cursor or not rows:
                        break
                log.append(t(lang, "ok", name=name, q=q, got=got, kept=kept, new=n, pages=pages))
            except TregError as e:
                if pages:
                    log.append(t(lang, "ok", name=name, q=q, got=got, kept=kept, new=n, pages=pages))
                err = f"HTTP {e.status} {http_hint(lang, e.status)} {e.detail}".strip()
                log.append(t(lang, "error", name=name, q=q, err=err))
                if e.status in (401, 402):
                    log.append(t(lang, "stop"))
                    disabled = True
            except Exception as e:  # network/parse issues on one query must not kill the run
                log.append(t(lang, "error", name=name, q=q, err=f"{type(e).__name__}: {e}"))

        cost = client.spent_micro if client else 0
        calls = client.calls if client else 0
        log.append(t(lang, "done", fetched=fetched, new=new, calls=calls, cost=cost / 1e6))
        self.store.add_run(started, int(time.time()), new, fetched, cost, calls, log)
        self.last_log = log
        return {"ok": True, "new": new, "fetched": fetched, "cost_usd": cost / 1e6, "calls": calls, "log": log}
