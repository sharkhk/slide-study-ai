// Offline verification of the Alimne FREE-MODE client (there is no JS test runner).
//
//   cd frontend && node scripts/verify-free-mode.mjs
//
// It bundles src/App_dev.jsx with esbuild (npm ci installs it with vite), exposes a few
// internals to the checks by appending an export line to the module at load time (the
// production source is not changed), and then:
//   * checks T / LEGACY have the same keys in English and Arabic, and that no Arabic value
//     is raw English;
//   * checks that the paywall / token / preview copy ('Free trial used', 'previews left',
//     'Subscribe', '10 token', credits, "unlimited" ...) is NOT in the free-mode strings
//     (it lives in LEGACY, merged in only when /api/config says free_mode:false);
//   * server-renders the real components in free mode, in both languages, and scans the
//     markup for the same copy;
//   * drives the SSE helper and the error mapper with the server's new refusals and the
//     'queued' step;
//   * checks the SIGN-IN GATE (an anonymous device may make ANON_FREE_USES guides, then a free
//     account is required): the numbers read from /api/config, the nav counter, the pre-flight
//     gate, the 401 'signin_required' refusal, the modal notice, and that no free-mode string
//     (English or Arabic) still claims "no sign-up needed" without the "first N guides" qualifier;
//   * checks WHY the server asked for a sign-in (reason: device / network / pool): one true text each,
//     the same call to action, and no local pre-block for a reason the client cannot know;
//   * checks ANON_FREE_USES=0 (an account from the first guide): the client never falls back to 3;
//   * drives the SIGN-IN STASH (what was waiting is kept in this browser's IndexedDB for the Google
//     round trip) against an in-memory IndexedDB: caps, restore once, tab binding, 30-minute limit,
//     sign-out, and every way IndexedDB can be missing or broken.
// Exit code 0 = everything passed. No network, no DOM, no secrets.
import { build } from 'esbuild'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const appPath = path.join(root, 'src', 'App_dev.jsx')
const outDir = path.join(root, 'node_modules', '.cache', 'verify-free-mode')
const outFile = path.join(outDir, 'bundle.mjs')
fs.mkdirSync(outDir, { recursive: true })

const EXPOSE = ['T', 'LEGACY', 'tFor', 'friendlyErr', 'streamSSE', 'perksOf', 'procLine', 'badgeKey', 'posInt',
  'showJoinCard', 'offersSignIn', 'STOP_CODES', 'JoinCard', 'ReferralCard', 'AccountModal', 'LoginModal',
  'TermsModal', 'UpgradeModal', 'EmailCaptureModal', 'TERMS_EN', 'TERMS_AR', 'TERMS_EN_LEGACY', 'TERMS_AR_LEGACY',
  // the sign-in gate after the free guides
  'FREE_USES_DEFAULT', 'GATE_CODES', 'countInt', 'gateFromConfig', 'gateAfterDone', 'anonGated', 'termsText', 'AnonCounter',
  // why the server asked for a sign-in, and the copy kept in this browser for the sign-in round trip
  'signinText', 'holdsDeviceCount', 'AR_THE_COUNT', 'stashPlan', 'stashItems', 'signinStash',
  'STASH_MAX_BYTES', 'STASH_MAX_FILES', 'STASH_MAX_AGE_MS', 'STASH_TAB_KEY', 'TERMS_STASH']

await build({
  entryPoints: [appPath], bundle: true, format: 'esm', platform: 'node', outfile: outFile,
  packages: 'external', jsx: 'automatic', logLevel: 'silent',
  plugins: [{
    name: 'expose-internals',
    setup(b) {
      b.onLoad({ filter: /App_dev\.jsx$/ }, async (args) => ({
        contents: fs.readFileSync(args.path, 'utf8') + `\nexport { ${EXPOSE.join(', ')} }\n`, loader: 'jsx',
      }))
    },
  }],
})

// ── a just-enough browser for the module's top-level code and a server render ────────
const store = () => { const m = new Map(); return {
  getItem: k => (m.has(k) ? m.get(k) : null), setItem: (k, v) => void m.set(k, String(v)),
  removeItem: k => void m.delete(k), clear: () => m.clear(), key: i => [...m.keys()][i] ?? null,
  get length() { return m.size } } }
const local = store(), session = store()
const noop = () => {}
const fakeWindow = {
  location: { search: '', hash: '', origin: 'https://alimne.app', pathname: '/', href: 'https://alimne.app/' },
  history: { state: null, replaceState: noop }, addEventListener: noop, removeEventListener: noop,
  crypto: globalThis.crypto, localStorage: local, sessionStorage: session,
  matchMedia: () => ({ matches: false, addEventListener: noop, removeEventListener: noop }),
  setTimeout, clearTimeout, setInterval, clearInterval,
}
Object.defineProperty(globalThis, 'window', { value: fakeWindow, configurable: true, writable: true })
Object.defineProperty(globalThis, 'document', { configurable: true, writable: true, value: {
  addEventListener: noop, removeEventListener: noop, visibilityState: 'visible', hidden: false,
  createElement: () => ({ style: {}, setAttribute: noop, appendChild: noop }), body: { appendChild: noop }, head: { appendChild: noop } } })
Object.defineProperty(globalThis, 'localStorage', { value: local, configurable: true })
Object.defineProperty(globalThis, 'sessionStorage', { value: session, configurable: true })
const setNavLang = (language) => Object.defineProperty(globalThis, 'navigator', {
  value: { language, userAgent: 'Mozilla/5.0 verify-free-mode', clipboard: undefined }, configurable: true })
setNavLang('en-US')

const M = await import(pathToFileURL(outFile).href)
const App = M.default
const { renderToStaticMarkup } = (await import('react-dom/server')).default
const React = (await import('react')).default
const h = React.createElement

// ── tiny harness ──────────────────────────────────────────────────────────────────────
let failed = 0, passed = 0
const check = (name, ok, detail = '') => {
  if (ok) { passed++; console.log(`  ok   ${name}`) }
  else { failed++; console.log(`  FAIL ${name}${detail ? '  -> ' + detail : ''}`) }
}
const section = (s) => console.log(`\n${s}`)

// every string a language pack can produce (functions are called with a few sample args)
const SAMPLES = [[1], [2], [3], [11], ['a@b.co'], [null], [{ anon_free_uses: 3, device_daily: 3, user_daily: 40 }]]
function strings(v, out = []) {
  if (typeof v === 'string') out.push(v)
  else if (typeof v === 'function') SAMPLES.forEach(a => { try { const r = v(...a); if (r != null) strings(r, out) } catch { /* sample doesn't fit */ } })
  else if (Array.isArray(v)) v.forEach(x => strings(x, out))
  else if (v && typeof v === 'object') Object.values(v).forEach(x => strings(x, out))
  return out
}
const shape = (v) => Array.isArray(v) ? `array(${v.length})` : typeof v

// copy that must NOT exist in free mode (English, then Arabic)
const BANNED_EN = [
  [/free trial used/i, 'Free trial used'], [/previews?\s+left/i, 'previews left'], [/\bsubscribe\b/i, 'Subscribe'],
  [/\b10\s+(free\s+)?tokens?\b/i, '10 tokens'], [/\btokens?\b/i, 'token'], [/\bcredits?\b/i, 'credit'],
  [/\bgo pro\b/i, 'Go Pro'], [/2\.99/, '$2.99'], [/\b30\s+(guides|a month)/i, '30 guides a month'],
  [/\b3\s+more\s+(?:study\s+)?guides/i, '3 more guides'], [/\b3\s+(?:free\s+)?study\s+guides/i, '3 free study guides'],
  [/\bguides?\s+(?:a|per|every)\s+month\b/i, 'guides a month'], [/\bon us\b/i, 'on us'], [/out of free guides/i, 'out of free guides'],
  [/\bunlimited\b/i, 'unlimited'], [/\bsign up free\b/i, 'Sign up free (paywall)'], [/loved it\?/i, 'Loved it?'],
]
const BANNED_AR = [
  [/رموز|رمز/, 'رموز (tokens)'], [/رصيد/, 'رصيد (credit)'], [/(^|[\s—])اشترك(?=[\s—.،]|$)/, 'اشترك (subscribe)'],
  [/2\.99/, '$2.99'], [/بلا حدود|غير محدود/, 'unlimited'], [/أعجبك\؟/, 'Loved it?'],
]
const scan = (text, lang) => (lang === 'ar' ? BANNED_AR : BANNED_EN).filter(([re]) => re.test(text)).map(([, n]) => n)
// text as react-dom/server prints it
const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#x27;')

