# Alimne free mode

Alimne is **free for everyone**: no tokens, no credits, no paywall, no subscription upsell.
The AI (Groq) still costs money per guide and the server is small, so free is kept safe with
five things: the sign-in gate, fair-use daily caps, a global daily budget breaker, a generation
queue, and a per-minute rate limit. We say "free" and "fair use". We never say "unlimited".

**The sign-in gate (owner's rule, 2026-10-07):** a visitor may make **3 guides without an
account**. After those 3 they must **sign in (create a free account)** to make more. Signing in
is free and stays free; a signed-in user has the daily account allowance (`FAIR_USER_DAILY`).
The sample lecture stays free, uncounted and needs no account. Opening, downloading and restoring
guides that were already made never needs an account: only making a NEW guide is gated. So we
never say "no sign-up needed" on its own any more. The true sentence is "your first 3 guides
need no account" (section 3, "The sign-in gate").

The gate counts **browsers, not people** (the device is an id the page keeps in the browser), so
it is a strong nudge, not a wall: section 3, "What the gate can and cannot stop", says exactly
what it holds and how to tighten or loosen it.

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
| `ALIMNE_FREE_MODE` | `1` (on) | `0`, `false`, `no` or `off` (any case) brings the old token system back exactly (see section 2). Anything else, or unset, is on. |
| `ANON_FREE_USES` | `3` | The sign-in gate: guides an **anonymous device** (header `X-Device-Id`) may make before a free account is required. A **lifetime** allowance, not a daily one. `0` means an account is required from the very first guide (decided without the database, so it cannot fail open); the client and the legal pages then say "a free account is needed to make guides" and name no number. Blank, malformed or negative: `3`. |
| `ANON_USES_WINDOW_HOURS` | `87600` | The window the gate counter is read with (about 10 years, which is what makes the allowance a lifetime one). Set `24` and the 3 guides come back every day. `0`, negative or malformed: the default. Capped at `876000` (100 years): a window the database cannot compute would make the counter error, and an erroring counter fails open. |
| `FAIR_ANON_IP_DAILY` | `10` | Anonymous guides per **IP address** per 24 h window, **across all devices**. It is the only thing that bounds a visitor who gets a fresh device id (a private window, cleared site data, another browser): every new id has its own 3, the network stops at 10 a day. Lower is tighter and asks more people on shared networks to sign in; higher is looser (section 3, "What the gate can and cannot stop"). `0` means no anonymous guides at all, from anywhere (for that, prefer `ANON_FREE_USES=0`: its message says so plainly). Signed-in users are not counted here. It was `30` in the first version of the gate. |
| `FAIR_DEVICE_DAILY` | `10` | **Retired.** It used to be the anonymous allowance per device per day; the sign-in gate replaced it. Still read, but it grants nothing in free mode (it only appears in the token-mode `/api/config` payload, unchanged). |
| `FAIR_IP_DAILY` | `250` | Guides per **IP address** (an IPv6 address counts as its whole /64) per 24 h window. Generous on purpose: campuses, hostels and mobile carriers put hundreds of students behind one IP. |
| `FAIR_USER_DAILY` | `40` | Guides per **signed-in user** (user id) per 24 h window. |
| `FAIR_GLOBAL_DAILY` | `2000` | Guides across **all users** per 24 h window. This is the budget breaker. |
| `FAIR_ANON_SHARE_PCT` | `60` | The share (1 to 100) of `FAIR_GLOBAL_DAILY` that **anonymous** visitors may use together. The rest is reserved for signed-in users, so anonymous traffic can never lock out the people the sign-up funnel is built for. `100` removes the reservation. |
| `FAIR_CHAT_DAILY` | `100` | Chat questions per **signed-in user** per 24 h window (`0` switches chat off). |
| `WEB_THREADS` | `4` | The gunicorn `--threads` value the service really runs with. The two knobs below are clamped so that running + waiting generations are always at most `WEB_THREADS - 1` (section 4). |
| `GEN_MAX_CONCURRENT` | `2` | Generations running at the same time, process-wide. |
| `GEN_MAX_WAITING` | `1` | Requests allowed to **wait** for a slot. Each waiter holds a web thread, so this is capped too. One more is answered `busy` at once. |
| `GEN_QUEUE_WAIT_S` | `45` | How long a waiting request waits for a free slot before giving up with `busy`. |
| `RATE_SUMMARIZE_PER_MIN` | `30` | Per-IP, per-minute limit on the generation endpoints (it used to be a hard-coded 5, which blocked a whole class sharing one IP). |
| `RATE_PRECHECK_PER_MIN` | `5` | Per-IP, per-minute limit for work that runs **before** a slot is taken and holds a web thread outside the generation gate: the YouTube duration probe (`/api/youtube`) and the server-side URL fetch (`/api/summarize-text` with a `url`). Never above `RATE_SUMMARIZE_PER_MIN`. |

Related settings that already existed and matter for cost: `GROQ_API_KEY`, `GROQ_MODEL`
(`openai/gpt-oss-120b` in `render.yaml`), `GROQ_TPM_LIMIT` (`200000` in `render.yaml`; the code
default is `7000`, so the variable must exist on Render).

**Changing any environment variable restarts the service on Render, and the job store is in
memory.** Every guide that is open in someone's browser (15-minute window) is lost on restart.
Change knobs off-peak when you can, and tell nobody to panic when you cannot.

---

## 2. Turning free mode off (rollback)

Set `ALIMNE_FREE_MODE=0` (or `false`, `no`, `off`, in any case) and redeploy/restart. The old
behaviour returns exactly: tokens are consumed and refunded, 402 `no_tokens` / `signin_for_more`
come back, Stripe checkout works again, signup token grants and the referral reward are promised
and awarded again. The sign-in gate, the fair-use counters, the chat meter, the demo cache and the
generation queue are all off in token mode (it has its own, older rule: 2 anonymous previews per
device, then 402 `signin_for_more`).

What follows the switch automatically:

- `/terms` and `/privacy` use the very same parsed value as the credit logic (one parser, the
  `FREE_MODE` constant). When free mode is off they describe the token plans again (Free plan /
  Pro plan); otherwise they say Alimne is free and state the account rule with the real
  `ANON_FREE_USES` number. The page can never contradict what the app is doing, whichever
  off-value you type. Covered by `tests/test_copy_truth.py`.

What does **not** follow (static files, they cannot read the environment):

- `frontend/index.html` / `dist/index.html` title and meta tags ("Free AI study guides ..."),
  and the social preview picture `og.png` ("Free for everyone - no credit card"). If you roll
  back for more than a day or two, restore the old copy by hand.

Never touched by free mode, in either direction: `/api/stripe/webhook` and
`/api/stripe/portal`. People who subscribed before the change can always manage or cancel.

Use the rollback for a real emergency only. For a cost spike the right tool is usually to
lower `FAIR_GLOBAL_DAILY`, `FAIR_ANON_IP_DAILY` or `ANON_FREE_USES` (section 5), which keeps
the product free and degrades gracefully.

---

## 3. How fair use works

**Counters.** Each generation (`/api/summarize-stream`, `/api/youtube`, `/api/summarize-text`,
non-demo) is charged against **every applicable counter**:

| Who | Counters charged, in this order |
|---|---|
| Anonymous visitor | `gate:dev:<device>` + `fair:anonip:<ip>` + `fair:ip:<ip>` + `fair:global:anon` + `fair:global` |
| Anonymous, no valid device id (a script, or a browser with storage blocked) | `gate:noid:<ip>` + `fair:anonip:<ip>` + `fair:ip:<ip>` + `fair:global:anon` + `fair:global` |
| Signed-in user | `fair:user:<user id>` + `fair:ip:<ip>` + `fair:global` |

**The sign-in gate.** `gate:dev:<device>` is the visitor's free guides: limit `ANON_FREE_USES`
(3), read with the long window `ANON_USES_WINDOW_HOURS` (about 10 years), so it does **not**
reset after a day. The 4th guide is refused with **401 `signin_required`**. A signed-in request
never touches a gate key and is never refused by it, whatever the device did before signing in.

- **No device id: 3 guides per IP per day.** A request without a valid `X-Device-Id` (a script, or
  a browser with storage switched off) has no device to count, so it is counted under
  `gate:noid:<ip>`: `ANON_FREE_USES` (3) guides **per IP address per 24 h**, shared by everyone
  on that IP who sends no id. Unlike the device allowance this one IS daily: it comes back the
  next day. Leaving the header out can therefore never dodge the gate, and those guides also count
  inside the per-IP cap of the next point. Its refusal says `reason: "network"`, because it is
  the network's allowance, not one person's.
- **A new device id: 10 guides per IP per day.** A new id gets a new 3 (see "What the gate can and
  cannot stop" below), so `fair:anonip:<ip>` caps anonymous guides per IP at `FAIR_ANON_IP_DAILY`
  (10) a day across all devices. When it is used up the answer is also `signin_required`, with
  `reason: "network"`: an account is the way forward, and accounts are not counted there.
- **The anonymous pool.** `fair:global:anon` is the anonymous slice of the global budget
  (`FAIR_ANON_SHARE_PCT`, 60% by default). Anonymous traffic can only ever use that slice, so the
  other 40% of `fair:global` is kept for signed-in users. When the slice is used up an anonymous
  visitor gets `signin_required` with `reason: "pool"`, which is true: signed-in users still have
  room.
- **A refusal never burns a free guide.** If a later counter refuses (the network, the pool, the
  global budget), the gate unit that was taken first is given back with the others. A visitor
  refused for the network or the pool still has their own 3.
- **What the client is told.** `/api/config` reports the allowance and what this **device** has
  left, and nothing about the network or the pool; the SSE `done` event of an anonymous guide
  carries `anon_remaining` (see "Config the client reads" below). A refusal carries its `reason`.

**What the gate can and cannot stop.** Read this before trusting the number 3. The "device" is not
a person and not a machine: it is a random id the page keeps in the browser's storage. So:

- It **does** stop the ordinary visitor: same browser, 3 guides, then the sign-in dialog. That is
  nearly everyone, and it is what the sign-up funnel is built on.
- It does **not** stop someone who resets the browser. A private window, "clear site data",
  another browser or another device is a new id with 3 more guides. Nothing on the server can
  tell that apart from a new student.
- What bounds that is the network, not the device: `FAIR_ANON_IP_DAILY`, **10 anonymous guides per
  IP per day** whatever the ids. On one connection a determined person gets at most 10 a day
  without an account (3 + 3 + 3 + 1), not the 30 the first version allowed.
- It does **not** stop someone who also changes network (mobile data, a VPN, another Wi-Fi): a new
  IP has its own 10. The last bound is then the anonymous slice of the global budget
  (`FAIR_ANON_SHARE_PCT` of `FAIR_GLOBAL_DAILY`, 1200 guides a day by default). That protects the
  bill and the signed-in users. It does not enforce the rule.
- The price of the lower cap is paid by **shared networks**. A campus, a hostel or a mobile
  carrier can put hundreds of students behind one IP, and they share those 10 anonymous guides a
  day. After the 10th, the next student on that network is asked to sign in before using any of
  their own 3. That is accepted on purpose (the goal is sign-ups and an account is free), the
  message they see is the true one for that case, and their own 3 are not used up: they are
  still there on another network or another day.
- A hard, per-person limit exists only with an account. That is exactly what the gate asks for.

**Tightening and loosening it.** All of these are plain environment variables (a change restarts
the service, section 1):

| To | Set | What it does |
|---|---|---|
| close the reset loophole on one network | `FAIR_ANON_IP_DAILY=3` | One browser's worth per IP per day: a private window buys nothing on the same connection. Every shared network reaches the sign-in dialog after 3 anonymous guides a day in total. |
| ask for an account from the first guide | `ANON_FREE_USES=0` | No anonymous guides at all; the sample lecture still works. Client, `/terms` and the refusal say "a free account is needed", with no number. |
| give fewer free guides | `ANON_FREE_USES=1` or `2` | The same gate, sooner. Keep `FAIR_ANON_IP_DAILY` at a few times this number. |
| be gentler on campuses and carriers | `FAIR_ANON_IP_DAILY=30` or more | More students per shared IP can try before signing in. The reset loophole widens by the same amount (30 = ten browser resets a day). |
| cap what anonymous visitors can cost in total | a lower `FAIR_ANON_SHARE_PCT` | A smaller anonymous slice of the daily budget; more is reserved for accounts. |

How to choose: count the refusal lines by reason (section 6). Lines ending `reason=network` with
sign-ups following mean the cap is doing its job. Many `reason=network` lines from a place where a
real class is working, and few sign-ups, mean the cap is too low for that audience: raise it.

For an IPv6 client `<ip>` is its /64, not the single address (rotating inside a /64 buys
nothing). The counter lookups of one request share a 3-second time budget; if the database is
slow the rest fail open instead of pinning a web thread.

**The demo.** "Try a sample" is never gated: it needs no account, takes none of the visitor's 3
free guides and works even with `ANON_FREE_USES=0`. It runs on a fixed lecture, so it is made
**once per language** and cached in memory for 6 hours. Every later demo is a fresh, independent job (own 15-minute life,
own "Delete now") served from the cache at **zero AI cost and zero fair-use units**. The one real
run per language takes one unit from `fair:global`, so the breaker bounds it, and it is refused
with `busy_today` when the breaker has tripped and nothing is cached. A failed or partial run is
never cached. A restart clears the cache (the next demo makes it again).

**Chat.** A chat question is an AI call too. Per signed-in user: at most 10 per minute and
`FAIR_CHAT_DAILY` per 24 h window (counter `fair:chat:user:<user id>`, 429 `fair_use_user`).
Chat also stops with `busy_today` once the global budget is used up (it reads `fair:global`, it
does not spend from it). A failed question gives its unit back.

**Storage.** The counters reuse the existing durable RPCs `anon_consume(p_key, p_limit,
p_window_hours)`, `anon_remaining` and `anon_refund(p_key)` (migrations 009 and 012) with the
key prefixes above (`fair:*` and `gate:*`). Rows live in `public.anon_usage`. No new migration is
needed, for the gate either.

**Windows.** A `fair:*` counter's 24 h window starts at its first use and resets 24 h later (that
is how `anon_consume` works). It is a fixed window per key, not a sliding one. For `fair:global`
this means the daily budget resets at an arbitrary hour, not at midnight. The gate counter
`gate:dev:*` works the same way with the long window, so in practice it never resets. The window
is an argument of every call, not something stored in the row: changing `ANON_USES_WINDOW_HOURS`
takes effect on the next request.

**Order.** Validation first (a bad file never costs anyone a slot or a count), then a check that
there is a slot or a seat in line (a full house answers `busy` before anything is charged and
before the YouTube probe or URL fetch), then charge all counters, then queue for a generation
slot. If one counter is exhausted, the ones already taken are rolled back (`anon_refund`) and the
request is refused.

**Refunds.** The counters, the visitor's free guide included, are given back exactly once (the
existing single-owner charge/refund machinery) when the **server** fails or the visitor leaves
**before any paid AI work started**:
validation after the charge, `busy`, a failed or hollow guide, the visitor closing the page while
queued or while the file is still being read. Once the first paid AI call (the overview pass, or
the Whisper transcription) has started, the units are **spent**: closing the connection later does
not refund them. Otherwise a script could run full-cost generations for free by dropping the
socket just before the last event, with every counter, the gate and the global breaker included,
still at zero. A server-side failure after paid work (an error, a guide with no notes) still refunds,
because the visitor did nothing wrong and the failure cannot be chosen from outside.

