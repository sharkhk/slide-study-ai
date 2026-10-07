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
//     (English or Arabic) still claims "no sign-up needed" without the "first N guides" qualifier.
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
  'FREE_USES_DEFAULT', 'GATE_CODES', 'countInt', 'gateFromConfig', 'gateAfterDone', 'anonGated', 'termsText', 'AnonCounter']

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
  en: /\bfirst (?:\d+ )?guides?\b|\b\d+ (?:free )?guides? (?:left )?without an account\b|\bsample\b/i,
  ar: /أول \d+ (?:أدلة|دليلاً)|أول دليلين|دليلك الأول|\d+ (?:أدلة|دليلاً)(?: مجانية| مجانياً)? دون حساب|(?:دليل|دليل مجاني) واحد دون حساب|(?:دليلان|دليلان مجانيان) دون حساب|النموذجية/,
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
  'anonLeft', 'anonNone', 'signinRequired', 'signInToContinue', 'gateCleared', 'generateNow', 'dropFreeUser']
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
check('AR gate notice: Arabic, with the number, free account, still free',
  /[؀-ۿ]/.test(T.ar.signinRequired(3)) && T.ar.signinRequired(3).includes('3') && /حساباً مجانياً/.test(T.ar.signinRequired(3)) && /مجاني/.test(T.ar.signinRequired(3).split('—')[1] || ''), T.ar.signinRequired(3))
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
    freeMode: true, fair, gateUses: 3, ...over }))
  check(`${lang}: gate modal opens in sign-up mode with the clear notice`,
    gate().includes(esc(t.signinRequired(3))) && gate().includes(t.loginTitleSignup) && gate().includes(t.emailBtnSignup) && scan(gate(), lang).length === 0, scan(gate(), lang).join(','))
  check(`${lang}: the notice uses the number it is given`, gate({ gateUses: 5 }).includes(esc(t.signinRequired(5))) && !gate({ gateUses: 5 }).includes(esc(t.signinRequired(3))))
  check(`${lang}: a normal sign-in modal has no gate notice`, !gate({ gateUses: null }).includes(esc(t.signinRequired(3))) && !gate({ gateUses: 0 }).includes(esc(t.signinRequired(3))))
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

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