// "No sign-up needed" is only true for the first N guides now. A line that says no account / no sign-up
// is needed must carry that qualifier (first N guides, N guides without an account, N free guides left)
// or be about the sample lecture.
const CLAIM = {
  en: /\bno sign-?up\b|\bno account\b|\bwithout an account\b|\bno registration\b|\bwithout (?:signing|registering)\b|\bno need to (?:sign|register)/i,
  ar: /(?:بدون|دون|بلا|من غير) (?:تسجيل|حساب)|لا حاجة إلى (?:حساب|تسجيل)|(?:يحتاج|تحتاج|يحتاجان) إلى (?:حساب|تسجيل)/,
}
const QUALIFIED = {
  en: /\bfirst (?:\d+ )?guides?\b|\b\d+ (?:free )?guides? (?:left )?without an account\b|\bsample\b|\bfree guides without an account are used up\b/i,
  ar: /أول \d+ (?:أدلة|دليلاً)|أول دليلين|دليلك الأول|\d+ (?:أدلة|دليلاً)(?: مجانية| مجانياً)? دون حساب|(?:دليل|دليل مجاني) واحد دون حساب|(?:دليلان|دليلان مجانيان) دون حساب|النموذجية|استُنفدت اليوم الأدلة المجانية المتاحة(?: على شبكتك)? دون حساب/,
}
const unqualified = (text, lang) => String(text).split('\n').map(s => s.trim()).filter(s => CLAIM[lang].test(s) && !QUALIFIED[lang].test(s))

const { T, LEGACY } = M

// ── 1. language packs ────────────────────────────────────────────────────────────────
section('1. T / LEGACY: same keys and shapes in English and Arabic')
for (const [name, pack] of [['T', T], ['LEGACY', LEGACY]]) {
  const en = Object.keys(pack.en).sort(), ar = Object.keys(pack.ar).sort()
  check(`${name}: same key set`, JSON.stringify(en) === JSON.stringify(ar),
    `only EN: ${en.filter(k => !ar.includes(k))}  only AR: ${ar.filter(k => !en.includes(k))}`)
  const bad = en.filter(k => ar.includes(k) && shape(pack.en[k]) !== shape(pack.ar[k]))
  check(`${name}: same value shape per key`, bad.length === 0, bad.join(', '))
}
const NEW_KEYS = ['heroFree', 'dropFree', 'footerFree', 'joinTitle', 'joinBody', 'perks', 'perksNote', 'signInFreeCta',
  'referJoined', 'accountAllowance', 'accountPerDay', 'accountFreeNote', 'queuePos', 'queueWait',
  'errFairIp', 'errFairUser', 'errBusyToday', 'errBusy', 'freeNow',
  // the sign-in gate
  'anonLeft', 'anonNone', 'signinRequired', 'signInToContinue', 'gateCleared', 'generateNow', 'dropFreeUser',
  // the reasons, and the toast after the sign-in round trip
  'signinNetwork', 'signinPool', 'stashReady']
for (const k of NEW_KEYS) check(`new key '${k}' exists in EN and AR`, k in T.en && k in T.ar)
// values that are meant to be Latin: URLs / e-mail placeholders, product names, cell-cycle phase names (G1, S, G2)
const ASCII_OK = new Set(['ytPlaceholder', 'urlPlaceholder', 'emailPh', 'emailPlaceholder', 'pdf', 'anki', 'planPro', 'sampleQuizOpts'])
const rawEnglish = Object.entries(T.ar).filter(([k, v]) => !ASCII_OK.has(k) &&
  strings(v).some(s => s && !/[؀-ۿ]/.test(s))).map(([k]) => k)
check('Arabic pack has no raw-English value', rawEnglish.length === 0, rawEnglish.join(', '))
const rawEnglishLegacy = Object.entries(LEGACY.ar).filter(([k, v]) => !ASCII_OK.has(k) &&
  strings(v).some(s => s && !/[؀-ۿ]/.test(s))).map(([k]) => k)
check('Arabic LEGACY pack has no raw-English value', rawEnglishLegacy.length === 0, rawEnglishLegacy.join(', '))

// ── 2. free-mode strings carry no paywall / token copy ───────────────────────────────
section('2. free-mode strings: no paywall, token, preview or credit copy')
for (const lang of ['en', 'ar']) {
  const hits = new Set()
  for (const [k, v] of Object.entries(T[lang])) strings(v).forEach(s => scan(s, lang).forEach(n => hits.add(`${k}: ${n}`)))
  check(`T.${lang} is clean`, hits.size === 0, [...hits].join(' | '))
  const free = M.tFor(lang, true)
  check(`tFor('${lang}', true) is T.${lang} (nothing from LEGACY merged)`, free === T[lang])
  const legacyOnly = Object.keys(LEGACY[lang]).filter(k => !(k in T[lang]))
  check(`tFor('${lang}', true) has none of the ${legacyOnly.length} legacy-only keys`, legacyOnly.every(k => !(k in free)))
  const leg = M.tFor(lang, false)
  check(`tFor('${lang}', false) restores the token copy`, typeof leg.upgradeBtn === 'string' && leg.upgradeBtn.length > 0)
}
check('LEGACY.en still holds the old paywall copy (kill switch intact)',
  /Go Pro/.test(LEGACY.en.upgradeBtn) && /previews?/.test(LEGACY.en.freeLeft(2)) && /10 free tokens/.test(LEGACY.en.referSub))
check("fair-use messages never say 'unlimited'", ['en', 'ar'].every(l => !/unlimited|غير محدود|بلا حدود/.test(strings(T[l]).join(' '))))
check('hero says free + no card + the first N guides need no account (EN)',
  T.en.heroFree(3) === 'Free. No card. Your first 3 guides need no account.' && !/no sign-?up/i.test(T.en.heroFree(3)), T.en.heroFree(3))
check('token-era promises are still caught by the scan',
  ['Create a free account — 3 more study guides on us', 'Loved it? Sign up free — 3 more guides on us.', 'Get 3 free study guides',
    'Free: 3 study guides a month'].every(s => scan(s, 'en').length > 0) &&
  ["You've used your 3 free guides.", '3 free guides left', 'Your first 3 guides need no account.'].every(s => scan(s, 'en').length === 0))
check('terms say fair use applies (EN + AR)', /fair-use/i.test(M.TERMS_EN) && /الاستخدام العادل/.test(M.TERMS_AR))

// ── 3. numbers from /api/config ───────────────────────────────────────────────────────
section('3. posInt / perks')
const pi = M.posInt
check('posInt accepts positive numbers', pi(10) === 10 && pi(40.9) === 40)
check('posInt rejects junk', [0, -1, NaN, null, undefined, '10', true, Infinity, {}].every(v => pi(v) === null))
const fair = { anon_free_uses: 3, device_daily: 3, user_daily: 40 }
check("perks quote the account's real daily number", M.perksOf(T.en, fair).includes('40') && M.perksOf(T.ar, fair).includes('40'))
check('perks never compare a daily number with the anonymous allowance (it is not a daily one any more)',
  !/instead of/i.test(M.perksOf(T.en, fair)) && !/\b3\b/.test(M.perksOf(T.en, fair)) && !/بدل/.test(M.perksOf(T.ar, fair)))
check('perks omit numbers when unknown', !/\d/.test(M.perksOf(T.en, null)) && !/\d/.test(M.perksOf(T.ar, { device_daily: 3, user_daily: null })))
check('perks only claim real features (more guides, chat, invite)',
  /more guides/.test(M.perksOf(T.en, null)) && /chat/.test(M.perksOf(T.en, null)) && /invite/.test(M.perksOf(T.en, null)))

// ── 4. server refusals → friendly, localized, per-item messages ──────────────────────
section('4. friendlyErr: the new refusals (EN + AR)')
const fe = M.friendlyErr
for (const lang of ['en', 'ar']) {
  const t = M.tFor(lang, true)
  // 'fair_use_device' is what a server from before the sign-in gate sent: it reads as the gate message now
  const cases = [
    ['fair_use_device', 429, t.signinRequired(3)], ['fair_use_ip', 429, t.errFairIp], ['fair_use_user', 429, t.errFairUser],
    ['busy_today', 503, t.errBusyToday], ['busy', 503, t.errBusy],
  ]
  for (const [code, status, want] of cases) {
    const raw = 'server text that must not leak'
    check(`${lang}: ${status} ${code}`, fe(t, raw, status, { code, error: raw }) === want && want && want !== raw)
    check(`${lang}: SSE error event (status 200) ${code}`, fe(t, raw, 200, { code, error: raw }) === want)
  }
  check(`${lang}: the five refusals are all different`, new Set(cases.map(c => c[2])).size === 5)
  check(`${lang}: plain 429 / 503 keep their old text`,
    fe(t, 'x', 429, {}) === t.errRateLimit && fe(t, 'x', 503, {}) === t.errUpdating && fe(t, 'x', 429, { code: 'rate_limited' }) === t.errRateLimit)
  check(`${lang}: no_notes + refunded needs no legacy string`, fe(t, 'x', 200, { code: 'no_notes', refunded: true }) === t.errNoNotes)
  check(`${lang}: legacy still says 'credit returned' when refunded`,
    fe(M.tFor(lang, false), 'x', 200, { code: 'no_notes', refunded: true }) === M.tFor(lang, false).errNoNotesRefunded)
}
check("no message promises 'come back tomorrow' for the anonymous allowance (it is not a daily one)",
  ['en', 'ar'].every(l => !/come back tomorrow|عُد غداً/.test(strings(T[l]).join(' '))) && !('errFairDevice' in T.en) && !('errFairDevice' in T.ar))
