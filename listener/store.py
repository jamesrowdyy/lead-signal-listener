"""SQLite storage with de-duplication on (source, external_id)."""
import csv
import io
import json
import sqlite3
import threading
import time

STATUSES = ("new", "qualified", "contacted", "replied", "ignored")

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL, kind TEXT NOT NULL, external_id TEXT NOT NULL,
  url TEXT, title TEXT, text TEXT, author TEXT, author_url TEXT, community TEXT,
  created_utc INTEGER, engagement INTEGER DEFAULT 0, query TEXT,
  score INTEGER DEFAULT 0, persona TEXT, matched TEXT,
  status TEXT DEFAULT 'new', note TEXT DEFAULT '',
  first_seen INTEGER NOT NULL,
  UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_signals_score ON signals(score DESC);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started INTEGER, finished INTEGER, new_signals INTEGER DEFAULT 0,
  fetched INTEGER DEFAULT 0, cost_micro INTEGER DEFAULT 0, calls INTEGER DEFAULT 0, log TEXT
);
"""

EXPORT_FIELDS = ["id", "score", "persona", "status", "source", "kind", "community", "author", "author_url",
                 "title", "text", "url", "query", "matched", "engagement", "created_utc", "note"]


class Store:
    def __init__(self, path):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.db.commit()

    def upsert_signals(self, signals):
        """Insert unseen signals; returns number of new rows."""
        new = 0
        now = int(time.time())
        with self.lock:
            for s in signals:
                cur = self.db.execute(
                    """INSERT OR IGNORE INTO signals
                       (source, kind, external_id, url, title, text, author, author_url, community,
                        created_utc, engagement, query, score, persona, matched, first_seen)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (s["source"], s["kind"], s["external_id"], s.get("url"), s.get("title"), s.get("text"),
                     s.get("author"), s.get("author_url"), s.get("community"), s.get("created_utc"),
                     s.get("engagement", 0), s.get("query"), s.get("score", 0), s.get("persona"),
                     json.dumps(s.get("matched", []), ensure_ascii=False), now))
                new += cur.rowcount
            self.db.commit()
        return new

    def list_signals(self, status=None, source=None, persona=None, min_score=0, q=None, limit=200, offset=0):
        sql, args = "SELECT * FROM signals WHERE score >= ?", [int(min_score or 0)]
        for col, val in (("status", status), ("source", source), ("persona", persona)):
            if val:
                sql += f" AND {col} = ?"
                args.append(val)
        if q:
            sql += " AND (title LIKE ? OR text LIKE ? OR author LIKE ?)"
            args += [f"%{q}%"] * 3
        sql += " ORDER BY score DESC, first_seen DESC LIMIT ? OFFSET ?"
        args += [int(limit), int(offset)]
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        return [_row(r) for r in rows]

    def update_signal(self, sid, status=None, note=None):
        if status is not None and status not in STATUSES:
            raise ValueError(f"invalid status: {status}")
        with self.lock:
            if status is not None:
                self.db.execute("UPDATE signals SET status=? WHERE id=?", (status, sid))
            if note is not None:
                self.db.execute("UPDATE signals SET note=? WHERE id=?", (note, sid))
            self.db.commit()

    def rescore_all(self, scorer):
        with self.lock:
            rows = self.db.execute("SELECT id, kind, title, text, community, engagement FROM signals").fetchall()
            for r in rows:
                score, persona, matched = scorer(dict(r))
                self.db.execute("UPDATE signals SET score=?, persona=?, matched=? WHERE id=?",
                                (score, persona, json.dumps(matched, ensure_ascii=False), r["id"]))
            self.db.commit()
        return len(rows)

    def stats(self):
        with self.lock:
            by_status = dict(self.db.execute("SELECT status, COUNT(*) FROM signals GROUP BY status").fetchall())
            by_source = dict(self.db.execute("SELECT source, COUNT(*) FROM signals GROUP BY source").fetchall())
            spent = self.db.execute("SELECT COALESCE(SUM(cost_micro),0), COALESCE(SUM(calls),0) FROM runs").fetchone()
            month_start = int(time.time()) - 30 * 86400
            spent30 = self.db.execute("SELECT COALESCE(SUM(cost_micro),0) FROM runs WHERE started >= ?",
                                      (month_start,)).fetchone()[0]
        return {"by_status": by_status, "by_source": by_source, "total": sum(by_status.values()),
                "spent_usd": spent[0] / 1e6, "spent_30d_usd": spent30 / 1e6, "calls": spent[1]}

    def add_run(self, started, finished, new_signals, fetched, cost_micro, calls, log):
        with self.lock:
            self.db.execute("INSERT INTO runs (started, finished, new_signals, fetched, cost_micro, calls, log)"
                            " VALUES (?,?,?,?,?,?,?)",
                            (started, finished, new_signals, fetched, cost_micro, calls, "\n".join(log)))
            self.db.commit()

    def recent_runs(self, limit=10):
        with self.lock:
            rows = self.db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def export(self, fmt="csv", **filters):
        rows = self.list_signals(limit=100000, **filters)
        if fmt == "json":
            return json.dumps(rows, ensure_ascii=False, indent=2)
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            r = dict(r)
            r["matched"] = ", ".join(r.get("matched") or [])
            w.writerow(r)
        return "﻿" + buf.getvalue()  # BOM so Excel opens UTF-8 correctly


def _row(r):
    d = dict(r)
    try:
        d["matched"] = json.loads(d.get("matched") or "[]")
    except json.JSONDecodeError:
        d["matched"] = []
    return d