**Fail open.** If the RPC is missing or errors, the request is allowed and the problem is logged.
A database hiccup must never block a real student. The flip side, and a launch risk: **if the
RPCs are missing the caps silently do not apply, and neither does the sign-in gate** (anonymous
visitors would simply keep going). Verify them before launch (section 8) and watch the log for
`failing open`. The one exception is `ANON_FREE_USES=0`: that refusal is decided without the
database.

**Refusals** (JSON `{error, code, retry_after_s?}`):

| HTTP | `code` | Meaning |
|---|---|---|
| 401 | `signin_required` | **The sign-in gate.** A free account is needed, and the body says why in `reason`: `device` (this anonymous visitor used their own free guides, `gate:dev:*`), `network` (this IP used its anonymous allowance for today: `fair:anonip:*`, or `gate:noid:*` for a request with no device id) or `pool` (the anonymous slice of the global budget is used up, `fair:global:anon`). The body also carries `free_uses` (the `ANON_FREE_USES` number). Each reason has its own text (below). This is the signup funnel. |
| 429 | `fair_use_ip` | This IP used its daily allowance, signed-in and anonymous together (shared networks can hit it). |
| 429 | `fair_use_user` | This signed-in account used its daily allowance (guides, or chat questions). |
| 503 | `busy_today` | The global daily budget is used up. Everyone (and chat) is refused until the window resets. |
| 503 | `busy` | **Before the stream:** no free slot and no seat in line. Nothing was charged. The JSON carries `retry_after_s`. |
| 200 | `busy` | **Inside the stream:** the request waited in line and `GEN_QUEUE_WAIT_S` ran out. It arrives as an SSE `error` event on an HTTP 200 response, so it never shows in Render's 5xx metric. Its units are refunded. |
| 429 | (rate limit) | More than `RATE_SUMMARIZE_PER_MIN` requests from one IP in a minute (`RATE_PRECHECK_PER_MIN` for the YouTube probe and URL fetch; 10 a minute per user for chat). |