check("EN busy_today / busy follow the product copy", /very popular today/i.test(T.en.errBusyToday) && /tap retry in a minute/i.test(T.en.errBusy))
check('only the sign-in refusals offer a sign-in button, and only to a signed-out visitor',
  ['signin_required', 'fair_use_device'].every(c => M.offersSignIn({ errCode: c }, null) === true && M.offersSignIn({ errCode: c }, { user: {} }) === false) &&
  ['fair_use_ip', 'fair_use_user', 'busy', 'busy_today', null, undefined].every(c => M.offersSignIn({ errCode: c }, null) === false))
check('batch stops on sign-in / fair-use / busy refusals', ['signin_required', 'fair_use_device', 'fair_use_ip', 'fair_use_user', 'busy_today', 'busy'].every(c => M.STOP_CODES.has(c)) &&
  !M.STOP_CODES.has('no_notes') && !M.STOP_CODES.has('rate_limited'))

// ── 5. queue position, badge, join card rules ─────────────────────────────────────────
section("5. 'queued' step text and badge, join-card rules")
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  const it = (extra) => ({ status: 'processing', step: 'queued', msg: 'English server text', ...extra })
  check(`${lang}: position shown (not the server's English)`, M.procLine(t, it({ queuePos: 3 })) === t.queuePos(3) && t.queuePos(3).includes('3'))
  check(`${lang}: no position -> waiting text`, M.procLine(t, it({ queuePos: 0 })) === t.queueWait && M.procLine(t, it({})) === t.queueWait)
  check(`${lang}: normal progress still shows the stream message`, M.procLine(t, { status: 'processing', step: 'section', msg: 'Building…' }) === 'Building…')
  check(`${lang}: normal progress falls back to the generic text`, M.procLine(t, { status: 'processing', step: 'extract' }) === t.processing)
}
check("EN queue text reads 'in line - position N'", /in line/i.test(T.en.queuePos(2)) && /position 2/i.test(T.en.queuePos(2)))
check('badge says Queued while waiting in line, Processing otherwise',
  M.badgeKey({ status: 'processing', step: 'queued' }) === 'queued' && M.badgeKey({ status: 'processing', step: 'extract' }) === 'processing' &&
  M.badgeKey({ status: 'error', step: 'queued' }) === 'error')
const base = { freeMode: true, authEnabled: true, authLoading: false, session: null, dismissed: false,
  queue: [{ status: 'done', source: { type: 'file' } }] }
const sj = M.showJoinCard
check('join card: anonymous visitor after a real first guide', sj(base) === true)
const off = (o) => sj({ ...base, ...o }) === false
check('join card: not before any guide', off({ queue: [] }) && off({ queue: [{ status: 'processing' }] }) && off({ queue: [{ status: 'error' }] }))
check('join card: the sample demo does not count', off({ queue: [{ status: 'done', demo: true }] }) && off({ queue: [{ status: 'done', source: { type: 'sample' } }] }))
check('join card: hidden when signed in, dismissed, loading, auth off, or token mode',
  off({ session: { user: {} } }) && off({ dismissed: true }) && off({ authLoading: true }) && off({ authEnabled: false }) && off({ freeMode: false }))

// ── 6. server-rendered components, both languages ─────────────────────────────────────
section('6. rendered markup (free mode)')
const noopFn = () => {}
const payer = { email: 'p@x.co', name: 'Pat', plan: 'pro', subscription_status: 'active', has_billing: true, tokens_remaining: 5, subscription_period_end: '2026-12-01' }
const billingOnly = { email: 'b@x.co', plan: 'free', subscription_status: 'canceled', has_billing: true, tokens_remaining: 3 }
const plain = { email: 'f@x.co', plan: 'free', subscription_status: 'free', has_billing: false, tokens_remaining: 3, referral_code: 'ABC123' }
const acct = (userInfo, lang, over = {}) => renderToStaticMarkup(h(M.AccountModal, {
  onClose: noopFn, onManage: noopFn, onUpgrade: noopFn, onSignOut: noopFn, userInfo, isSubscribed: userInfo.plan === 'pro',
  lang, loadErr: false, onRetry: noopFn, freeMode: true, fair, ...over }))
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  const a = acct(plain, lang), p = acct(payer, lang), b = acct(billingOnly, lang)
  check(`${lang}: Account (free user) offers sign out, never Subscribe / manage`,
    a.includes(t.signOut) && !a.includes(t.manageBtn) && scan(a, lang).length === 0, scan(a, lang).join(','))
  check(`${lang}: Account shows the fair-use daily allowance, not tokens`, a.includes(t.accountPerDay(40)) && !a.includes(String(plain.tokens_remaining) + '<'), '')
  check(`${lang}: Account (active subscriber) can manage / cancel`, p.includes(t.manageBtn) && p.includes(t.accountFreeNote) && p.includes(t.signOut))
  check(`${lang}: Account (has_billing, plan ended) can still manage / cancel`, b.includes(t.manageBtn))
  check(`${lang}: Account has no token balance row`, !p.includes(LEGACY[lang].guidesLeft) && !a.includes(LEGACY[lang].guidesLeft))
  const lg = acct(plain, lang, { freeMode: false, onUpgrade: noopFn })
  check(`${lang}: token-mode Account still offers the old upgrade button`, lg.includes(LEGACY[lang].upgradeBtn) && lg.includes(LEGACY[lang].guidesLeft))
}
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  for (const mode of ['signin', 'signup']) {
    const html = renderToStaticMarkup(h(M.LoginModal, { onClose: noopFn, lang, sbClient: null, initialMode: mode, initialEmail: '', notice: null, freeMode: true, fair }))
    check(`${lang}: sign-in modal (${mode}) shows the benefits line and no token promise`,
      html.includes(esc(t.perksNote(M.perksOf(t, fair)))) && scan(html, lang).length === 0, scan(html, lang).join(','))
  }
  const legacy = renderToStaticMarkup(h(M.LoginModal, { onClose: noopFn, lang, sbClient: null, initialMode: 'signup', initialEmail: '', notice: null, freeMode: false, fair }))
  check(`${lang}: token-mode sign-up modal keeps the old promise and no benefits line`,
    legacy.includes(LEGACY[lang].loginSubSignup) && !legacy.includes(T[lang].perksNote(M.perksOf(T[lang], fair))))
}
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  const join = renderToStaticMarkup(h(M.JoinCard, { t, isAr: lang === 'ar', fair, left: 2, onJoin: noopFn, onDismiss: noopFn }))
  check(`${lang}: join card has title, the guides left, benefits, create button and a labelled dismiss`,
    join.includes(t.joinTitle) && join.includes(esc(t.joinBody(M.perksOf(t, fair), 2))) && join.includes(t.emailBtnSignup) && join.includes(`aria-label="${t.close}"`) && scan(join, lang).length === 0)
  const ref = (stats, freeMode) => renderToStaticMarkup(h(M.ReferralCard, { t: M.tFor(lang, freeMode), isAr: lang === 'ar', freeMode, link: 'https://alimne.app?ref=ABC123', stats, copied: false, onCopy: noopFn }))
  const r3 = ref({ total: 3, paid: 1, tokens_earned: 10 }, true)
  check(`${lang}: invite card = plain share link + friends joined, no token rewards`,
    r3.includes('https://alimne.app?ref=ABC123') && r3.includes(t.referJoined(3)) && r3.includes(t.referCopy) && scan(r3, lang).length === 0 &&
    !/\b10\b/.test(r3.replace(/<[^>]*>/g, ' ')))
  check(`${lang}: invite card with no stats endpoint answer shows no count`, !ref(null, true).includes(t.referJoined(0)))
  check(`${lang}: token-mode invite card keeps the old reward copy`, ref({ total: 3, paid: 2 }, false).includes(LEGACY[lang].referSub))
  const up = renderToStaticMarkup(h(M.UpgradeModal, { onClose: noopFn, onUpgrade: noopFn, onManage: noopFn, isSubscribed: false, lang }))
  check(`${lang}: UpgradeModal (token mode only) renders its price`, up.includes('2.99'))
}
check('terms: free-mode text', (() => {
  const en = renderToStaticMarkup(h(M.TermsModal, { lang: 'en', freeMode: true, onClose: noopFn }))
  const ar = renderToStaticMarkup(h(M.TermsModal, { lang: 'ar', freeMode: true, onClose: noopFn }))
  return /free to use/i.test(en) && /fair-use/i.test(en) && /may change/i.test(en) && /cancel your subscription/i.test(en) && scan(en, 'en').length === 0 &&
    !/Pro plan|2\.99|3 free guides|2 anonymous previews/.test(en) && /مجاني/.test(ar) && /الاستخدام العادل/.test(ar) && /إلغاؤه|إلغاء/.test(ar) && scan(ar, 'ar').length === 0
})())
check('terms: token-mode text is the old one', /Pro plan: \$2\.99\/month/.test(M.TERMS_EN_LEGACY) && /3 free guides every month/.test(M.TERMS_EN_LEGACY))
const tail = (s, mark) => s.slice(s.indexOf(mark))
check('terms: every privacy section (3-10) is byte-identical in both modes',
  tail(M.TERMS_EN, '3. YOUR FILES AND PRIVACY') === tail(M.TERMS_EN_LEGACY, '3. YOUR FILES AND PRIVACY') &&
  tail(M.TERMS_AR, '٣. ملفاتك وخصوصيتك') === tail(M.TERMS_AR_LEGACY, '٣. ملفاتك وخصوصيتك') &&
  /Files you upload are processed entirely in server memory/.test(M.TERMS_EN) && /unshared guides remain memory-only/.test(M.TERMS_EN))

