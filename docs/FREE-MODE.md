# Alimne free mode

Alimne is **free for everyone**: no tokens, no credits, no paywall, no subscription upsell.
The AI (Groq) still costs money per guide and the server is small, so free is kept safe with
four things: fair-use daily caps, a global daily budget breaker, a generation queue, and a
per-minute rate limit. We say "free" and "fair use". We never say "unlimited".

This file is the operator's manual: the knobs, how to switch free mode off, how fair use
works, what the server can actually carry, how to control cost, what to watch, and the
launch checklist.

> The numbers and error codes below are the design contract between the credit logic in
> `app.py`, the React client and these pages. After any change to the credit logic, re-check
> the defaults table against the constants in `app.py`.

---

## 1. Environment knobs

All optional. Set them in the Render dashboard (Environment). When a variable is unset the
code default applies.

| Variable | Default | What it does |
|---|---|---|
| `ALIMNE_FREE_MODE` | `1` (on) | `0` brings the old token system back exactly (see section 2). |
| `FAIR_DEVICE_DAILY` | `10` | Guides per **anonymous device** (header `X-Device-Id`) per 24 h window. |
| `FAIR_IP_DAILY` | `250` | Guides per **IP address** per 24 h window. Generous on purpose: campuses, hostels and mobile carriers put hundreds of students behind one IP. |
| `FAIR_USER_DAILY` | `40` | Guides per **signed-in user** (user id) per 24 h window. |
| `FAIR_GLOBAL_DAILY` | `2000` | Guides across **all users** per 24 h window. This is the budget breaker. |
| `GEN_MAX_CONCURRENT` | `3` | Generations running at the same time, process-wide. |
| `GEN_QUEUE_WAIT_S` | `45` | How long a request waits for a free slot before giving up with `busy`. |
| `RATE_SUMMARIZE_PER_MIN` | `30` | Per-IP, per-minute limit on the generation endpoints (it used to be a hard-coded 5, which blocked a whole class sharing one IP). |

Related settings that already existed and matter for cost: `GROQ_API_KEY`, `GROQ_MODEL`
(`openai/gpt-oss-120b` in `render.yaml`), `GROQ_TPM_LIMIT` (`200000` in `render.yaml`; the code
default is `7000`, so the variable must exist on Render).

**Changing any environment variable restarts the service on Render, and the job store is in
memory.** Every guide that is open in someone's browser (15-minute window) is lost on restart.
Change knobs off-peak when you can, and tell nobody to panic when you cannot.

---

## 2. Turning free mode off (rollback)

Set `ALIMNE_FREE_MODE=0` and redeploy/restart. The old behaviour returns exactly: tokens are
consumed and refunded, 402 `no_tokens` / `signin_for_more` come back, Stripe checkout works
again, signup token grants and the referral reward are promised and awarded again.

What follows the switch automatically:

- `/terms` and `/privacy` read the variable on every request. With `0` they describe the token
  plans again (Free plan / Pro plan); with anything else they say Alimne is free. The page can
  never contradict what the app is doing. Covered by `tests/test_copy_truth.py`.

What does **not** follow (static files, they cannot read the environment):

- `frontend/index.html` / `dist/index.html` title and meta tags ("Free AI study guides ..."),
  and the social preview picture `og.png` ("Free for everyone - no credit card"). If you roll
  back for more than a day or two, restore the old copy by hand.

Never touched by free mode, in either direction: `/api/stripe/webhook` and
`/api/stripe/portal`. People who subscribed before the change can always manage or cancel.

Use the rollback for a real emergency only. For a cost spike the right tool is usually to
lower `FAIR_GLOBAL_DAILY` or `FAIR_DEVICE_DAILY` (section 5), which keeps the product free
and degrades gracefully.

---

## 3. How fair use works

**Counters.** Each generation (`/api/summarize-stream`, `/api/youtube`, `/api/summarize-text`,
non-demo) is charged against **every applicable counter**:

| Who | Counters charged |
|---|---|
| Anonymous visitor | `fair:dev:<device>` + `fair:ip:<ip>` + `fair:global` |
| Signed-in user | `fair:user:<user id>` + `fair:ip:<ip>` + `fair:global` |

The demo path stays free and unmetered. No token is consumed in free mode.

**Storage.** The counters reuse the existing durable RPCs `anon_consume(p_key, p_limit,
p_window_hours=24)` and `anon_refund(p_key)` (migrations 009 and 012) with the new key prefixes
above. Rows live in `public.anon_usage`. No new migration is needed.