**The three sign-in texts** (`_signin_required_text` in `app.py`; English shown, the Arabic says the
same, the language follows the request):

| `reason` | Text |
|---|---|
| `device` | "You've used your 3 free guides. Create a free account to keep going - it's still free." (the real number; "your free guide" for 1; with `ANON_FREE_USES=0`: "Create a free account to make study guides - it's free.") |
| `network` | "Today's free guides without an account are used up on your network. Create a free account to keep going - it's still free." |
| `pool` | "Today's free guides without an account are used up. Create a free account to keep going - it's still free." |

Only `device` says "you've used your...": a visitor refused for the network or the pool may have
made nothing at all, and was wrongly told so before `reason` existed. All three end with the same
call to action. The log line names the reason too:
`fair-use refusal code=signin_required status=401 reason=network`.

**What the shipped client does with it.** The React client mirrors the **device** counter only
(`anon_remaining` from `/api/config`, then from every `done` event). When that reaches 0 it does
**not send** the request: it opens the sign-in dialog itself, with the `device` text. So in normal
use the server never receives a 4th request from that browser and writes **no** refusal line for
it. A `reason=device` line in the log comes from a script, an older cached client, a second tab,
or a counter the client could not read. The client never blocks for `network` or `pool` (it is
not told those numbers): such a request is sent, the server refuses it, and the dialog shows the
text for the server's reason. The device counter is left alone then, so the nav still says "3 free
guides left", which is true. A browser that keeps no device id is never blocked locally either
(its number is its network's): the server answers. An older cached client does not know `reason`
and shows the `device` text for all three until it loads the new bundle.

No `402` is returned in free mode. `fair_use_device` (429) is retired: the server never sends it
any more, `signin_required` replaced it (the client still understands the old code). The 401 is
not an auth error: its code is never `auth_required`, `token_expired` or `token_invalid`, and a
request that carries a bad token is still answered by the auth check first. An older cached
client treats any 401 from an anonymous request as "open the sign-in dialog", which is the right
outcome.

SSE `done` events keep their shape; `tokens_remaining` may be missing or null and the client
tolerates both. For an **anonymous** guide in free mode `done` adds `anon_remaining`: the free
guides this device has left (2, 1, 0). It is best effort: it is left out when the counter could
not be read, for signed-in users, for the demo and in token mode.

**Queue.** A process-wide `BoundedSemaphore` of `min(GEN_MAX_CONCURRENT, WEB_THREADS - 1)` slots
wraps the generation work. When all slots are busy the request may take one of the (at most
`GEN_MAX_WAITING`) seats in line and waits up to `GEN_QUEUE_WAIT_S`, sending SSE events
`{"step":"queued","position":<n>,"msg":"..."}` about every 3 s so the student sees a place in
line. The line is strictly first come, first served: a later arrival never passes an earlier
one, so the place the student is told is the place they get. The slot is released in a `finally`
on every path: done, error, client disconnect.

**Config the client reads.** In free mode `/api/config` returns `free_mode: true`,
`anon_free_limit` and `signin_after` (both the `ANON_FREE_USES` number, `0` included),
`anon_remaining` (the free guides this **device** has left: a read-only lookup of its gate counter
that never blocks the page, falling back to the full allowance when the database is slow or down;
it never reflects the network cap or the anonymous pool) and
`fair_use {anon_free_uses, user_daily, device_daily}`. `device_daily` is kept only so an older
cached client does not break; it equals `anon_free_uses`. `/api/auth/me` adds `free_mode: true`.
In free mode `/api/stripe/checkout` answers `410 free_now` and creates no Stripe session.

**Google sign-in keeps what was waiting (client only).** Google sign-in is a full-page redirect,
and a page that leaves forgets what it holds: a file chosen behind the gate, or pasted text, used
to be gone when the visitor came back signed in. Now, just before the page leaves for Google, the
client puts the items that were not generated yet (the File objects, pasted text, links) in the
browser's own IndexedDB. Nothing is uploaded early: an item is sent when the visitor taps
Generate, exactly as before. On the next page load the items are back in the list, ready to
generate, with the notice "You're signed in. Your file is ready - tap Generate." (they also come
back if the visitor cancels at Google and returns without an account). The copy:

- is capped at 3 files and about 60 MB in all;
- belongs to the tab that made it (a random claim in sessionStorage): no other tab can bring it
  back, including one opened later by someone else at the same computer;
- is deleted in the same step that reads it, deleted on sign-out, and never used once it is more
  than 30 minutes old (the next page load in that browser deletes it);
- is skipped silently where IndexedDB or sessionStorage is missing or blocked (some private modes):
  the page then behaves as it did before, and the file has to be chosen again.

The OAuth call and the auth flow (implicit) are unchanged. Email and password sign-in does not
reload the page, so nothing needs keeping there. Token mode (`ALIMNE_FREE_MODE=0`) makes no such
copy. The privacy wording follows: section 7.

---

## 4. Capacity: what the server can really carry

The current Render service: **1 gunicorn worker, 0.5 CPU, 512 MB RAM, 1 instance**, Python 3.14.
The live start command uses `--threads 4`; `render.yaml` says `--threads 8` (see drift note below).
Guides live in an in-memory job store for 15 minutes.

- **Every generation holds a web thread for its whole run (the stream), and so does a request
  that is waiting in line.** With 4 threads the code therefore allows at most 3 generation
  requests in total: **2 running + 1 waiting** (the defaults). The fourth is answered `busy` at
  once, with nothing charged, and **at least one thread is always free** for `/healthz`,
  `/api/config` and the static files. This is enforced in code, not by convention: whatever you
  set, `min(GEN_MAX_CONCURRENT, WEB_THREADS - 1)` slots plus the seats in line stay at most
  `WEB_THREADS - 1`. (Before this limit, 3 running + 1 waiting took all 4 threads, `/healthz` sat
  in gunicorn's backlog behind them, and Render restarted the service, wiping every in-memory
  guide.) Covered by `tests/test_free_mode.py`, section J.
- **The pre-slot work.** The YouTube duration probe and the server-side URL fetch run before a
  slot is taken, so the gate does not count them. They are bounded by their own per-IP limit
  (`RATE_PRECHECK_PER_MIN`, 5 a minute) and by the full-house check, and each network call has
  its own timeout, but there is no total deadline on a slow YouTube. Watch for it in the first
  week. (The YouTube probe also runs before the sign-in gate is checked, so a visitor who is past
  their free guides waits for the probe before being asked to sign in.)
- **Peak-hour arithmetic.** Throughput is roughly `slots / seconds-per-guide`. Example: if a guide
  takes about 60 s, 2 slots serve about 120 guides an hour. `FAIR_GLOBAL_DAILY=2000` looks
  comfortable, but traffic is peaky (exam season, evenings): in practice the slots, not the
  budget, are the limit at peak, and students see the queue line or `busy` first. That is the
  safe failure. Measure the real seconds-per-guide in the first week and revisit. To serve more
  you need more threads, not more knobs (next point).
- **Raising the numbers: threads first.** The two generation knobs only help when the web-thread
  count really goes up. On a bigger plan with `--threads 8`, set the environment variables
  `WEB_THREADS=8`, `GEN_MAX_CONCURRENT=4` and `GEN_MAX_WAITING=3` together (4 + 3 = 7 = threads
  minus one). If you raise only the knobs, the code clamps them back to what 4 threads can carry.
- **Groq's own limit.** Calls are paced under `GROQ_TPM_LIMIT` tokens per minute across the whole
  process. If the pacer is the bottleneck, more slots will not help.
- **Memory.** Each in-flight request holds its upload in RAM (up to 50 MB; typical slide decks are
  far smaller). 8 threads on 512 MB is workable but not roomy.

**Drift to resolve before launch:** the Render dashboard start command (`--threads 4`) and
`render.yaml` (`--threads 8`) disagree. The dashboard wins in production. Make them match, on
purpose, and set `WEB_THREADS` to the same number (the default, 4, matches the live service).
Keep the code comments honest (`_REHYDRATE_SLOTS` is written for 8).

**Upgrade path: scale UP, never out.** The job store and the Groq pacer are per process:

- Do **not** add instances and do **not** raise `--workers` above 1. A guide created on one
  instance cannot be found by the other (students would get "guide expired" at random).
- Move to a bigger Render plan (more CPU and RAM) and raise `--threads`, `WEB_THREADS`,
  `GEN_MAX_CONCURRENT` and `GEN_MAX_WAITING` together, keeping at least one thread free (the code
  insists on it).
- Only when one big instance is not enough: move the job store to shared storage (Redis or the
  database) first, then scale out.

---

## 5. Cost-control levers (cheapest and gentlest first)

1. **`ANON_FREE_USES`** (free guides before sign-in) and **`FAIR_ANON_IP_DAILY`** (anonymous
   guides per IP a day, 10). Lowering them pushes more visitors to sign in; `ANON_FREE_USES=0` asks
   for an account from the first guide (the sample lecture still works without one). The table in
   section 3 ("Tightening and loosening it") says what each setting costs. If you change
   `ANON_FREE_USES`, check the static copy that names the number (section 7).
2. **`FAIR_USER_DAILY`** and **`FAIR_IP_DAILY`**.
3. **`FAIR_GLOBAL_DAILY`**, the breaker. Every guide, and the one real demo run per language,
   takes a unit from it, so guide spend is at most `FAIR_GLOBAL_DAILY x cost-per-guide` a day.
   Two things sit beside that number, both small: chat questions (each far cheaper than a guide;
   they stop when the breaker trips, and each user is held to `FAIR_CHAT_DAILY` a day) and the
   demo (two builds per 6 hours at most). Read cost-per-guide from the Groq dashboard after the
   first days (tokens per guide times price), then set the number so the ceiling is a bill you
   are happy to pay. `FAIR_ANON_SHARE_PCT` decides how much of it anonymous visitors can use.
4. **`GEN_MAX_CONCURRENT` / `GEN_MAX_WAITING` / `GEN_QUEUE_WAIT_S`**: slow the spend rate instead
   of refusing (but never above what `WEB_THREADS` can carry, section 4).
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
| Render > Logs | Search for these exact phrases. `failing open` (a counter could not be read: the caps are not applying), `fair-use refusal code=` (one line for every `signin_required` / `fair_use_*` / `busy_today` refusal the **server** gave, with the code; a `signin_required` line ends with `reason=device`, `reason=network` or `reason=pool`), `generation busy` (one line for every `busy`, whether it came before the stream as a 503 or inside it), `passed 80% of its daily limit` and `is used up` (a global pool: the cue to look at the Groq bill), `time budget` (the database was slow), `client left after the AI work started` (units kept), and Groq 429s | Any `failing open` line at launch; many `generation busy` lines in one hour; the `80%` line before evening |
| Groq console | Requests and tokens per day, 429s, spend against your limit | Spend trending past the limit you set; many 429s (raise the Groq tier or lower concurrency) |
| Supabase > Auth | Signups per day, provider mix (Google vs email), email errors and rate-limit errors in Auth logs | Signups fail or confirmation emails do not arrive (section 8, custom SMTP) |
| Supabase > SQL | The queries below | `fair:global` near its limit before evening; one device or IP far above the rest |
| `/admin` (existing dashboard) | Usage events and visit stats, if migrations 008 and 011 are applied | Guides per day versus visits (conversion) |
| The funnel | **`/admin`**: the sign-up funnel there (visits, anonymous guides, devices at the sign-in gate, new accounts) and sign-ups per day. On a build of `/admin` without the funnel section, read Visits, Generations (anon versus signed-in) and "New this week", and run the last query below for the devices at the gate. **Do not count `signin_required` log lines for this.** The client opens the sign-in dialog without sending a request when a device has no guides left (section 3, "What the shipped client does with it"), so most visitors who meet the gate never produce a log line. | Many devices at the gate and few new accounts: the sign-in prompt is not converting, or sign-up itself is broken (confirmation emails, Google OAuth: section 8) |
| Which limit people hit | The `reason=` at the end of the `signin_required` log lines. These ARE all logged: the client never blocks for the network or the pool. | Many `reason=network` lines where real classes work and few sign-ups: raise `FAIR_ANON_IP_DAILY` (section 3). Any `reason=pool` line: the anonymous slice ran out, look at `FAIR_ANON_SHARE_PCT` and the Groq bill |

Read-only queries for the Supabase SQL editor:

```sql
-- are the RPCs there? (must return 3 rows; if not, the caps do not apply)
select proname from pg_proc where proname in ('anon_consume','anon_remaining','anon_refund');

-- the global budget right now (the whole budget, then the anonymous slice of it)
select key, count, window_start, last_at from public.anon_usage
where key in ('fair:global', 'fair:global:anon');

-- heaviest IPs / users / chat users in the current windows
select key, count, last_at from public.anon_usage
where key like 'fair:anonip:%' or key like 'fair:ip:%' or key like 'fair:user:%' or key like 'fair:chat:%'
order by count desc limit 20;

-- the sign-in gate: how many devices have started, and how many have used all their free guides
-- (replace 3 with your ANON_FREE_USES)
select count(*) as devices, count(*) filter (where count >= 3) as at_the_gate
from public.anon_usage where key like 'gate:dev:%';
```

Housekeeping (optional, run by hand now and then): counters are never purged automatically. Old
`fair:` rows hold only a count and timestamps, but there is no reason to keep them forever (the
privacy page says old counters may be deleted at any time). The query below only touches `fair:`
rows, on purpose: **do not delete `gate:` rows.** A deleted `gate:dev:` row hands that device its
free guides back. (The `fair:dev:` rows left over from before the gate are unused and are cleaned
up by the same query.)

```sql
delete from public.anon_usage
where key like 'fair:%' and key not in ('fair:global', 'fair:global:anon')
  and last_at < now() - interval '30 days';
```

Do not delete keys that start with `dev:` (the old anonymous preview counters; they matter again
if you ever set `ALIMNE_FREE_MODE=0`).

---

## 7. Where the words live (so they stay true)

| Place | Says |
|---|---|
| `/terms`, `/privacy` (`app.py`) | Free; your first 3 study guides need no account, after that a free account is required (the number is the real `ANON_FREE_USES`, never typed in); fair-use daily limits apply to accounts; limits may change; no unlimited promise; legacy subscribers can manage or cancel in the app, Stripe for them; usage counters disclosed, including that the device counter is not a daily one. Follow `ALIMNE_FREE_MODE`. |
| The sign-in refusal (`_signin_required_text` in `app.py`) | Three texts, one per `reason` (section 3, "The three sign-in texts"), English and Arabic, all ending "Create a free account to keep going - it's still free." The `device` one carries the real number (singular and zero forms included). |
| The sign-in dialog and the held item (`signinRequired`, `signinNetwork`, `signinPool` in `frontend/src/App_dev.jsx`) | The same three texts, picked by the server's `reason`. `tests/test_signin_gate.py` (section 14) fails if client and server stop saying the same thing. |
| The short privacy line under the upload box (`privacy` in `App_dev.jsx`), the in-app Terms bullet (`TERMS_STASH`) and `/privacy` ("Signing in") | What the browser keeps for the Google sign-in round trip: in the visitor's own browser only, not uploaded before Generate, deleted when it is restored or on sign-out, never used after 30 minutes. Free mode only; token mode keeps its old line. If the client's behaviour changes (`signinStash` in `App_dev.jsx`), change all three. |
| In-app Terms (`TERMS_*` in `frontend/src/App_dev.jsx`) | The same promises as `/terms` and `/privacy`, in English and Arabic, including the opt-in sharing and the usage counters. `tests/test_free_mode_client.py` checks both languages say the same things and scans the Arabic copy for token, plan, price and "unlimited" claims. |
| `/s/<slug>` shared guide and its 404 | "Make your own study guide - free" growth call to action with UTM tags, English and Arabic. |
| `frontend/index.html` and `dist/index.html` | Title and meta tags for a free product. `dist/` is committed and Render does not build it, so both files must carry the same tags. |
| `frontend/public/og.png` and `dist/og.png` | The social preview picture. The meta tags point at `og.png?v=free` so WhatsApp, X and LinkedIn refetch it instead of showing the cached old one. |
| `tests/test_copy_truth.py` | Fails on stale plan claims (free trial, 3 tokens, Pro price, 30 guides), on "unlimited", on an unqualified "no sign-up / no account needed" claim on the server-rendered pages, on storage claims, on a changed privacy promise, and on the old `og.png` coming back. |
| `tests/test_signin_gate.py` | The gate itself: 3 guides then 401, the lifetime window, the counters and their order, the per-IP cap (10), refunds, fail open, the demo, `/api/config`, the `reason` and its three texts, client and server wording in step, token mode untouched, the knobs. |
| `tests/test_free_mode_client.py` and `frontend/scripts/verify-free-mode.mjs` | The client: the counter, no request at 0 left, the reasons, `ANON_FREE_USES=0`, and the sign-in round trip (the node script drives the real helper against an in-memory IndexedDB). |

Rule: if you change the limits or the counters, update `/privacy` (it describes the counters)
and run `python -m pytest -q`.

Rule for the number: the server-rendered pages and the refusal read `ANON_FREE_USES`, so they
follow the knob by themselves. The **static** client copy does not (the React strings read
`/api/config`, but `index.html` meta tags and `og.png` cannot). If you change `ANON_FREE_USES`,
check every place that says "3" by hand, and never ship "no sign-up needed" without "for your
first 3 guides". With `ANON_FREE_USES=0` the React copy switches by itself to "a free account is
needed to make guides". One thing it cannot do: before `/api/config` has answered (and if it never
answers) the client shows its built-in default, 3, so with any other value a visitor can see
"first 3 guides" for a moment on first paint. The server still enforces the real number.

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
- [ ] **Custom SMTP for email sign-ups. This is a blocker now:** after 3 guides a visitor MUST
      sign up to go on, so a sign-up that does not work is a dead end. Supabase's built-in email
      sender is for testing only
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
- [ ] Make the live start command and `render.yaml` agree (today the dashboard says
      `--threads 4` and `render.yaml` says `--threads 8`), always with `--workers 1`, and set
      the `WEB_THREADS` variable to the same number. On 4 threads the defaults are safe (2
      generations running + 1 waiting, one thread always free). On 8 threads also set
      `GEN_MAX_CONCURRENT=4` and `GEN_MAX_WAITING=3` (section 4).
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
- [ ] `curl -s https://alimne.app/api/config` also shows `"signin_after": 3` and
      `"anon_free_limit": 3`.