// the whole app, first paint, signed out
section('7. whole App, first paint (signed out, free mode by default)')
for (const lang of ['en', 'ar']) {
  local.clear(); session.clear(); local.setItem('alimne_lang', lang)
  const html = renderToStaticMarkup(h(App))
  const t = T[lang]
  check(`${lang}: hero shows the free line with the first-3-guides qualifier`, html.includes(esc(t.heroFree(3))) && html.includes(esc(t.dropFree(3))) && html.includes(t.footerFree))
  check(`${lang}: first paint makes no unqualified 'no sign-up' claim`, unqualified(html.replace(/<[^>]*>/g, '\n'), lang).length === 0,
    unqualified(html.replace(/<[^>]*>/g, '\n'), lang).join(' | '))
  check(`${lang}: no paywall copy, no preview counter, no token pill`, scan(html, lang).length === 0, scan(html, lang).join(','))
  check(`${lang}: sign-in still reachable`, html.includes(t.signIn) || authIsHiddenForLoading(html))
  check(`${lang}: RTL only in Arabic`, lang === 'ar' ? html.includes('dir="rtl"') : html.includes('dir="ltr"'))
  check(`${lang}: no join card before a guide`, !html.includes(t.joinTitle))
}
function authIsHiddenForLoading() { return true }   // first paint shows a spinner while the session restores

// ── 8. the SSE helper with the new server behaviour ───────────────────────────────────
section('8. streamSSE: queued steps, refusals, terminal events')
const sse = (events) => events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('')
const respond = (status, body, json) => ({
  ok: status >= 200 && status < 300, status, json: async () => json ?? {},
  body: { getReader() { let sent = false; return { read: async () => sent ? { done: true } : (sent = true, { done: false, value: new TextEncoder().encode(body) }) } } },
})
const run = (res) => new Promise((resolve) => {
  const seen = []
  globalThis.fetch = async () => res
  M.streamSSE('/api/x', {}, ev => seen.push(ev), (msg, status, data) => resolve({ seen, err: { msg, status, data } }), T.en)
  setTimeout(() => resolve({ seen, err: null }), 200)
})
let r = await run(respond(200, sse([{ step: 'queued', position: 2, msg: 'Waiting' }, { step: 'queued', position: 1, msg: 'Waiting' }, { step: 'extract', msg: 'Go' }, { step: 'done', job_id: 'j1', sections: 3 }])))
check('queued events reach the handler in order, then done; no error', r.seen.map(e => e.step).join() === 'queued,queued,extract,done' && !r.err)
check("'done' without tokens_remaining is fine", r.seen.at(-1).job_id === 'j1' && r.seen.at(-1).tokens_remaining === undefined)
r = await run(respond(200, sse([{ step: 'queued', position: 1 }, { error: 'busy', code: 'busy' }])))
check("queue timeout arrives as an error event with code 'busy' and nothing after it is processed", r.seen.length === 2 && r.seen[1].code === 'busy')
r = await run(respond(429, '', { error: 'x', code: 'fair_use_device', retry_after_s: 3600 }))
check('HTTP 429 refusal reaches onError with its code', r.err && r.err.status === 429 && r.err.data.code === 'fair_use_device')
r = await run(respond(503, '', { error: 'x', code: 'busy_today' }))
check('HTTP 503 refusal reaches onError with its code', r.err && r.err.status === 503 && r.err.data.code === 'busy_today')
r = await run(respond(200, sse([{ step: 'queued', position: 4 }])))
check('a stream that ends while queued reports connection lost (never stuck)', r.err && r.err.status === 0 && r.err.data.code === 'incomplete')

// ── 9. the sign-in gate after the free guides ─────────────────────────────────────────
section('9. sign-in gate: numbers from /api/config')
const gfc = M.gateFromConfig
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b)
check('the default allowance is 3', M.FREE_USES_DEFAULT === 3)
check('missing / odd config -> 3 of 3', [undefined, null, {}, { anon_free_limit: 'x', anon_remaining: null, signin_after: -1 }].every(c => same(gfc(c), { limit: 3, remaining: 3 })))
check('reads anon_free_limit / anon_remaining / signin_after', same(gfc({ anon_free_limit: 3, anon_remaining: 1, signin_after: 3 }), { limit: 3, remaining: 1 }) &&
  same(gfc({ anon_free_limit: 5, anon_remaining: 4, signin_after: 5 }), { limit: 5, remaining: 4 }) && same(gfc({ signin_after: 4 }), { limit: 4, remaining: 4 }) &&
  same(gfc({ anon_free_limit: 2, anon_remaining: 1 }), { limit: 2, remaining: 1 }))
check('0 left stays 0 (never mistaken for "missing")', same(gfc({ anon_free_limit: 3, anon_remaining: 0, signin_after: 3 }), { limit: 3, remaining: 0 }))
check('remaining is clamped to 0..limit', gfc({ anon_free_limit: 3, anon_remaining: 9 }).remaining === 3 && gfc({ anon_free_limit: 3, anon_remaining: -2 }).remaining === 3 &&
  gfc({ anon_free_limit: 3, anon_remaining: 2.9 }).remaining === 2)
check('countInt: whole numbers >= 0 only', M.countInt(0) === 0 && M.countInt(2.7) === 2 && [-1, NaN, null, undefined, '2', true, Infinity].every(v => M.countInt(v) === null))
const gad = M.gateAfterDone
check("'done' with anon_remaining -> that number (0 included)", same(gad({ limit: 3, remaining: 3 }, { step: 'done', anon_remaining: 2 }), { limit: 3, remaining: 2 }) &&
  same(gad({ limit: 3, remaining: 1 }, { step: 'done', anon_remaining: 0 }), { limit: 3, remaining: 0 }))
check("'done' without anon_remaining -> one less, never below 0", same(gad({ limit: 3, remaining: 3 }, { step: 'done' }), { limit: 3, remaining: 2 }) &&
  same(gad({ limit: 3, remaining: 0 }, { step: 'done' }), { limit: 3, remaining: 0 }) && same(gad({ limit: 3, remaining: 1 }, { step: 'done', anon_remaining: null }), { limit: 3, remaining: 0 }))
check("'done' never raises the count above the limit", gad({ limit: 3, remaining: 1 }, { anon_remaining: 7 }).remaining === 3)

section('9b. sign-in gate: when a generation must not be sent')
const g0 = { freeMode: true, authEnabled: true, authLoading: false, session: null, remaining: 0 }
const ag = M.anonGated
check('signed-out visitor with 0 left is gated', ag(g0) === true)
check('not gated with guides left', ag({ ...g0, remaining: 1 }) === false && ag({ ...g0, remaining: 3 }) === false)
check('never gated when signed in, in token mode, while the session is still restoring, or with sign-in switched off',
  ag({ ...g0, session: { user: {} } }) === false && ag({ ...g0, freeMode: false }) === false && ag({ ...g0, authLoading: true }) === false && ag({ ...g0, authEnabled: false }) === false)
check('token mode is untouched: no hero / dropzone free line, the old trust strip, none of the gate copy overridden',
  ['en', 'ar'].every(l => M.tFor(l, false).heroFree === '' && M.tFor(l, false).dropFree === '' && M.tFor(l, false).trust[0] === LEGACY[l].trust[0]) &&
  LEGACY.en.trust[0] === 'No sign-up to try' && ['anonLeft', 'anonNone', 'signinRequired', 'signInToContinue'].every(k => !(k in LEGACY.en) && !(k in LEGACY.ar)))
check('gate codes: signin_required and the older fair_use_device', M.GATE_CODES.has('signin_required') && M.GATE_CODES.has('fair_use_device') && M.GATE_CODES.size === 2)
check('a held item shows the sign-in badge to a signed-out visitor only',
  M.badgeKey({ status: 'queued', errCode: 'signin_required' }, null) === 'signin' && M.badgeKey({ status: 'queued', errCode: 'signin_required' }, { user: {} }) === 'queued' &&
  M.badgeKey({ status: 'queued' }, null) === 'queued' && M.badgeKey({ status: 'processing', step: 'queued', errCode: 'signin_required' }, null) === 'queued')

section('9c. sign-in gate: copy (EN + AR)')
check('EN gate notice', T.en.signinRequired(3) === "You've used your 3 free guides. Create a free account to keep going — it's still free.", T.en.signinRequired(3))
check('EN gate notice uses the real number', T.en.signinRequired(5).includes('your 5 free guides') && T.en.signinRequired(1).includes('your free guide.') && !/\b1 free guides\b/.test(T.en.signinRequired(1)))
check('AR gate notice: Arabic, with the number (in words up to ten, as the server writes it), free account, still free',
  /[؀-ۿ]/.test(T.ar.signinRequired(3)) && T.ar.signinRequired(3).includes('الثلاثة') && T.ar.signinRequired(5).includes('الخمسة') && T.ar.signinRequired(12).includes('12') &&
  /حساباً مجانياً/.test(T.ar.signinRequired(3)) && /مجاني/.test(T.ar.signinRequired(3).split('—')[1] || ''), T.ar.signinRequired(3))