**Windows.** A counter's 24 h window starts at its first use and resets 24 h later (that is how
`anon_consume` works). It is a fixed window per key, not a sliding one. For `fair:global` this
means the daily budget resets at an arbitrary hour, not at midnight.

**Order.** Validation first (a bad file never costs anyone a slot or a count), then charge all
counters, then queue for a generation slot. If one counter is exhausted, the ones already taken
are rolled back (`anon_refund`) and the request is refused.

**Refunds.** If a generation fails or the visitor abandons it, the counters are given back
exactly once (the existing single-owner charge/refund machinery).

**Fail open.** If the RPC is missing or errors, the request is allowed and the problem is logged.
A database hiccup must never block a real student. The flip side, and a launch risk: **if the
RPCs are missing the caps silently do not apply.** Verify them before launch (section 8).

**Refusals** (JSON `{error, code, retry_after_s?}`):

| HTTP | `code` | Meaning |
|---|---|---|
| 429 | `fair_use_device` | This anonymous device used its daily allowance. The message tells the visitor to sign in free for a higher one. This is the signup funnel. |
| 429 | `fair_use_ip` | This IP used its daily allowance (shared networks can hit it). |
| 429 | `fair_use_user` | This signed-in account used its daily allowance. |
| 503 | `busy_today` | The global daily budget is used up. Everyone is refused until the window resets. |
| 503 | `busy` | The queue wait (`GEN_QUEUE_WAIT_S`) ran out. Try again in a moment. |
| 429 | (rate limit) | More than `RATE_SUMMARIZE_PER_MIN` requests from one IP in a minute. |

No `402` is returned in free mode. SSE `done` events keep their shape; `tokens_remaining` may be
missing or null and the client tolerates both.

**Queue.** A process-wide `BoundedSemaphore(GEN_MAX_CONCURRENT)` wraps the generation work. When
all slots are busy the request waits up to `GEN_QUEUE_WAIT_S`, sending SSE events
`{"step":"queued","position":<n>,"msg":"..."}` about every 3 s so the student sees a place in
line. The slot is released in a `finally` on every path: done, error, client disconnect.

**Config the client reads.** `/api/config` adds `free_mode` and
`fair_use {device_daily, user_daily}`. `/api/auth/me` adds `free_mode: true`. In free mode
`/api/stripe/checkout` answers `410 free_now` and creates no Stripe session.

---

## 4. Capacity: what the server can really carry

The current Render service: **1 gunicorn worker, 0.5 CPU, 512 MB RAM, 1 instance**, Python 3.14.
The live start command uses `--threads 4`; `render.yaml` says `--threads 8` (see drift note below).
Guides live in an in-memory job store for 15 minutes.

- **3 concurrent generations** (`GEN_MAX_CONCURRENT`). Each one holds a Flask thread for its whole
  run (the stream), so with 4 threads only one thread is left for everything else.
- **A queued request also holds a thread** while it waits (the wait happens inside the request).
  With 4 threads: 3 running + 1 waiting = every thread busy. Anything else, including
  `/healthz`, waits in gunicorn's backlog. If Render's health check times out repeatedly it
  restarts the service, and a restart wipes every in-memory guide. **Do not launch free mode on
  4 threads.** Use 8 (what `render.yaml` already says) and watch memory.
- **Peak-hour arithmetic.** Throughput is roughly `slots / seconds-per-guide`. Example: if a guide
  takes about 60 s, 3 slots serve about 180 guides an hour (about 4,300 a day if saturated all
  day). `FAIR_GLOBAL_DAILY=2000` looks comfortable, but traffic is peaky (exam season, evenings):
  400 guides in a single hour is more than 180, the queue grows, 45 s waits expire, and students
  see `busy`. In practice the slots, not the budget, are the limit at peak. Measure the real
  seconds-per-guide in the first week and revisit.
- **Groq's own limit.** Calls are paced under `GROQ_TPM_LIMIT` tokens per minute across the whole
  process. If the pacer is the bottleneck, more slots will not help.
- **Memory.** Each in-flight request holds its upload in RAM (up to 50 MB; typical slide decks are
  far smaller). 8 threads on 512 MB is workable but not roomy.

**Drift to resolve before launch:** the Render dashboard start command (`--threads 4`) and
`render.yaml` (`--threads 8`) disagree. The dashboard wins in production. Make them match, on
purpose, and keep the code comments honest (`_REHYDRATE_SLOTS` is written for 8).

**Upgrade path: scale UP, never out.** The job store and the Groq pacer are per process:

- Do **not** add instances and do **not** raise `--workers` above 1. A guide created on one
  instance cannot be found by the other (students would get "guide expired" at random).
- Move to a bigger Render plan (more CPU and RAM) and raise `--threads` and `GEN_MAX_CONCURRENT`
  together, keeping at least 2 threads free for light endpoints and queued waiters.
- Only when one big instance is not enough: move the job store to shared storage (Redis or the
  database) first, then scale out.

---

## 5. Cost-control levers (cheapest and gentlest first)

1. **`FAIR_DEVICE_DAILY`** (anonymous allowance). Lowering it pushes more visitors to sign in.
2. **`FAIR_USER_DAILY`** and **`FAIR_IP_DAILY`**.
3. **`FAIR_GLOBAL_DAILY`**, the hard ceiling: worst-case daily AI spend is roughly
   `FAIR_GLOBAL_DAILY x cost-per-guide`. Read cost-per-guide from the Groq dashboard after the
   first days (tokens per guide times price), then set the number so the ceiling is a bill you
   are happy to pay.
4. **`GEN_MAX_CONCURRENT` / `GEN_QUEUE_WAIT_S`**: slow the spend rate instead of refusing.
5. **`GROQ_MODEL`**: a cheaper model, if quality allows.
6. **A Groq spend limit and alert** in the Groq console (the real backstop, section 8).
7. **`ALIMNE_FREE_MODE=0`**: last resort (section 2).

Counters are compared against the limit on every request, so lowering a limit takes effect
straight away (after the restart the variable change causes).

---

## 6. What to monitor

| Where | Look at | Worry when |
|---|---|---|
| Render > Metrics | CPU, memory, restarts, 5xx rate, response time | CPU above about 80% for minutes; memory above about 400 of 512 MB; any restart or out-of-memory kill |
| Render > Logs | Fail-open lines (the existing wording is "anon durable consume failed" / "anon durable refund failed"; search for `anon_consume` and `fair` too), `busy` refusals, `fair_use_*` refusals, Groq 429s | Any fail-open line at launch (caps are not applying); many `busy` in one hour |
| Groq console | Requests and tokens per day, 429s, spend against your limit | Spend trending past the limit you set; many 429s (raise the Groq tier or lower concurrency) |
| Supabase > Auth | Signups per day, provider mix (Google vs email), email errors and rate-limit errors in Auth logs | Signups fail or confirmation emails do not arrive (section 8, custom SMTP) |
| Supabase > SQL | The queries below | `fair:global` near its limit before evening; one device or IP far above the rest |
| `/admin` (existing dashboard) | Usage events and visit stats, if migrations 008 and 011 are applied | Guides per day versus visits (conversion) |
| The funnel | `fair_use_device` refusals versus new signups the same day | Many device refusals and few signups: the sign-in prompt is not converting |

Read-only queries for the Supabase SQL editor:

```sql
-- are the RPCs there? (must return 3 rows; if not, the caps do not apply)
select proname from pg_proc where proname in ('anon_consume','anon_remaining','anon_refund');

-- the global budget right now
select key, count, window_start, last_at from public.anon_usage where key = 'fair:global';

-- heaviest devices / IPs / users in the current windows
select key, count, last_at from public.anon_usage
where key like 'fair:dev:%' or key like 'fair:ip:%' or key like 'fair:user:%'
order by count desc limit 20;
```

Housekeeping (optional, run by hand now and then): counters are never purged automatically. Old
`fair:` rows hold only a count and timestamps, but there is no reason to keep them forever (the
privacy page says old counters may be deleted at any time).

```sql
delete from public.anon_usage
where key like 'fair:%' and key <> 'fair:global'
  and last_at < now() - interval '30 days';
```

Do not delete keys that start with `dev:` (the old anonymous preview counters; they matter again
if you ever set `ALIMNE_FREE_MODE=0`).

---

## 7. Where the words live (so they stay true)

| Place | Says |
|---|---|
| `/terms`, `/privacy` (`app.py`) | Free, fair use, limits may change, no unlimited promise, legacy subscribers can manage or cancel in the app, Stripe for them, usage counters disclosed. Follow `ALIMNE_FREE_MODE`. |
| `/s/<slug>` shared guide and its 404 | "Make your own study guide - free" growth call to action with UTM tags, English and Arabic. |
| `frontend/index.html` and `dist/index.html` | Title and meta tags for a free product. `dist/` is committed and Render does not build it, so both files must carry the same tags. |
| `frontend/public/og.png` and `dist/og.png` | The social preview picture. The meta tags point at `og.png?v=free` so WhatsApp, X and LinkedIn refetch it instead of showing the cached old one. |
| `tests/test_copy_truth.py` | Fails on stale plan claims (free trial, 3 tokens, Pro price, 30 guides), on "unlimited", on storage claims, on a changed privacy promise, and on the old `og.png` coming back. |