- [ ] In a fresh private window make 3 guides with no sign-in. No token message anywhere, and the
      counter in the top bar counts down ("2 free guides left", "1 free guide left", then "Sign in
      to continue - free"). Try a 4th: the page opens "Create your account" with "You've used your
      3 free guides. Create a free account to keep going - it's still free." It does this
      **without sending a request**: nothing new appears in the browser's Network tab and no
      refusal line appears in the logs. That is the shipped behaviour, not a fault. The 3 guides
      you made still open and download.
- [ ] The Google round trip: in that window choose a file but do not generate it, tap the sign-in
      prompt, "Continue with Google", and finish signing in. Back on Alimne the file is in the
      list again with "You're signed in. Your file is ready - tap Generate." (If the browser blocks
      IndexedDB the file is not kept and has to be chosen again: the old behaviour, not an error.)
- [ ] (Optional, it makes 3 real guides.) The server's own gate, without the client: run this 4
      times from a terminal, with a few hundred words of text in place of the dots. The first 3
      stream a guide, the 4th answers HTTP 401 with `"code":"signin_required","reason":"device"`
      and the log shows `fair-use refusal code=signin_required status=401 reason=device`.
      `curl -s -X POST https://alimne.app/api/summarize-text -H "Content-Type: application/json" -H "X-Device-Id: smoke-test-0001" -d "{\"text\":\"...\"}"`
- [ ] "Try a sample" still works in that same window, with no account.
- [ ] Sign in and generate again. No token or upgrade prompt, no sign-in prompt, and the account
      allowance is the daily one.
- [ ] Open `/terms`, `/privacy` and a shared guide `/s/<slug>`: free wording, English and Arabic.
- [ ] (Optional) set `ANON_FREE_USES=1` for a test, make one guide, read the sign-in message on
      the second, then set it back. With `ANON_FREE_USES=0` the page says "A free account is needed
      to make guides" and the counter shows "Sign in to continue - free" from the start. (Each
      change restarts the service.)