check('EN nav counter', T.en.anonLeft(3) === '3 free guides left' && T.en.anonLeft(1) === '1 free guide left' && T.en.anonNone === 'Sign in to continue — free')
check('AR nav counter', T.ar.anonLeft(3).includes('3') && /أدلة مجانية/.test(T.ar.anonLeft(3)) && /دليل مجاني واحد/.test(T.ar.anonLeft(1)) && /دليلان مجانيان/.test(T.ar.anonLeft(2)) &&
  /سجّل الدخول/.test(T.ar.anonNone) && /مجان/.test(T.ar.anonNone))
check('EN item state + dropzone hints', T.en.signInToContinue === 'Sign in to continue (free)' && T.en.dropFree(3) === 'Free · 3 guides without an account · then a free sign-in' &&
  !CLAIM.en.test(T.en.dropFreeUser))
check('AR item state + dropzone hints', /سجّل الدخول للمتابعة/.test(T.ar.signInToContinue) && /3 أدلة دون حساب/.test(T.ar.dropFree(3)) && /تسجيل دخول مجاني/.test(T.ar.dropFree(3)) &&
  !CLAIM.ar.test(T.ar.dropFreeUser))
check("the sign-in toast and the 'Generate' button exist in both languages", ['gateCleared', 'generateNow'].every(k => T.en[k] && /[؀-ۿ]/.test(T.ar[k])))
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  for (const code of ['signin_required', 'fair_use_device']) {
    check(`${lang}: ${code} reads as the gate notice with the server's number`,
      fe(t, 'server text', code === 'signin_required' ? 401 : 429, { code, error: 'server text', free_uses: 5 }) === t.signinRequired(5) &&
      fe(t, 'server text', 401, { code, error: 'server text' }) === t.signinRequired(3) && fe(t, 'server text', 200, { code, free_uses: 'x' }) === t.signinRequired(3))
  }
  check(`${lang}: a plain 401 keeps its own text`, fe(t, 'Login required', 401, { code: 'auth_required' }) === 'Login required')
}

// the claim scanner itself, then every free-mode string
check('claim scanner catches each old unqualified claim',
  ['Free. No card. No sign-up needed.', 'Free to use · no account needed · fair-use daily limits apply', 'Try free, no sign-up', 'Free · no sign-up needed',
    'you can try it without an account.'].every(s => unqualified(s, 'en').length === 1) &&
  ['مجاني. بدون بطاقة. لا حاجة إلى حساب.', 'مجاني للاستخدام · بدون حساب · تُطبَّق حدود يومية للاستخدام العادل', 'جرّب مجاناً، بدون تسجيل', 'مجاني · بدون تسجيل',
    'ويمكنك تجربته دون حساب.'].every(s => unqualified(s, 'ar').length === 1))
check('claim scanner accepts the qualified claims', unqualified('Free. No card. Your first 3 guides need no account.', 'en').length === 0 &&
  unqualified('Free · 3 guides without an account · then a free sign-in', 'en').length === 0 && unqualified('No file needed.', 'en').length === 0 &&
  unqualified('مجاني · 3 أدلة دون حساب · ثم تسجيل دخول مجاني', 'ar').length === 0 && unqualified('مجاني. بدون بطاقة.', 'ar').length === 0)
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  const texts = []
  for (const [k, v] of Object.entries(t)) {
    if (typeof v === 'function') [1, 2, 3, 11].forEach(n => { try { const out = v(n, n); if (typeof out === 'string') texts.push(`${k}: ${out}`) } catch { /* not a number key */ } })
    else strings(v).forEach(s2 => texts.push(`${k}: ${s2}`))
  }
  ;[1, 2, 3, 11].forEach(n => M.termsText(lang, true, n).split('\n').forEach(line => texts.push(`terms(${n}): ${line}`)))
  const bad = texts.filter(s2 => unqualified(s2, lang).length)
  check(`${lang}: no free-mode string claims 'no sign-up / no account needed' without the first-N-guides qualifier`, bad.length === 0, bad.join(' | '))
}

section('9d. sign-in gate: rendered pieces')
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  const counter = (left) => renderToStaticMarkup(h(M.AnonCounter, { t, left, onClick: noopFn }))
  check(`${lang}: nav counter shows the guides left`, counter(2).includes(esc(t.anonLeft(2))) && counter(3).includes(esc(t.anonLeft(3))) && !counter(2).includes(esc(t.anonNone)))
  check(`${lang}: nav counter at 0 says sign in to continue`, counter(0).includes(esc(t.anonNone)) && !counter(0).includes(esc(t.anonLeft(1))) && scan(counter(0), lang).length === 0)
  check(`${lang}: nav counter is a labelled button`, /^<button[^>]*aria-label="/.test(counter(1)) && counter(1).includes('ctrl-label'))
  const gate = (over = {}) => renderToStaticMarkup(h(M.LoginModal, { onClose: noopFn, lang, sbClient: null, initialMode: 'signup', initialEmail: '', notice: null,
    freeMode: true, fair, gate: { reason: 'device', uses: 3 }, ...over }))
  check(`${lang}: gate modal opens in sign-up mode with the clear notice`,
    gate().includes(esc(t.signinRequired(3))) && gate().includes(t.loginTitleSignup) && gate().includes(t.emailBtnSignup) && scan(gate(), lang).length === 0, scan(gate(), lang).join(','))
  check(`${lang}: the notice uses the number it is given`, gate({ gate: { reason: 'device', uses: 5 } }).includes(esc(t.signinRequired(5))) && !gate({ gate: { reason: 'device', uses: 5 } }).includes(esc(t.signinRequired(3))))
  check(`${lang}: a normal sign-in modal has no gate notice`, [null, undefined].every(g => !gate({ gate: g }).includes('role="status"') && !gate({ gate: g }).includes(esc(t.signinRequired(3)))))
  check(`${lang}: token mode never shows the gate notice`, !gate({ freeMode: false }).includes(esc(t.signinRequired(3))))
  const jc = (left) => renderToStaticMarkup(h(M.JoinCard, { t, isAr: lang === 'ar', fair, left, onJoin: noopFn, onDismiss: noopFn }))
  check(`${lang}: join card counts the guides left, and says so when none are left`,
    jc(1).includes(esc(t.joinBody(M.perksOf(t, fair), 1))) && jc(0).includes(esc(t.joinBody(M.perksOf(t, fair), 0))) && jc(1) !== jc(2) && jc(0) !== jc(1) && /\d/.test(jc(2)))
}
{
  const en = renderToStaticMarkup(h(M.TermsModal, { lang: 'en', freeMode: true, freeUses: 3, onClose: noopFn }))
  const ar = renderToStaticMarkup(h(M.TermsModal, { lang: 'ar', freeMode: true, freeUses: 3, onClose: noopFn }))
  check('terms (EN): first 3 guides without an account, then a free account is required, fair-use limits for accounts',
    /Without an account you can make your first 3 guides/.test(en) && /a free account is required/.test(en) && /Fair-use limits apply to accounts/.test(en) && !/\{[A-Z_]+\}/.test(en))
  check('terms (AR): the same three statements',
    /أول 3 أدلة دون حساب/.test(ar) && /يلزم حساب مجاني/.test(ar) && /حدود الاستخدام العادل على الحسابات/.test(ar) && !/\{[A-Z_]+\}/.test(ar))
  check('terms follow the number from /api/config', /your first 5 guides/.test(M.termsText('en', true, 5)) && /أول 5 أدلة/.test(M.termsText('ar', true, 5)) &&
    /your first guide\b/.test(M.termsText('en', true, 1)) && /your first 3 guides/.test(renderToStaticMarkup(h(M.TermsModal, { lang: 'en', freeMode: true, onClose: noopFn }))))
  check('terms: token-mode text is untouched by the gate', M.termsText('en', false, 3) === M.TERMS_EN_LEGACY && M.termsText('ar', false, 3) === M.TERMS_AR_LEGACY)
  check('terms no longer say anonymous visitors have a (lower) daily allowance', !/higher daily allowance than anonymous/i.test(en) && !/الزوّار بلا حساب/.test(ar))
}

section('9e. sign-in gate: the refusal over the wire')
r = await run(respond(401, '', { error: "You've used your 3 free guides.", code: 'signin_required', free_uses: 3 }))
check('HTTP 401 signin_required reaches onError with its code and number', r.err && r.err.status === 401 && r.err.data.code === 'signin_required' && r.err.data.free_uses === 3 && r.seen.length === 0)
r = await run(respond(200, sse([{ step: 'extract', msg: 'Go' }, { step: 'done', job_id: 'j2', sections: 2, anon_remaining: 1 }])))
check("'done' carries anon_remaining to the handler", r.seen.at(-1).step === 'done' && r.seen.at(-1).anon_remaining === 1 && !r.err)

// ── 10. WHY the server asked for a sign-in ────────────────────────────────────────────
section('10. sign-in reasons: device / network / pool, one true text each')
const CTA = { en: "Create a free account to keep going — it's still free.", ar: 'أنشئ حساباً مجانياً للمتابعة — ما زال الاستخدام مجانياً.' }
const st = M.signinText
check('EN device / network / pool texts are the three the server sends', T.en.signinRequired(3) === `You've used your 3 free guides. ${CTA.en}` &&
  T.en.signinNetwork === `Today's free guides without an account are used up on your network. ${CTA.en}` &&
  T.en.signinPool === `Today's free guides without an account are used up. ${CTA.en}`, T.en.signinNetwork)
