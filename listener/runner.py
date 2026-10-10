"""One listening run: fetch every enabled source/query, score, de-dupe, store."""
import threading
import time

from . import generic, sources
from .i18n import http_hint, t
from .scoring import score_signal
from .treg_client import TregClient, TregError

TREG_SOURCES = {
    "reddit": sources.fetch_reddit,
    "x": sources.fetch_x,
    "linkedin_posts": sources.fetch_linkedin_posts,
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

        jobs = []
        if src_cfg.get("hn", {}).get("enabled"):
            for q in src_cfg["hn"].get("queries", []):
                jobs.append(("hn", q, lambda q=q: sources.fetch_hn(q, days)))
        for name, fn in TREG_SOURCES.items():
            if src_cfg.get(name, {}).get("enabled"):
                for q in src_cfg[name].get("queries", []):
                    jobs.append((name, q, lambda fn=fn, q=q: fn(client, q, days)))
        jc = src_cfg.get("linkedin_jobs", {})
        if jc.get("enabled"):
            for q in jc.get("queries", []):
                jobs.append(("linkedin_jobs", q, lambda q=q: sources.fetch_linkedin_jobs(
                    client, q, days, jc.get("location") or "United States")))
        rc = cfg.get("rss") or {}
        if rc.get("enabled"):
            for url in rc.get("feeds", []):
                jobs.append(("rss", url, lambda url=url: generic.fetch_rss(url, rc.get("keywords"))))
        for cs in cfg.get("custom_sources") or []:
            if not cs.get("enabled") or not cs.get("endpoint"):
                continue
            for q in cs.get("queries") or [""]:
                jobs.append((cs.get("name") or cs["endpoint"], q,
                             lambda cs=cs, q=q: generic.fetch_custom(client, cs, q, days)))
        fc = src_cfg.get("funding", {})
        if fc.get("enabled"):
            jobs.append(("funding", fc.get("region", "US"),
                         lambda: sources.fetch_funding(client, days, fc.get("region", "US"))))

        free = {"hn", "rss"}
        for name, q, fn in jobs:
            if name not in free and disabled:
                log.append(t(lang, "skip_no_token" if client is None else "skip_disabled", name=name, q=q))
                continue
            if name not in free and over_budget():
                log.append(t(lang, "skip_budget", name=name, q=q, budget=budget_micro / 1e6))
                continue
            try:
                got, kept, n = keep(fn())
                log.append(t(lang, "ok", name=name, q=q, got=got, kept=kept, new=n))
            except TregError as e:
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