- [ ] Tap "Try a sample" twice: the second one appears instantly (served from the cache) and
      the logs show no second AI run.
- [ ] Look at Render > Logs for `failing open` (there should be none). The `fair-use refusal
      code=` and `generation busy` lines only appear when the server itself refuses, so an empty
      search after a normal smoke test is expected (see the 4th-guide step above). For the funnel
      use `/admin` (section 6).
- [ ] Paste `https://alimne.app` into WhatsApp and LinkedIn: the preview shows "Free for
      everyone". (The picture URL changed, so old caches are bypassed.)
- [ ] Update bios and pinned posts on the Alimne social accounts that still mention tokens or a
      price.

---

## 9. Not covered here

- The PDF footer ("Made with alimne.app - turn any lecture into a study guide") and the print
  and view pages make no pricing claim and were left alone.
- The daily caps are deliberately absent from the Arabic and English copy ("daily limits", not
  "40 a day"): they are env knobs and will change, and the pages must not go stale when they do.
  The one number that does appear is the free-guide allowance ("your first 3 guides"), because it
  is the product rule; the server-rendered pages take it from `ANON_FREE_USES` (section 7).

## 10. Known limits (so nobody is surprised)

- **The sign-in gate counts browsers, not people.** A visitor who clears the site data, opens a
  private window or switches browser gets a new id and 3 more guides. That is bounded per
  network, not per person: `FAIR_ANON_IP_DAILY` (10 anonymous guides per IP a day, across all
  devices), and beyond one network only by the anonymous slice of the global budget. A hard,
  per-person limit is only possible with an account, which is exactly what the gate asks for.
  Section 3 ("What the gate can and cannot stop") has the whole picture and the knobs.