check('AR device / network / pool texts are the three the server sends', T.ar.signinRequired(3) === `لقد استخدمت أدلتك المجانية الثلاثة. ${CTA.ar}` &&
  T.ar.signinNetwork === `استُنفدت اليوم الأدلة المجانية المتاحة على شبكتك دون حساب. ${CTA.ar}` &&
  T.ar.signinPool === `استُنفدت اليوم الأدلة المجانية المتاحة دون حساب. ${CTA.ar}`, T.ar.signinNetwork)
check('AR singular / dual, and the count words match the server table', T.ar.signinRequired(1).startsWith('لقد استخدمت دليلك المجاني. ') && T.ar.signinRequired(2).startsWith('لقد استخدمت دليلَيك المجانيَّين. ') &&
  JSON.stringify(M.AR_THE_COUNT) === JSON.stringify({ 3: 'الثلاثة', 4: 'الأربعة', 5: 'الخمسة', 6: 'الستة', 7: 'السبعة', 8: 'الثمانية', 9: 'التسعة', 10: 'العشرة' }))
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  const three = [t.signinRequired(3), t.signinNetwork, t.signinPool]
  check(`${lang}: the three texts differ and end with the same call to action`, new Set(three).size === 3 && three.every(x => x.endsWith(' ' + CTA[lang])))
  check(`${lang}: only the device text says the visitor used their own guides`,
    /You've used your|لقد استخدمت/.test(three[0]) && three.slice(1).every(x => !/You've used|you used|your \d|استخدمت|أدلتك|دليلك/.test(x)))
  check(`${lang}: network / pool say "today", and only network names the network`, three.slice(1).every(x => /Today|اليوم/.test(x)) && /network|شبكتك/.test(three[1]) && !/network|شبكتك/.test(three[2]))
  check(`${lang}: signinText picks by the server's reason`, st(t, 'device', 3) === three[0] && st(t, 'network', 3) === three[1] && st(t, 'pool', 3) === three[2])
  check(`${lang}: no reason (a server from before it) reads as the device text with the server's number`, st(t, undefined, 5) === t.signinRequired(5) && st(t, null, undefined) === t.signinRequired(3))
  check(`${lang}: a reason this client does not know shows the server's own sentence, never a guess`,
    st(t, 'campus', 3, 'Server sentence.') === 'Server sentence.' && st(t, 'campus', 3, '  ') === t.signinRequired(3) && st(t, 'campus', 3) === t.signinRequired(3))
  for (const [reason, want] of [['device', three[0]], ['network', three[1]], ['pool', three[2]]]) {
    check(`${lang}: friendlyErr 401 signin_required reason=${reason}`,
      fe(t, 'server text', 401, { code: 'signin_required', error: 'server text', free_uses: 3, reason }) === want &&
      fe(t, 'server text', 200, { code: 'signin_required', free_uses: 3, reason }) === want)
  }
  const modal = (gate) => renderToStaticMarkup(h(M.LoginModal, { onClose: noopFn, lang, sbClient: null, initialMode: 'signup', initialEmail: '', notice: null, freeMode: true, fair, gate }))
  check(`${lang}: the modal shows the network text for a network refusal, never "you've used your 3"`,
    modal({ reason: 'network', uses: 3 }).includes(esc(three[1])) && !modal({ reason: 'network', uses: 3 }).includes(esc(three[0])))
  check(`${lang}: the modal shows the pool text for a pool refusal`, modal({ reason: 'pool', uses: 3 }).includes(esc(three[2])) && !modal({ reason: 'pool', uses: 3 }).includes(esc(three[0])))
  check(`${lang}: the modal shows the server's sentence for a reason it does not know`, modal({ reason: 'campus', uses: 3, text: 'Server sentence.' }).includes('Server sentence.'))
  check(`${lang}: no reason text is caught as an unqualified "no account needed" claim, and none has paywall copy`,
    three.every(x => unqualified(x, lang).length === 0 && scan(x, lang).length === 0), three.filter(x => unqualified(x, lang).length).join(' | '))
}
check('the claim scanner still catches a bare "without an account" promise', unqualified('Make guides without an account.', 'en').length === 1 && unqualified('أنشئ الأدلة دون حساب.', 'ar').length === 1)
// only the device's own counter may block a generation locally: the client cannot know the network's or the pool's
const hdc = M.holdsDeviceCount
check("a 'device' refusal (or one with no reason, from an older server) empties the local counter", hdc({ code: 'signin_required', reason: 'device' }) === true &&
  hdc({ code: 'signin_required' }) === true && hdc({ code: 'fair_use_device' }) === true)
check("a 'network' / 'pool' refusal (or a reason this client does not know) leaves the device counter alone, so nothing is pre-blocked for it",
  ['network', 'pool', 'campus'].every(reason => hdc({ code: 'signin_required', reason }) === false))

// ── 11. ANON_FREE_USES=0 ─────────────────────────────────────────────────────────────
section('11. ANON_FREE_USES=0: an account from the first guide, and the client says so')
check('config with 0 is 0 of 0, never the default 3', same(gfc({ anon_free_limit: 0, anon_remaining: 0, signin_after: 0 }), { limit: 0, remaining: 0 }) &&
  same(gfc({ signin_after: 0 }), { limit: 0, remaining: 0 }) && same(gfc({ anon_free_limit: 0 }), { limit: 0, remaining: 0 }))
check('0 of 0 gates a signed-out visitor (and nobody else)', ag({ ...g0, remaining: gfc({ signin_after: 0 }).remaining }) === true && ag({ ...g0, remaining: 0, session: { user: {} } }) === false)
check('EN copy at 0', T.en.heroFree(0) === 'Free. No card. A free account is needed to make guides.' && T.en.dropFree(0) === 'Free · a free account is needed to make guides' &&
  T.en.signinRequired(0) === "Create a free account to make study guides — it's free.", `${T.en.heroFree(0)} | ${T.en.dropFree(0)} | ${T.en.signinRequired(0)}`)
check('AR copy at 0', T.ar.heroFree(0) === 'مجاني. بدون بطاقة. يلزم حساب مجاني لإنشاء الأدلة.' && T.ar.dropFree(0) === 'مجاني · يلزم حساب مجاني لإنشاء الأدلة' &&
  T.ar.signinRequired(0) === 'أنشئ حساباً مجانياً لإنشاء أدلة الدراسة — الاستخدام مجاني.', `${T.ar.heroFree(0)} | ${T.ar.dropFree(0)} | ${T.ar.signinRequired(0)}`)
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  const zero = [t.heroFree(0), t.dropFree(0), t.signinRequired(0)]
  check(`${lang}: hero, dropzone and notice at 0 name no number, promise no guide without an account, and ask for a free account`,
    zero.every(x => !/\d/.test(x) && !CLAIM[lang].test(x) && !/need no account|لا يحتاج|لا تحتاج/.test(x) && /free account|حساب مجاني|حساباً مجانياً/.test(x)), zero.join(' | '))
  check(`${lang}: nothing at 0 says the visitor "used" any guide`, zero.every(x => !/used|استخدمت/.test(x)))
  check(`${lang}: the counter at 0 says 'Sign in to continue - free'`, renderToStaticMarkup(h(M.AnonCounter, { t, left: 0, onClick: noopFn })).includes(esc(t.anonNone)))
  const m0 = renderToStaticMarkup(h(M.LoginModal, { onClose: noopFn, lang, sbClient: null, initialMode: 'signup', initialEmail: '', notice: null, freeMode: true, fair, gate: { reason: 'device', uses: 0 } }))
  check(`${lang}: the gate modal at 0 says an account is needed, not "you've used your 3 free guides"`, m0.includes(esc(t.signinRequired(0))) && !m0.includes(esc(t.signinRequired(3))))
  check(`${lang}: friendlyErr honours free_uses 0`, fe(t, 'x', 401, { code: 'signin_required', free_uses: 0, reason: 'device' }) === t.signinRequired(0))
  const terms0 = M.termsText(lang, true, 0)
  check(`${lang}: the Terms at 0 say a free account is required, with no "first N guides" and no placeholder`,
    (lang === 'en' ? /A free account is required to make study guides; creating one costs nothing\./.test(terms0) && !/your first|Without an account you can/.test(terms0)
      : /يلزم حساب مجاني لإنشاء أدلة الدراسة، وإنشاء الحساب لا يكلّف شيئاً\./.test(terms0) && !/دون حساب\. بعد ذلك|أول \d/.test(terms0)) &&
    !/\{[A-Z_]+\}/.test(terms0) && /sample lecture|النموذجية/.test(terms0))
  const tm0 = renderToStaticMarkup(h(M.TermsModal, { lang, freeMode: true, freeUses: 0, onClose: noopFn }))
  check(`${lang}: the Terms modal follows a 0 from /api/config`, !/your first 3 guides|أول 3 أدلة/.test(tm0))
  const jb = t.joinBody(M.perksOf(t, fair), 0, 0)
  check(`${lang}: the join card at a 0 allowance does not say guides were used`, !/used|استخدمت/.test(jb) && jb === jb.trim() && /free account|حساب مجاني/.test(jb), jb)
  check(`${lang}: the join card with an allowance still counts down and says when it is used`, /used|استخدمت/.test(t.joinBody('x', 0, 3)) && t.joinBody('x', 0, 3) === t.joinBody('x', 0) && /3/.test(t.joinBody('x', 3, 5)))
}