Rule: if you change the limits or the counters, update `/privacy` (it describes the counters)
and run `python -m pytest -q`.

---

## 8. Launch checklist for HK

Do these before announcing, in this order.

**Groq (the bill)**
- [ ] In the Groq console set a monthly **spend limit** and a **spend alert** (a number you can
      lose without pain). This is the backstop behind every cap in this file.
- [ ] Confirm `GROQ_TPM_LIMIT` on Render matches your Groq tier.
- [ ] Note today's cost-per-guide after the first 50 guides; use it to size `FAIR_GLOBAL_DAILY`.

**Supabase**
- [ ] Run the RPC check from section 6. All three (`anon_consume`, `anon_remaining`,
      `anon_refund`) must exist, or fair use fails open and does nothing.
- [ ] **Custom SMTP for email sign-ups.** Supabase's built-in email sender is for testing only
      (very low hourly limit, not meant for real users). Without your own SMTP, sign-up
      confirmation emails stall exactly when a class signs up together. Set up SMTP (for example
      Resend) on a verified `alimne.app` sender (SPF and DKIM), raise the Auth email rate limit,
      and send yourself a test sign-up from a Gmail and a university address. Make the
      confirm-email template read well in English and Arabic.
- [ ] Decide on email confirmation: keeping it ON makes fake accounts (and so 40/day quota
      farming) harder; turning it OFF removes a step for students. Google sign-in is the
      lowest-friction path either way. Start with it ON and revisit with real data.
- [ ] Auth > URL configuration: Site URL `https://alimne.app`, redirect URL allow-list includes it.

**Google sign-in (OAuth)**
- [ ] Google Cloud console > OAuth consent screen: app name Alimne, support email, authorised
      domain `alimne.app`, privacy policy `https://alimne.app/privacy`, terms
      `https://alimne.app/terms`.
- [ ] Publishing status **In production**. In "Testing" only listed test users can sign in and
      their sessions expire after a week. Keep the scopes to the basics (email, profile, openid)
      so no Google verification review is needed.
- [ ] The OAuth client's authorised redirect URI is the Supabase callback
      (`https://<project-ref>.supabase.co/auth/v1/callback`); the client id and secret are
      entered under Supabase > Auth > Providers > Google.
- [ ] Sign in with a brand-new Google account and confirm you land on `https://alimne.app`.

**Render**
- [ ] Make the live start command and `render.yaml` agree, with **`--threads 8`** (section 4),
      `--workers 1`. Do not launch on 4 threads.
- [ ] Add alerts for failed deploys and out-of-memory events. Check `healthCheckPath` is
      `/healthz`.
- [ ] Know the upgrade path: bigger plan (scale up), never more instances or workers (section 4).
      Check the current plan sizes and prices in the dashboard.
- [ ] Any variable change restarts the service and drops in-memory guides: do the launch
      changes together, off-peak.

**Legacy subscribers (your call)**
- [ ] Decide what to do with people who already pay: let them run out, cancel their
      subscriptions in Stripe and tell them, or refund. The portal and webhook keep working
      either way, and `/terms` already tells them they can manage or cancel in the app.

**Smoke test after the deploy**
- [ ] `curl -s https://alimne.app/api/config` shows `"free_mode": true` and the `fair_use`
      numbers.
- [ ] Generate a guide with no sign-in. No token message anywhere.
- [ ] Sign in and generate again. No token or upgrade prompt, and the account allowance is the
      higher one.
- [ ] Open `/terms`, `/privacy` and a shared guide `/s/<slug>`: free wording, English and Arabic.
- [ ] (Optional) set `FAIR_DEVICE_DAILY=2` for a test, hit the cap and read the sign-in message,
      then set it back.
- [ ] Paste `https://alimne.app` into WhatsApp and LinkedIn: the preview shows "Free for
      everyone". (The picture URL changed, so old caches are bypassed.)
- [ ] Update bios and pinned posts on the Alimne social accounts that still mention tokens or a
      price.

---

## 9. Not covered here

- The PDF footer ("Made with alimne.app - turn any lecture into a study guide") and the print
  and view pages make no pricing claim and were left alone.
- Numbers in the Arabic and English copy are deliberately absent ("daily limits", not "10 a
  day"): the caps are env knobs and will change, and the pages must not go stale when they do.