- **A busy shared network meets the gate early.** `FAIR_ANON_IP_DAILY` is per IP: on a campus,
  a hostel or a carrier behind one address, once 10 anonymous guides were made in a day the next
  anonymous visitor is asked to sign in before using their own 3 (they are told it is the
  network, and their 3 are not used up). Signed-in users are not affected. Raise the knob if the
  `reason=network` log lines show this happening to real classes without sign-ups following.
- **A request with no device id gets 3 guides per IP per day.** That is a script, or a browser
  with storage switched off (the normal client always sends an id). It is a daily allowance, not
  a lifetime one: the 3 come back the next day, and they are shared with everybody else on that
  IP who sends no id.
- **"Create a free account to keep going" assumes there is room for accounts.** The gate is
  checked before the IP's total cap and the global budget. If one of those is also used up, a
  visitor who signs in after a `signin_required` is then told to try later (`fair_use_ip` or
  `busy_today`). With the default numbers that needs the daily breaker to have tripped, which
  the log announces ("is used up").
- **An older cached client does not know `reason`.** Until a browser loads the new bundle it
  shows the `device` text ("You've used your 3 free guides") for a network or pool refusal too.
- **The file kept for Google sign-in has limits.** It works only where IndexedDB and
  sessionStorage do (not in some private modes: the file is then simply not kept, as before), for
  at most 3 files and about 60 MB, in the same tab, for 30 minutes. An email confirmation link
  opens a new tab: the file stays in the first tab, which becomes signed in too. If a visitor
  closes the tab while on Google's page, the copy stays in their own browser (it cannot be
  opened by another tab and is sent nowhere) until Alimne is next opened there, when a copy
  older than 30 minutes is deleted.