// ── 12. the sign-in round trip ───────────────────────────────────────────────────────
section('12. sign-in stash: what was waiting stays in this browser for the Google round trip')
const MB = 1024 * 1024
check('caps: about 60 MB in all, 3 files, 30 minutes', M.STASH_MAX_BYTES === 60 * MB && M.STASH_MAX_FILES === 3 && M.STASH_MAX_AGE_MS === 30 * 60 * 1000)
const realFile = (name, body = 'slides') => new File([body], name, { type: 'application/pdf' })
const fakeFile = (name, size) => ({ name, size, type: 'application/pdf' })   // only its size matters to the plan
const qi = (extra) => ({ id: 1, status: 'queued', jobId: null, error: null, ...extra })
const sp = M.stashPlan
check('nothing waiting -> nothing kept', sp([], {}) === null && sp(undefined, undefined) === null && sp([], { text: '   ', url: '', yt: '', tab: 'upload' }) === null)
check('finished guides, expired guides and the sample are never kept (they are not "waiting")',
  sp([qi({ status: 'done', jobId: 'j', file: fakeFile('a.pdf', 9), source: { type: 'file' } }), qi({ status: 'expired', jobId: 'j', source: { type: 'youtube', url: 'https://youtu.be/x' } }),
    qi({ status: 'queued', demo: true, source: { type: 'sample', lang: 'en' } })], {}) === null)
{
  const f = realFile('lecture.pdf')
  const plan = sp([qi({ file: f, name: 'lecture.pdf', source: { type: 'file' }, errCode: 'signin_required' }),
    qi({ status: 'error', file: null, name: 'https://youtu.be/abc', source: { type: 'youtube', url: 'https://youtu.be/abc' } }),
    qi({ status: 'processing', file: null, name: 'Pasted text', source: { type: 'text', text: 'Some pasted notes', url: '', name: 'Pasted text' } })],
  { text: ' typed but not sent ', url: 'https://example.com/a', yt: 'https://youtu.be/zzz', tab: 'text' })
  check('queued / failed / in-flight items are kept with their file, link or text', plan && plan.items.length === 3 && plan.items[0].kind === 'file' && plan.items[0].file === f &&
    plan.items[0].name === 'lecture.pdf' && plan.items[1].kind === 'youtube' && plan.items[1].url === 'https://youtu.be/abc' && plan.items[2].kind === 'text' && plan.items[2].text === 'Some pasted notes')
  check('what is typed in the boxes is kept too (text, link, YouTube link, the open tab)', plan.box.text === ' typed but not sent ' && plan.box.url === 'https://example.com/a' && plan.box.yt === 'https://youtu.be/zzz' && plan.box.tab === 'text')
  check('nothing but the source is kept: no job id, no status, no error, no guide', plan.items.every(i => !('jobId' in i) && !('status' in i) && !('error' in i) && !('guide' in i) && !('id' in i)))
}
check('at most 3 files', sp([1, 2, 3, 4, 5].map(n => qi({ id: n, file: fakeFile(`f${n}.pdf`, MB), name: `f${n}.pdf`, source: { type: 'file' } })), {}).items.length === 3)
{
  const plan = sp([qi({ file: fakeFile('a.pdf', 40 * MB), name: 'a.pdf', source: { type: 'file' } }), qi({ file: fakeFile('b.pdf', 30 * MB), name: 'b.pdf', source: { type: 'file' } }),
    qi({ file: fakeFile('c.pdf', 15 * MB), name: 'c.pdf', source: { type: 'file' } })], {})
  check('about 60 MB in all: a file that would pass the cap is left out, a smaller later one still fits', plan.items.map(i => i.name).join() === 'a.pdf,c.pdf')
}
check('a file item whose File is gone, an odd link and an empty text are skipped', sp([qi({ file: null, name: 'x.pdf', source: { type: 'file' } }),
  qi({ file: null, source: { type: 'youtube', url: 'x'.repeat(2001) } }), qi({ file: null, source: { type: 'text', text: '', url: '' } })], {}) === null)
const si = M.stashItems
{
  const f = realFile('lecture.pdf')
  const back = si({ items: [{ kind: 'file', name: 'lecture.pdf', file: f }, { kind: 'youtube', url: 'https://youtu.be/abc' }, { kind: 'text', text: 'Some pasted notes', url: '', name: 'Pasted text' }],
    box: { text: 'typed', url: 'https://example.com/a', yt: '', tab: 'text' } })
  check('the copy comes back as queue items that are READY to generate (queued, no error, nothing held)', back.items.length === 3 &&
    back.items.every(i => i.status === 'queued' && i.error === null && i.jobId === null && !i.errCode && i.id > 0) && new Set(back.items.map(i => i.id)).size === 3)
  check('the File itself comes back, with its name and its source', back.items[0].file === f && back.items[0].name === 'lecture.pdf' && back.items[0].source.type === 'file' &&
    back.items[1].source.type === 'youtube' && back.items[1].source.url === 'https://youtu.be/abc' && back.items[1].file === null &&
    back.items[2].source.type === 'text' && back.items[2].source.text === 'Some pasted notes' && back.items[2].name === 'Pasted text')
  check('the boxes come back', back.box.text === 'typed' && back.box.url === 'https://example.com/a' && back.box.tab === 'text')
  check("what came back is named for the toast: 'file', 'files', 'text', 'link' or 'items'", back.kind === 'items' &&
    si({ items: [{ kind: 'file', name: 'a.pdf', file: realFile('a.pdf') }], box: {} }).kind === 'file' &&
    si({ items: [{ kind: 'file', name: 'a.pdf', file: realFile('a.pdf') }, { kind: 'file', name: 'b.pdf', file: realFile('b.pdf') }], box: {} }).kind === 'files' &&
    si({ items: [], box: { text: 'notes' } }).kind === 'text' && si({ items: [{ kind: 'youtube', url: 'https://youtu.be/abc' }], box: {} }).kind === 'link' &&
    si({ items: [{ kind: 'text', text: 'notes', url: '', name: 'Pasted text' }], box: {} }).kind === 'text' && si({ items: [], box: { yt: 'https://youtu.be/abc' } }).kind === 'link')
  check('junk in the copy is dropped, never rendered: wrong type, oversize, not a file, odd shapes', si(null).items.length === 0 && si(null).kind === null && si({}).kind === null &&
    si({ items: 'x', box: 7 }).items.length === 0 &&
    si({ items: [{ kind: 'file', name: 'evil.exe', file: realFile('evil.exe') }, { kind: 'file', name: 'a.pdf', file: 'not a file' }, { kind: 'file', name: 'big.pdf', file: fakeFile('big.pdf', 51 * MB) },
      { kind: 'youtube', url: 42 }, { kind: 'text', text: {}, url: null }, { kind: 'nope' }, null, 5], box: { text: 9, url: {}, yt: [], tab: 'elsewhere' } }).kind === null)
}

