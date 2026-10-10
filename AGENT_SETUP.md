# Agent Setup Guide — Lead Signal Listener

> **For humans:** copy the prompt below into your AI agent (Claude Code, Codex, Cursor, NewMax…):
>
> ```
> Read AGENT_SETUP.md from https://github.com/yangyixxxx/lead-signal-listener
> and set up Lead Signal Listener for me. Walk me through choosing keywords and scoring rules.
> ```
>
> **For agents:** this file is your playbook. Follow the steps in order. Talk to the user in **their** language. Ask one group of questions at a time, propose concrete defaults, and let the user edit them. Never print, log or commit the user's Treg token.

---

## What this project does

Lead Signal Listener is a local web app that finds people publicly describing a problem your user can solve, then scores, de-duplicates and queues them for review.

It can listen in several ways, and they can be combined:

| Method | How | Cost |
|---|---|---|
| Built-in sources | Reddit, X, LinkedIn posts, LinkedIn jobs (hiring signals), Facebook posts, Facebook groups, Instagram hashtags, Instagram Reels, funding news, through [Treg](https://treg.to) | Paid per call, usually under $0.01 (Facebook post search ~$0.03) |
| Hacker News | Official Algolia API | Free |
| RSS / Atom | Any feed: Google Alerts, `reddit.com/r/NAME/new/.rss`, `hnrss.org/newest?q=...`, blogs, job boards | Free |
| Custom Treg endpoint | Any of the 3,800+ Treg catalog endpoints (YouTube, TikTok, Google News, reviews…) using a params template and field mapping | Paid per call |
| Import | `POST /api/import` or `python app.py --import file.json`, for leads you or another agent found anywhere | Free |

Everything runs on the user's machine. Data lives in `data/` (git-ignored).

---

## Step 1 — Install and start

Requirements: Python 3.10 or newer. There are no third-party dependencies.

```bash
git clone https://github.com/yangyixxxx/lead-signal-listener.git
cd lead-signal-listener
python -m unittest discover tests      # should pass
python app.py --no-browser             # serves http://127.0.0.1:8787
```

Run the server in the background and tell the user to open `http://127.0.0.1:8787`. The UI defaults to English; there is an `EN / 中文` toggle in the top-right corner.

## Step 2 — Treg token (optional but recommended)

Without a token, only the free sources run (Hacker News, RSS, import).

1. Ask the user to create an account at [treg.to](https://treg.to) and copy a token. Tokens look like `trg_live_...`; team tokens look like a JWT.
2. Prefer the environment variable so the token never touches disk:
   ```bash
   TREG_TOKEN=... python app.py          # macOS / Linux
   $env:TREG_TOKEN="..."; python app.py   # Windows PowerShell
   ```
   Alternatively, the user can paste it into **Settings → Treg token** in the UI. It is then stored in `data/config.json`.
3. Verify the token without spending money:
   ```bash
   curl -s -X POST http://127.0.0.1:8787/api/test-token -H "Content-Type: application/json" -d "{}"
   ```

**Do not ask the user to paste the token into the chat if you can avoid it.** If they do, write it straight to the env var or config file, and suggest rotating it afterwards.

## Step 3 — Interview the user (most important)

Keywords and scoring are only as good as your understanding of the buyer. Ask these questions in two or three short rounds, and offer example answers:

1. **Offer:** What do you sell, and what result does the customer get?
2. **Buyer:** Who pays? Role, company type, company size, region.
3. **Trigger:** What happens right before someone needs you? (traffic dropped, just raised money, hiring a role, launched a product, a competitor did X…)
4. **Pain language:** How would that buyer describe the problem *in their own words* in a Reddit post? Ask for 3 to 5 example sentences.
5. **Where they talk:** Which subreddits, X communities, LinkedIn topics, forums, newsletters?
6. **Noise to exclude:** Who uses the same words but is *not* a buyer? (competitors and agencies promoting themselves, job seekers, students, vendors…)
7. **Budget:** How much per run and per month is OK to spend on paid sources?

Summarize the answers back as a one-paragraph ideal customer profile (ICP) and get a yes before moving on. Then condense it into **one sentence** and save it as `focus` (Step 6). It's shown at the top of the Leads page, e.g. *"B2B SaaS founders whose organic traffic dropped because of AI search."*

## Step 4 — Propose keywords

Turn the ICP into keyword sets. Rules that work:

- **Write like the buyer, not like the seller.** Use "our traffic dropped after AI Overviews", not "GEO services".
- **Questions and first person do well:** "how do I…", "anyone tried…", "we can't get…", "looking for an agency…".
- **Keep each query to 2–4 words.** Long exact sentences ("ChatGPT doesn't mention our brand") match very little; single words return noise. Short buyer phrases ("show up in ChatGPT") work best.
- Aim for **5–10 queries per paid source**.
- **Pages:** each paged source (Reddit, X, LinkedIn) has `max_pages` (default 3 for Reddit/X, 2 for LinkedIn). One page = one paid call. A Reddit page holds ~7 posts and an X page ~20, and later pages are usually still relevant, so more pages is the cheapest way to get more leads. Raise it before adding many more keywords.
- **Hiring signals:** use job titles that imply budget for the problem (e.g. "Head of Growth", "SEO Manager").
- **RSS:** subreddit `.rss` feeds plus `https://hnrss.org/newest?q=<keyword>`; use the RSS keyword filter to cut noise.
- **Facebook / Instagram** (off by default): `facebook_groups` takes public group URLs (ask the user which communities their buyers join; group posts are often the highest-intent leads), `instagram_hashtags` takes hashtags without `#`, `facebook_posts` and `instagram_reels` take keywords. Facebook post search is the priciest source (~$0.03 per page), so keep `max_pages` at 1 there.
- **Other platforms:** search the catalog and add custom sources (see Step 7).

Show the user a table: source × queries × pages, plus an estimated cost per run (paid queries × pages × ~$0.002 for Reddit/LinkedIn posts, ~$0.001 for X, ~$0.0005 for LinkedIn jobs). Let them edit it.

## Step 5 — Propose scoring rules

Scoring is transparent and rule-based (`rules` in the config). Each signal's title, text and community are matched against these lists:

```jsonc
{
  "pain":     { "<phrase>": <weight> },      // the problem itself: "traffic dropped": 12
  "intent":   { "<phrase>": <weight> },      // buying / asking for help: "looking for": 10, "recommend an agency": 15
  "persona":  { "<segment>": ["<word>", ...] },  // who they are: "saas": ["b2b", "mrr", "founder"]
  "negative": { "<phrase>": <negative weight> }  // noise: "check out my": -10, "we offer": -15
}
```

How the score is calculated (capped at 0–100): pain (up to 45) + intent (up to 30) + persona matches × 3 (up to 10) + engagement/10 (up to 10) + 5 if it's a question + a base of 30 for hiring or 35 for funding signals + negative weights.

Guidelines:
- Pain weights: 6–12. Intent weights: 5–15. Make "asking for a recommendation" the strongest signal.
- **Always add negatives for sellers.** On X especially, many results are agencies promoting themselves. Phrases like "we help", "book a call", "our agency", "DM me" are good candidates.
- Two or three personas are enough. Their names show up as filters in the UI.

## Step 6 — Write the configuration

Either edit it in the UI (**Listeners** tab) or POST a partial config. Only the keys you send are changed; lists are replaced as a whole:

```bash
curl -s -X POST http://127.0.0.1:8787/api/config -H "Content-Type: application/json" -d @setup.json
```

`setup.json` example:

```json
{
  "focus": "B2B SaaS founders whose organic traffic dropped because of AI search.",
  "lookback_days": 7,
  "max_cost_per_call_usd": 0.05,
  "max_cost_per_run_usd": 0.5,
  "min_score_to_keep": 10,
  "sources": {
    "hn":            {"enabled": true,  "queries": ["AI Overviews traffic"]},
    "reddit":        {"enabled": true,  "max_pages": 3, "queries": ["AI Overviews traffic", "show up in ChatGPT"]},
    "x":             {"enabled": true,  "max_pages": 3, "queries": ["GEO agency", "AI search visibility"]},
    "linkedin_posts":{"enabled": false, "queries": []},
    "linkedin_jobs": {"enabled": true,  "location": "United States", "queries": ["Head of Growth"]},
    "funding":       {"enabled": false, "region": "US"}
  },
  "rss": {"enabled": true, "keywords": ["ai overviews", "chatgpt"],
          "feeds": ["https://www.reddit.com/r/SaaS/new/.rss", "https://hnrss.org/newest?q=%22AI+Overviews%22"]},
  "rules": { "pain": {}, "intent": {}, "persona": {}, "negative": {} }
}
```

> `rules` is replaced as a whole, so send the complete rules object.

## Step 7 — Add custom sources (optional)

Find an endpoint (no token needed):

```bash
python app.py --catalog "youtube search videos"
```

Then add it under `custom_sources`:

```json
{
  "name": "youtube", "enabled": true, "kind": "pain",
  "endpoint": "treg.youtube.search.videos", "method": "POST",
  "params": {"q": "{q}"},
  "queries": ["ChatGPT not recommending my brand"],
  "url_template": "https://www.youtube.com/watch?v={id}",
  "fields": {"id": "video_id", "author": "author", "created": "published_time"}
}
```

- `params`: query string for GET, JSON body for POST. `{q}` is replaced by each query; `{days}` by the lookback.
- `fields` (optional): signal field → response path. `a.b|c` means "try `a.b`, then `c`". Sensible defaults cover most APIs.
- `items_path` (optional): where the result list lives. By default the first list of objects found is used.
- `kind`: `pain` | `hiring` | `funding` | `mention` | `other`.

To check the response shape, run one query with `max_cost_per_run_usd` set low, then look at the run log and the leads list.

## Step 8 — First run, review, tune

1. **Confirm the budget with the user before the first paid run.** The default config is about 50 paid calls per run (with paging), roughly $0.07. The per-run budget stops paging early if reached.
2. Click **Run now** (or `POST /api/run`, or `python app.py --run-once`).
3. Review the top 20 leads *with the user*. For each false positive, ask why it's wrong and turn the answer into a negative phrase or a keyword change.
4. Save the rules, then click **Rescore all leads** (`POST /api/rescore`). Repeat until most of the top 20 are real buyers.
5. Set **Auto-run every N hours** in Settings, or schedule `python app.py --run-once` with cron or Windows Task Scheduler.

## Step 9 — Daily workflow to hand over

- Open the **Leads** tab, filter `status = new`, and work from the highest score down. Leads are stored permanently in `data/signals.db` and de-duplicated, so each run only adds new ones: use **range → New in last run** (or **sort → Newest found**) to see what the latest run added.
- Mark leads `qualified` / `contacted` / `replied` / `ignored` and add notes.
- Export CSV/JSON for outreach tools or CRM. The JSON export can be fed to an LLM for deeper qualification or for drafting replies.
- Push leads found elsewhere into the same queue:
  ```bash
  curl -s -X POST http://127.0.0.1:8787/api/import -H "Content-Type: application/json" \
    -d '{"source":"agent","signals":[{"url":"https://...","title":"...","text":"...","author":"..."}]}'
  ```

---

## API reference

All endpoints are local only (`127.0.0.1`). Write requests must send `Content-Type: application/json`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Current config (token masked) |
| POST | `/api/config` | Partial update |
| POST | `/api/test-token` | Free token check |
| POST | `/api/run` | Start a run in the background |
| GET | `/api/status` | Running state, stats (incl. `last_run.new`), last log, recent runs |
| GET | `/api/signals?status=&source=&persona=&min_score=&q=&scope=last_run&sort=score\|recent&limit=&offset=` | List leads (paged; total in the `X-Total-Count` header). `scope=last_run` = only leads first seen in the latest run |
| POST | `/api/signals/<id>` | `{"status": "...", "note": "..."}` |
| POST | `/api/import` | Import signals (`{"source": "...", "signals": [...]}` or a bare list) |
| POST | `/api/rescore` | Re-apply scoring rules to all leads |
| GET | `/api/catalog?q=` | Search the Treg catalog |
| GET | `/api/export?fmt=csv|json&...filters` | Export |

## Guardrails

- Only collect public content. Respect each platform's and each Treg provider's terms.
- This is a research and lead discovery tool. Do not use it to mass-message people. Follow GDPR and CAN-SPAM in outreach.
- Never echo the token in commands, logs, commits or chat. `data/` must stay out of git.
- Stay within the user's budget. The per-call cap (`X-Treg-Route-Max-Cost`) and per-run budget are enforced, but confirm before raising them.