- **The gate fails open.** If the database cannot answer, anonymous visitors are let through
  (and the log says `failing open`). Section 3 explains why, and what to watch.
- **Everyone starts at 3 on the day the gate ships.** The gate uses new counter keys, so guides
  made before it (under the old daily device counter) are not counted against the 3.
- **Client IP trust.** The per-IP counters and rate limits use the address from the
  `CF-Connecting-IP` header when `CF_ORIGIN_SECRET` is not set (the existing behaviour: Render's
  own edge sits behind Cloudflare and stamps it). If the header ever reaches the app unreplaced,
  one client could pose as many IPs and the per-IP caps (not the global ones) would stop
  working, `FAIR_ANON_IP_DAILY` and the no-device-id allowance included: together with a rotating
  device id that is a way past the sign-in gate, bounded only by the anonymous slice of the
  global budget. Two things limit the damage: anonymous traffic as a whole is capped by the anonymous
  slice of the global budget, and the rate-limit table prunes expired entries so a flood of fake
  addresses cannot grow memory without end. It was left unchanged on purpose: if the header were
  distrusted without checking, every student would share one or two Cloudflare addresses and
  hit the per-IP cap together. **Check once on production** (the admin visitor log shows the
  address recorded for a request you send with a made-up `CF-Connecting-IP`). The DNS records
  are grey-cloud, so a Cloudflare rule cannot stamp `X-Origin-Verify`.
- **The YouTube probe has no total deadline.** Each network call has a timeout, and the
  per-IP limit and full-house check bound how often it runs, but one slow YouTube answer can
  still hold a web thread for a while.
- **Old `fair:` rows are never purged automatically.** Use the housekeeping query in section 6
  now and then. A full database makes the counters fail open, which the `failing open` log line
  makes visible.
- **A global counter is a fixed 24 h window**, so the budget can reset at an odd hour (section 3).