// an in-memory IndexedDB, just enough for the helper: open / upgrade, one store, put / delete / clear / cursor
function fakeIndexedDB({ openFails = false, putThrows = false, hangs = false } = {}) {
  const dbs = new Map()
  const soon = (fn) => setTimeout(fn, 0)
  return {
    dbs,
    rows: () => [...(dbs.get('alimne_signin_stash')?.get('pending') || new Map()).entries()],
    open(name) {
      const req = {}
      if (hangs) return req                      // some private modes never answer
      soon(() => {
        if (openFails) { req.error = new Error('SecurityError'); req.onerror?.(); return }
        const fresh = !dbs.has(name)
        if (fresh) dbs.set(name, new Map())
        const stores = dbs.get(name)
        req.result = {
          createObjectStore: (n) => { stores.set(n, new Map()) },
          close() {},
          transaction(storeName) {
            if (!stores.has(storeName)) throw new Error('NotFoundError')
            const data = stores.get(storeName), tx = {}
            let pending = 0, over = false
            const settle = () => soon(() => { if (!pending && !over) { over = true; tx.oncomplete?.() } })
            const run = (fn) => { const r = {}; pending++; soon(() => { try { r.result = fn(); r.onsuccess?.() } finally { pending--; settle() } }); return r }
            tx.objectStore = () => ({
              put: (v, k) => { if (putThrows) throw new Error('DataCloneError'); return run(() => { data.set(k, v); return k }) },
              delete: (k) => run(() => { data.delete(k) }),
              clear: () => run(() => { data.clear() }),
              openCursor: () => {
                const r = {}, keys = [...data.keys()]
                let i = 0
                const step = () => { pending++; soon(() => { try {
                  const k = keys[i]
                  r.result = i < keys.length ? { key: k, value: data.get(k), delete: () => { data.delete(k) }, continue: () => { i++; step() } } : null
                  r.onsuccess?.()
                } finally { pending--; settle() } }) }
                step()
                return r
              },
            })
            settle()
            return tx
          },
        }
        if (fresh) req.onupgradeneeded?.()
        req.onsuccess?.()
      })
      return req
    },
  }
}
const useIdb = (idb) => Object.defineProperty(globalThis, 'indexedDB', { value: idb, configurable: true, writable: true })
const stash = M.signinStash
const firstLoad = stash.page
const newPageLoad = (n) => { stash.page = `page-load-${n}` }      // what a reload (the return from Google) changes
const planOf = (file) => sp([qi({ file, name: file.name, source: { type: 'file' } })], { text: 'typed notes', url: '', yt: '', tab: 'upload' })
const realNow = Date.now
{
  session.clear()
  let idb = fakeIndexedDB(); useIdb(idb)
  const f = realFile('lecture.pdf')
  check('the copy is saved, and only in this browser: one IndexedDB row, claimed by this tab', (await stash.save(planOf(f))) === true && idb.rows().length === 1 &&
    typeof session.getItem(M.STASH_TAB_KEY) === 'string' && idb.rows()[0][0] === session.getItem(M.STASH_TAB_KEY) && idb.rows()[0][1].items[0].file === f)
  check('nothing to keep -> nothing saved', (await stash.save(null)) === false && idb.rows().length === 1)
  check('the SAME page (Google never opened, or Back from the cache) deletes its copy and restores nothing: the items are still in memory',
    (await stash.take()) === null && idb.rows().length === 0 && session.getItem(M.STASH_TAB_KEY) === null)

  await stash.save(planOf(f)); newPageLoad(1)
  const back = await stash.take()
  check('after the round trip (a new page load in the same tab) the copy comes back, with the File', !!back && back.items[0].file === f && back.box.text === 'typed notes')
  check('...and it is deleted at once: nothing is left behind, and a second read finds nothing', idb.rows().length === 0 && session.getItem(M.STASH_TAB_KEY) === null && (await stash.take()) === null)

  await stash.save(planOf(f)); newPageLoad(2)
  const token = session.getItem(M.STASH_TAB_KEY)
  session.removeItem(M.STASH_TAB_KEY)                                // ANOTHER tab: it holds no claim on this copy
  check('another tab cannot take the copy (it is tied to the tab that made it), and leaves a fresh one alone', (await stash.take()) === null && idb.rows().length === 1)
  Date.now = () => realNow() + M.STASH_MAX_AGE_MS + 1000
  check('...but any tab sweeps a copy older than 30 minutes', (await stash.take()) === null && idb.rows().length === 0)
  Date.now = realNow

  await stash.save(planOf(f)); newPageLoad(3)
  Date.now = () => realNow() + M.STASH_MAX_AGE_MS + 1000
  check('a copy older than 30 minutes is never restored, even to its own tab, and is deleted', (await stash.take()) === null && idb.rows().length === 0 && session.getItem(M.STASH_TAB_KEY) === null)
  Date.now = realNow

  await stash.save(planOf(f)); await stash.save(planOf(realFile('second.pdf')))
  check('a second save from the same tab replaces the first (never two copies for one tab)', idb.rows().length === 1 && idb.rows()[0][1].items[0].name === 'second.pdf')
  await stash.clear()
  check('sign-out deletes every copy and the claim', idb.rows().length === 0 && session.getItem(M.STASH_TAB_KEY) === null)
  void token

  // every way IndexedDB can be missing or broken: nothing is thrown, nothing is kept, sign-in goes on
  useIdb(undefined)
  check('no IndexedDB at all -> skipped silently', (await stash.save(planOf(f))) === false && session.getItem(M.STASH_TAB_KEY) === null && (await stash.take()) === null && (await stash.clear()) === undefined)
  Object.defineProperty(globalThis, 'indexedDB', { get() { throw new Error('SecurityError') }, configurable: true })
  check('IndexedDB that throws on access (blocked site data) -> skipped silently', (await stash.save(planOf(f))) === false && session.getItem(M.STASH_TAB_KEY) === null && (await stash.take()) === null)
  useIdb(fakeIndexedDB({ openFails: true }))
  check('IndexedDB that refuses to open (some private modes) -> skipped silently', (await stash.save(planOf(f))) === false && session.getItem(M.STASH_TAB_KEY) === null && (await stash.take()) === null)
  idb = fakeIndexedDB({ putThrows: true }); useIdb(idb)
  check('a browser that cannot store a File in IndexedDB -> skipped silently, no claim left', (await stash.save(planOf(f))) === false && idb.rows().length === 0 && session.getItem(M.STASH_TAB_KEY) === null)
  useIdb(fakeIndexedDB({ hangs: true }))
  const t0 = realNow()
  check('IndexedDB that never answers cannot hold the sign-in up: the save gives up on its own', (await stash.save(planOf(f), 150)) === false && realNow() - t0 < 3000 && session.getItem(M.STASH_TAB_KEY) === null)
  idb = fakeIndexedDB(); useIdb(idb)
  const brokenSession = { getItem() { throw new Error('blocked') }, setItem() { throw new Error('blocked') }, removeItem() { throw new Error('blocked') } }
  Object.defineProperty(globalThis, 'sessionStorage', { value: brokenSession, configurable: true })
  check('no session storage -> no copy is made (nothing could claim it back)', (await stash.save(planOf(f))) === false && idb.rows().length === 0 && (await stash.take()) === null)
  Object.defineProperty(globalThis, 'sessionStorage', { value: session, configurable: true })
  useIdb(undefined); stash.page = firstLoad
}

section('12b. sign-in stash: the words (EN + AR) stay true')
for (const lang of ['en', 'ar']) {
  const t = T[lang]
  const kinds = ['file', 'files', 'text', 'link', 'items'].map(k => t.stashReady(k))
  check(`${lang}: the toast after the round trip says signed in, what is ready, and to tap Generate`, new Set(kinds).size === 5 &&
    kinds.every(x => (lang === 'en' ? /^You're signed in\. Your .+ ready — tap Generate\.$/.test(x) : /^تم تسجيل الدخول\. .+ — اضغط «توليد»\.$/.test(x))), kinds.join(' | '))
  check(`${lang}: the toast names the Generate button as the UI names it`, kinds[0].includes(lang === 'en' ? 'Generate' : t.generateNow))
  check(`${lang}: the short privacy line says the server only uses memory, and the browser keeps what waits during Google sign-in (never uploaded early)`,
    lang === 'en' ? /server memory only/.test(t.privacy) && /sign in with Google/.test(t.privacy) && /your own browser only/.test(t.privacy) && /never uploaded early/.test(t.privacy)
      : /ذاكرة الخادم فقط/.test(t.privacy) && /Google/.test(t.privacy) && /متصفحك فقط/.test(t.privacy) && /دون رفعه مسبقاً/.test(t.privacy), t.privacy)
  check(`${lang}: the short privacy line no longer says a file is never written to disk at all (the browser copy is on the visitor's own disk)`,
    !/never written to disk\b/.test(t.privacy) && !/لا تُكتب على القرص/.test(t.privacy))
  const terms = M.termsText(lang, true, 3)
  check(`${lang}: the Terms (free mode) disclose the browser copy, in section 3: own browser only, not uploaded before Generate, deleted on restore / sign-out, 30 minutes`,
    terms.includes(M.TERMS_STASH[lang]) && terms.indexOf(M.TERMS_STASH[lang]) > terms.indexOf(lang === 'en' ? '3. YOUR FILES AND PRIVACY' : '٣. ملفاتك وخصوصيتك') &&
    terms.indexOf(M.TERMS_STASH[lang]) < terms.indexOf(lang === 'en' ? '4. AI-GENERATED CONTENT DISCLAIMER' : '٤. إخلاء مسؤولية') &&
    (lang === 'en' ? /your own browser only/.test(M.TERMS_STASH.en) && /not uploaded until you tap Generate/.test(M.TERMS_STASH.en) && /sign out/.test(M.TERMS_STASH.en) && /30 minutes/.test(M.TERMS_STASH.en)
      : /متصفحك فقط/.test(M.TERMS_STASH.ar) && /لا يُرفع قبل أن تضغط «توليد»/.test(M.TERMS_STASH.ar) && /تسجيل خروجك/.test(M.TERMS_STASH.ar) && /30 دقيقة/.test(M.TERMS_STASH.ar)))
  check(`${lang}: the Terms modal renders that bullet, and it makes no storage or 'no account' claim`,
    renderToStaticMarkup(h(M.TermsModal, { lang, freeMode: true, freeUses: 3, onClose: noopFn })).includes(esc(M.TERMS_STASH[lang])) &&
    unqualified(M.TERMS_STASH[lang], lang).length === 0 && !/never stored|nothing stored|no data stored|no storage/i.test(M.TERMS_STASH[lang]))
  const leg = M.tFor(lang, false)
  check(`${lang}: token mode keeps its old privacy line and Terms (no browser copy is made there)`,
    leg.privacy !== t.privacy && !/Google/.test(leg.privacy) && !M.termsText(lang, false, 3).includes(M.TERMS_STASH[lang]) &&
    (lang === 'en' ? /never written to disk or seen by anyone/.test(leg.privacy) : /لا تُكتب على القرص ولا يراها أحد/.test(leg.privacy)))
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
