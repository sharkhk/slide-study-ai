// Drives the BUILT client (dist/, the files the host serves) in a real headless browser and checks the
// sign-in dialog as a visitor meets it: what opens on arrival, where a click and a key press lead, where the
// keyboard focus is, and which address the page asks the phone or Supabase for.
//
//   node frontend/scripts/verify-login-flows.mjs
//
// verify-free-mode.mjs renders the components to a string: no effect runs there and nothing is clicked. The
// things below can only be seen in a browser (two of them were found that way: a focus that fell to <body>, and
// "Back to Google sign-in" turning into the Google button under a second Enter):
//   * ?join=1 on arrival: the sign-up dialog opens once, the mark comes off the address, and it stays out of the
//     way of a link that came back with an error;
//   * a failed Google return (bad_oauth_state) keeps the Google button; only an expired EMAIL link opens the
//     email sign-in view;
//   * the dialog takes the focus, Tab stays inside it, the focus follows the visitor between the Google view and
//     the email view, and a second Enter or tap never acts on what took the place of the link just used;
//   * a normal browser can ask Supabase to sign in, never to sign up; another app's browser can do both;
//   * "Open in browser": the address it asks for (intent:// in the named Android apps, x-safari-https:// on
//     iPhone, none in an unknown Android web view), the way by hand about 2 s later when the page is still in
//     front, and nothing when the page did go away.
//
// OFFLINE. No server is started and nothing leaves the machine: every request the page makes is paused and
// answered here from dist/ or with a canned reply, anything else is refused, and the browser is started with
// name resolution switched off. The browser is a local Chrome / Edge / Chromium (CHROME_PATH to name one).
// Exit code: 0 = everything passed, 1 = a check failed, 77 = skipped (no such browser, or no built dist/).
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const dist = path.resolve(process.env.ALIMNE_DIST || path.join(here, '..', '..', 'dist'))   // ALIMNE_DIST: another build to drive
const ORIGIN = 'https://alimne.app'
const SUPABASE = 'https://ufwurywcozlpadzaobug.supabase.co'
const skip = (why) => { console.log(`SKIP: ${why}`); process.exit(77) }

// ── the browser ───────────────────────────────────────────────────────────────────────
function findBrowser() {
  const named = [process.env.CHROME_PATH, process.env.CHROME_BIN].filter(Boolean)
  const win = [process.env.PROGRAMFILES, process.env['PROGRAMFILES(X86)'], process.env.LOCALAPPDATA].filter(Boolean).flatMap(base => [
    path.join(base, 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(base, 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    path.join(base, 'Chromium', 'Application', 'chrome.exe'),
  ])
  const mac = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    '/Applications/Chromium.app/Contents/MacOS/Chromium']
  const onPath = (process.env.PATH || '').split(path.delimiter).filter(Boolean).flatMap(dir =>
    ['google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'microsoft-edge'].map(n => path.join(dir, n)))
  return [...named, ...(process.platform === 'win32' ? win : process.platform === 'darwin' ? mac : []), ...(process.platform === 'win32' ? [] : onPath)]
    .find(p => { try { return fs.statSync(p).isFile() } catch { return false } }) || null
}

if (typeof WebSocket !== 'function') skip('this node has no WebSocket (node 22 or newer is needed)')
if (!fs.existsSync(path.join(dist, 'index.html'))) skip('dist/index.html is missing (cd frontend && npm run build)')
const browserPath = findBrowser()
if (!browserPath) skip('no Chrome, Edge or Chromium found (set CHROME_PATH to use one)')

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'alimne-login-flows-'))
const chrome = spawn(browserPath, [
  '--headless=new', '--remote-debugging-port=0', `--user-data-dir=${profile}`, '--no-first-run', '--no-default-browser-check',
  '--disable-background-networking', '--disable-component-update', '--disable-sync', '--disable-extensions', '--disable-default-apps',
  '--metrics-recording-only', '--mute-audio', '--disable-gpu', '--lang=en-US',
  // nothing resolves: a request this script failed to answer cannot reach the network either
  '--host-resolver-rules=MAP * ~NOTFOUND',
  ...(process.platform === 'linux' ? ['--no-sandbox'] : []),
  'about:blank',
], { stdio: ['ignore', 'ignore', 'pipe'] })
let closing = false
const gone = new Promise(resolve => chrome.on('exit', resolve))
// The browser never outlives this script, and its throwaway profile goes with it. The script ends itself after
// 5 minutes (a run takes well under one), so whoever started it never has to kill it and leave the browser behind.
process.on('exit', () => {
  closing = true
  try { chrome.kill() } catch { /* gone already */ }
  try { fs.rmSync(profile, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 }) } catch { /* the OS clears its temp folder */ }
})
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => process.exit(1))
setTimeout(() => { console.log('  FAIL the run took longer than 5 minutes and was stopped'); process.exit(1) }, 300000).unref()

const wsUrl = await new Promise((resolve, reject) => {
  let err = ''
  const timer = setTimeout(() => reject(new Error(`the browser did not start in 30 s: ${err.slice(-300)}`)), 30000)
  chrome.stderr.on('data', chunk => {
    err += chunk
    const m = /DevTools listening on (ws:\/\/\S+)/.exec(err)
    if (m) { clearTimeout(timer); resolve(m[1]) }
  })
  chrome.on('exit', code => { if (!closing) { clearTimeout(timer); reject(new Error(`the browser exited (${code}): ${err.slice(-300)}`)) } })
}).catch(e => skip(e.message))

// ── a just-enough DevTools client ─────────────────────────────────────────────────────
const ws = new WebSocket(wsUrl)
await new Promise((resolve, reject) => { ws.addEventListener('open', resolve); ws.addEventListener('error', () => reject(new Error('no DevTools connection'))) })
let msgId = 0
const waiting = new Map(), listeners = new Map()
ws.addEventListener('message', ev => {
  const m = JSON.parse(ev.data)
  if (m.id) {
    const w = waiting.get(m.id); waiting.delete(m.id)
    if (w) m.error ? w.reject(new Error(`${w.method}: ${m.error.message}`)) : w.resolve(m.result)
  } else listeners.get(m.sessionId || '')?.(m.method, m.params)
})
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = ++msgId
  waiting.set(id, { resolve, reject, method })
  ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }))
})
const sleep = ms => new Promise(r => setTimeout(r, ms))

// ── what the page is given ────────────────────────────────────────────────────────────
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.png': 'image/png', '.txt': 'text/plain', '.xml': 'application/xml' }
const CONFIG = { auth_enabled: true, free_mode: true, anon_free_limit: 3, anon_remaining: 3, signin_after: 3, anon_free_uses: 3,
  fair_use: { device_daily: 3, user_daily: 40 } }
const CORS = [{ name: 'Access-Control-Allow-Origin', value: '*' }, { name: 'Access-Control-Allow-Headers', value: '*' },
  { name: 'Access-Control-Allow-Methods', value: '*' }]
const b64 = (s) => Buffer.from(s).toString('base64')
const json = (code, obj, extra = []) => ({ responseCode: code, responseHeaders: [{ name: 'Content-Type', value: 'application/json' }, ...extra], body: b64(JSON.stringify(obj)) })

function reply(req) {
  const u = new URL(req.url)
  if (u.origin === ORIGIN) {
    if (u.pathname === '/api/config') return json(200, CONFIG)
    if (u.pathname.startsWith('/api/')) return json(404, { error: 'not found' })
    const file = path.resolve(dist, '.' + (u.pathname === '/' ? '/index.html' : u.pathname))
    if (file.startsWith(dist + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile())
      return { responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: TYPES[path.extname(file)] || 'application/octet-stream' }], body: fs.readFileSync(file).toString('base64') }
    return { responseCode: 404, responseHeaders: [{ name: 'Content-Type', value: 'text/plain' }], body: b64('not found') }
  }
  if (u.origin === SUPABASE) {
    if (req.method === 'OPTIONS') return { responseCode: 204, responseHeaders: CORS }
    // the page left for Google: a blank page stands in for Google's
    if (u.pathname === '/auth/v1/authorize') return { responseCode: 200, responseHeaders: [{ name: 'Content-Type', value: 'text/html' }], body: b64('<!doctype html><title>at google</title>') }
    // a new account whose email is not confirmed yet: a user and no session
    if (u.pathname === '/auth/v1/signup') return json(200, { id: '00000000-0000-4000-8000-000000000001', aud: 'authenticated', role: 'authenticated',
      email: 'new@example.com', identities: [{ id: '1', provider: 'email' }], app_metadata: { provider: 'email' }, user_metadata: {}, created_at: '2026-10-07T00:00:00Z',
      confirmation_sent_at: '2026-10-07T00:00:00Z' }, CORS)
    if (u.pathname === '/auth/v1/token') return json(400, { code: 400, error_code: 'invalid_credentials', msg: 'Invalid login credentials' }, CORS)
    return json(404, { code: 404, error_code: 'not_found', msg: 'not found' }, CORS)
  }
  return null   // fonts, anything else: refused
}

// In the page: how the checks look at the dialog
const HELPERS = `window.__t = {
  dialog: () => document.querySelector('[role="dialog"][aria-modal="true"]'),
  text: () => (__t.dialog() ? __t.dialog().innerText : ''),
  btn: (label) => [...(__t.dialog() ? __t.dialog().querySelectorAll('button') : [])].find(b => b.textContent.trim() === label) || null,
  pageBtn: (label) => [...document.querySelectorAll('button')].find(b => !b.closest('[role="dialog"]') && (b.textContent.trim() === label || b.getAttribute('aria-label') === label)) || null,
  mid: (el) => { el.scrollIntoView({ block: 'center' }); const r = el.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 } },
  active: () => { const a = document.activeElement; return !a || a === document.body ? 'BODY'
    : a.tagName + (a.getAttribute('type') ? '[' + a.getAttribute('type') + ']' : '') + ':' + (a.textContent || a.getAttribute('aria-label') || '').trim().slice(0, 60) },
  inDialog: () => !!(__t.dialog() && __t.dialog().contains(document.activeElement)),
  at: () => location.pathname + location.search + location.hash,
}`

const UA = {
  desktop: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
  iosSafari: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
  iosChrome: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/126.0.6478.153 Mobile/15E148 Safari/604.1',
  igAndroid: 'Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UQ1A.240205.004; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.6478.134 Mobile Safari/537.36 Instagram 340.0.0.22.109 Android',
  igIphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 340.0.2.19.105',
  // an app this client does not know by name: a plain Android web view, and an iPhone app's own web view
  plainWebView: 'Mozilla/5.0 (Linux; Android 14; SM-S918B Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0.6478.134 Mobile Safari/537.36',
  linkedInIphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 [LinkedInApp]/9.29.8962',
}
const PHONE = { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }
const DESK = { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false }

// ── one page: its own browser context (fresh storage), every request answered here ───
async function openPage(where, { ua = UA.desktop, screen = DESK } = {}) {
  const { browserContextId } = await send('Target.createBrowserContext')
  const { targetId } = await send('Target.createTarget', { url: 'about:blank', browserContextId })
  const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true })
  const cdp = (method, params) => send(method, params, sessionId)
  const page = { requests: [], asked: [], errors: [], refused: [] }
  listeners.set(sessionId, (method, p) => {
    if (method === 'Fetch.requestPaused') {
      const r = reply(p.request)
      page.requests.push({ url: p.request.url, method: p.request.method, body: p.request.postData || '' })
      if (r) cdp('Fetch.fulfillRequest', { requestId: p.requestId, ...r }).catch(() => {})
      else { page.refused.push(p.request.url); cdp('Fetch.failRequest', { requestId: p.requestId, errorReason: 'BlockedByClient' }).catch(() => {}) }
    }
    else if (method === 'Page.frameRequestedNavigation') page.asked.push(p.url)
    else if (method === 'Runtime.exceptionThrown') page.errors.push(p.exceptionDetails?.exception?.description || p.exceptionDetails?.text || 'exception')
    else if (method === 'Page.javascriptDialogOpening') cdp('Page.handleJavaScriptDialog', { accept: true }).catch(() => {})
  })
  await cdp('Page.enable'); await cdp('Runtime.enable')
  await cdp('Fetch.enable', { patterns: [{ urlPattern: '*' }] })
  await cdp('Emulation.setUserAgentOverride', { userAgent: ua, acceptLanguage: 'en-US' })
  await cdp('Emulation.setDeviceMetricsOverride', screen)
  await cdp('Emulation.setFocusEmulationEnabled', { enabled: true })
  await cdp('Page.addScriptToEvaluateOnNewDocument', { source: HELPERS })

  page.ev = async (expression) => {
    const r = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error(`${expression} -> ${r.exceptionDetails.exception?.description || r.exceptionDetails.text}`)
    return r.result.value
  }
  page.until = async (expression, ms = 8000) => {
    const end = Date.now() + ms
    for (;;) {
      try { if (await page.ev(expression)) return true } catch { /* the page is between two documents */ }
      if (Date.now() > end) return false
      await sleep(50)
    }
  }
  page.click = async (finder) => {
    const at = await page.ev(`(() => { const el = ${finder}; return el ? __t.mid(el) : null })()`)
    if (!at) throw new Error(`nothing to click: ${finder}`)
    for (const type of ['mousePressed', 'mouseReleased']) await cdp('Input.dispatchMouseEvent', { type, x: at.x, y: at.y, button: 'left', clickCount: 1 })
    return at
  }
  page.tapAt = async ({ x, y }) => { for (const type of ['mousePressed', 'mouseReleased']) await cdp('Input.dispatchMouseEvent', { type, x, y, button: 'left', clickCount: 1 }) }
  const KEYS = { Enter: { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, text: '\r' }, Tab: { key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 },
    Escape: { key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 } }
  page.press = async (name, { shift = false } = {}) => {
    const k = { ...KEYS[name], modifiers: shift ? 8 : 0 }
    await cdp('Input.dispatchKeyEvent', { type: 'keyDown', ...k })
    await cdp('Input.dispatchKeyEvent', { type: 'keyUp', ...k, text: undefined })
  }
  page.type = (text) => cdp('Input.insertText', { text })
  page.focus = (finder) => page.ev(`(() => { const el = ${finder}; if (!el) return false; el.focus(); return document.activeElement === el })()`)
  page.to = (pathPart) => page.requests.filter(r => r.url.startsWith(pathPart))
  page.close = async () => {
    listeners.delete(sessionId)
    await send('Target.closeTarget', { targetId }).catch(() => {})
    await send('Target.disposeBrowserContext', { browserContextId }).catch(() => {})
  }

  await cdp('Page.navigate', { url: ORIGIN + where })
  // the app is up when the top bar is there and the session restore has answered (the "Sign in" button shows then)
  page.up = await page.until(`!!window.__t && !!document.querySelector('#root nav') && !!__t.pageBtn('Sign in')`, 15000)
  return page
}

// ── tiny harness ──────────────────────────────────────────────────────────────────────
let failed = 0, passed = 0
const check = (name, ok, detail = '') => {
  if (ok) { passed++; console.log(`  ok   ${name}`) }
  else { failed++; console.log(`  FAIL ${name}${detail !== '' ? '  -> ' + (typeof detail === 'string' ? detail : JSON.stringify(detail)) : ''}`) }
}
const section = (s) => console.log(`\n${s}`)
const TITLE = { signup: 'Create your free account', signin: 'Sign in', email: 'Sign in with email', inbox: 'Check your inbox' }
const QUIET = 'Signed up with email? Sign in with email', BACK = 'Back to Google sign-in', GOOGLE = 'Continue with Google'
const NOTICE = 'Google sign-in is not allowed inside this app.', OPEN = 'Open in browser', MANUAL = 'Nothing opened?'
const titleIs = (t) => `__t.text().split('\\n').map(s => s.trim()).includes(${JSON.stringify(t)})`
const authorize = (page) => page.to(SUPABASE + '/auth/v1/authorize')
const quiet = async (page) => { await sleep(500) }   // past the moment in which a view just shown takes no click

async function run(name, where, opts, body) {
  section(name)
  const page = await openPage(where, opts)
  try {
    check('the built page loads and the top bar is up', page.up, page.errors.concat(page.refused).join(' | '))
    if (page.up) await body(page)
    check('no script error on the page', page.errors.length === 0, page.errors.join(' | '))
    check('nothing was sent anywhere but the site itself and its sign-in provider',
      page.requests.every(r => r.url.startsWith(ORIGIN + '/') || r.url.startsWith(SUPABASE + '/') || page.refused.includes(r.url)) &&
      page.refused.every(u => /^https:\/\/fonts\.(googleapis|gstatic)\.com\//.test(u)), page.refused.join(' | '))
  } catch (e) { check(`${name}: ran to the end`, false, e.message) }
  finally { await page.close() }
}

try {
  // ── 1. ?join=1 on arrival, in a normal browser ─────────────────────────────────────
  await run('1. ?join=1 in a normal browser: the sign-up dialog, the address, the keyboard', '/?join=1&ref=ab12cd34', {}, async (page) => {
    check('the sign-up dialog opens by itself', await page.until(titleIs(TITLE.signup)), await page.ev('__t.text()'))
    check('?join=1 comes off the address (and the invite code is kept as before)',
      await page.ev('__t.at()') === '/' && await page.ev(`localStorage.getItem('alimne_ref')`) === 'AB12CD34', await page.ev('__t.at()'))
    check('it is a dialog named by its title', await page.ev(`(() => { const d = __t.dialog(), id = d.getAttribute('aria-labelledby'); const el = id && document.getElementById(id)
      return d.getAttribute('role') === 'dialog' && d.getAttribute('aria-modal') === 'true' && !!el && el.textContent.trim() === ${JSON.stringify(TITLE.signup)} })()`))
    check('the dialog has the focus when it opens (not the page behind it): on its title, not on a button',
      await page.ev(`__t.inDialog() && document.activeElement.id === 'login-title'`), await page.ev('__t.active()'))
    await page.press('Enter'); await sleep(300)
    check('...so an Enter right after it opens starts no sign-in', authorize(page).length === 0 && await page.ev(titleIs(TITLE.signup)))
    check('...and the dialog keeps its rounded corners while it has the focus', await page.ev(`parseFloat(getComputedStyle(__t.dialog()).borderTopLeftRadius) >= 12`),
      await page.ev(`getComputedStyle(__t.dialog()).borderTopLeftRadius`))
    check('ONE action, "Continue with Google": no form, no field', await page.ev(`(() => { const d = __t.dialog(); const b = d.querySelectorAll('.submit-btn')
      return b.length === 1 && b[0].textContent.trim() === ${JSON.stringify(GOOGLE)} && b[0].getAttribute('type') === 'button' && !d.querySelector('form, input') })()`))
    check('the quiet link is a real button', await page.ev(`(() => { const b = __t.btn(${JSON.stringify(QUIET)}); return !!b && b.tagName === 'BUTTON' && b.getAttribute('type') === 'button' })()`))
    const ratio = await page.ev(`(() => {
      const rgb = (s) => (s.match(/[\\d.]+/g) || []).map(Number)
      const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4) }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b) }
      const fg = rgb(getComputedStyle(__t.btn(${JSON.stringify(QUIET)})).color), bg = rgb(getComputedStyle(__t.dialog()).backgroundColor)
      const a = bg.length > 3 ? bg[3] : 1, on = bg.slice(0, 3).map(v => v * a)      // the dialog's own colour over the dark overlay
      const l1 = lum(fg), l2 = lum(on); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05) })()`)
    check('the quiet link can be read in the default (dark) theme: contrast 4.5:1 or better', ratio >= 4.5, ratio.toFixed(2))
    const stops = []
    for (let i = 0; i < 9; i++) { await page.press('Tab'); stops.push(await page.ev('__t.inDialog()')) }
    for (let i = 0; i < 4; i++) { await page.press('Tab', { shift: true }); stops.push(await page.ev('__t.inDialog()')) }
    check('Tab and Shift+Tab stay inside the dialog', stops.every(Boolean), stops.join(','))

    // the quiet link, by keyboard
    await page.focus(`__t.btn(${JSON.stringify(QUIET)})`)
    await page.press('Enter')
    check('Enter on the quiet link opens the email sign-in view', await page.until(titleIs(TITLE.email)), await page.ev('__t.text()'))
    check('...and the focus is in the email field', await page.ev(`document.activeElement === __t.dialog().querySelector('input[type="email"]')`), await page.ev('__t.active()'))
    check('the email view can create no account: a current password, no sign-up button, no toggle', await page.ev(`(() => { const d = __t.dialog(), txt = __t.text()
      return d.querySelector('input[type="password"]').getAttribute('autocomplete') === 'current-password' && !!__t.btn('Forgot password?') && !!__t.btn(${JSON.stringify(BACK)}) &&
        !__t.btn('Create free account') && !/Create a free account|Already have an account/.test(txt) && !__t.btn(${JSON.stringify(GOOGLE)}) })()`))
    await quiet(page)
    await page.type('old@example.com')
    await page.focus(`__t.dialog().querySelector('input[type="password"]')`)
    await page.type('secret12')
    await page.press('Enter')
    check('submitting it asks Supabase to SIGN IN', await page.until(`/Incorrect email or password/.test(__t.text())`) && page.to(SUPABASE + '/auth/v1/token').some(r => r.method === 'POST' && /grant_type=password/.test(r.url)),
      page.requests.map(r => r.method + ' ' + r.url).filter(u => u.includes('supabase')).join(' | '))
    check('...and says, for a wrong password, to sign in with Google instead', await page.ev(`__t.text().includes('If you signed up with Google, sign in with Google instead.')`))

    // back, with a second Enter right behind the first
    await page.ev(`(() => { window.__back = __t.btn(${JSON.stringify(BACK)}) })()`)
    await page.focus(`__t.btn(${JSON.stringify(BACK)})`)
    await page.press('Enter'); await sleep(60); await page.press('Enter'); await sleep(150); await page.press('Enter')
    await sleep(700)
    check('Enter on "Back to Google sign-in" returns to the Google view', await page.ev(titleIs(TITLE.signup)), await page.ev('__t.text()'))
    check('...the focus is on the quiet link, not on the Google button', await page.ev(`document.activeElement === __t.btn(${JSON.stringify(QUIET)})`), await page.ev('__t.active()'))
    check('...and the Back button left the page: it was not turned into the Google button (the two were one node once)',
      await page.ev(`!!window.__back && !document.contains(window.__back) && window.__back !== __t.btn(${JSON.stringify(GOOGLE)})`))
    check('...and a second Enter does NOT start the Google sign-in', authorize(page).length === 0 && await page.ev('location.origin') === ORIGIN, authorize(page).map(r => r.url).join(' | '))
    check('Escape closes the dialog', (await page.press('Escape'), await page.until('!__t.dialog()', 2000)))
  })

  await run('1b. a normal browser on a phone: a double tap, and the Google button', '/?join=1', { ua: UA.iosSafari, screen: PHONE }, async (page) => {
    check('the sign-up dialog opens', await page.until(titleIs(TITLE.signup)))
    const at = await page.ev(`__t.mid(__t.btn(${JSON.stringify(QUIET)}))`)
    await page.tapAt(at); await sleep(150); await page.tapAt(at)
    await sleep(700)
    check('a double tap on the quiet link opens the email view and leaves it open', await page.ev(titleIs(TITLE.email)), await page.ev('__t.text()'))
    check('...with no error the visitor did not cause', await page.ev(`!__t.dialog().querySelector('[role="alert"]')`), await page.ev('__t.text()'))
    const back = await page.ev(`__t.mid(__t.btn(${JSON.stringify(BACK)}))`)
    await page.tapAt(back); await sleep(150); await page.tapAt(back)
    await sleep(700)
    check('a double tap on "Back to Google sign-in" ends on the Google view, and starts no sign-in', await page.ev(titleIs(TITLE.signup)) && authorize(page).length === 0, await page.ev('__t.text()'))
    check('no sign-up was ever asked of Supabase', page.to(SUPABASE + '/auth/v1/signup').length === 0)
    await page.click(`__t.btn(${JSON.stringify(GOOGLE)})`)
    check('"Continue with Google" leaves for the Google sign-in, once, to come back to the site', await page.until(`document.title === 'at google'`) &&
      authorize(page).length === 1 && /[?&]provider=google(&|$)/.test(authorize(page)[0].url) && new URL(authorize(page)[0].url).searchParams.get('redirect_to') === ORIGIN,
      authorize(page).map(r => r.url).join(' | '))
  })

  // ── 2. no ?join=1, and the links that come back with an error ──────────────────────
  await run('2. no ?join=1: nothing opens by itself', '/?utm_source=ig', {}, async (page) => {
    await sleep(1500)
    check('no dialog opens on a plain visit', await page.ev('!__t.dialog()'))
    await page.click(`__t.pageBtn('Sign in')`)
    check('"Sign in" in the top bar opens the Google view', await page.until(titleIs(TITLE.signin)) && await page.ev(`!!__t.btn(${JSON.stringify(GOOGLE)}) && !__t.dialog().querySelector('form, input')`))
    check('a desktop browser is shown nothing of the in-app view', await page.ev(`!__t.text().includes(${JSON.stringify(NOTICE)}) && !__t.btn(${JSON.stringify(OPEN)})`))
  })

  await run('2b. a Google sign-in that came back failed (bad_oauth_state) keeps the Google button',
    '/?error=invalid_request&error_code=bad_oauth_state&error_description=OAuth+callback+with+invalid+state', {}, async (page) => {
    check('the dialog opens with the error', await page.until(`/Sign-in didn.t complete/.test(__t.text())`), await page.ev('__t.text()'))
    check('...on the Google view: the button is there, and no password is asked for', await page.ev(`!!__t.btn(${JSON.stringify(GOOGLE)}) && !__t.dialog().querySelector('input')`), await page.ev('__t.text()'))
    check('...and it does not speak of an expired link', await page.ev(`!/link has expired|your password/.test(__t.text())`))
    check('the error comes off the address', await page.ev('__t.at()') === '/', await page.ev('__t.at()'))
  })

  await run('2c. an email link that came back expired opens the email sign-in view',
    '/#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired', {}, async (page) => {
    check('the dialog opens on the email view, saying the link expired', await page.until(titleIs(TITLE.email)) && await page.ev(`/That link has expired/.test(__t.text())`), await page.ev('__t.text()'))
    check('...with the password field and the way back to Google', await page.ev(`!!__t.dialog().querySelector('input[type="password"]') && !!__t.btn(${JSON.stringify(BACK)}) && !__t.btn(${JSON.stringify(GOOGLE)})`))
  })

  await run('2d. ?join=1 never opens over a link that came back with an error',
    '/?join=1&error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired', {}, async (page) => {
    check('the email view is what opens', await page.until(titleIs(TITLE.email)), await page.ev('__t.text()'))
    await sleep(1200)
    check('...and the sign-up dialog does not replace it', await page.ev(titleIs(TITLE.email)) && !await page.ev(titleIs(TITLE.signup)))
    check('both marks come off the address', await page.ev('__t.at()') === '/', await page.ev('__t.at()'))
  })

  // ── 3. browsers where Google works: no in-app view ─────────────────────────────────
  for (const [name, ua] of [['Safari on an iPhone', UA.iosSafari], ['Chrome on an iPhone', UA.iosChrome]]) {
    await run(`3. ${name} is a real browser`, '/', { ua, screen: PHONE }, async (page) => {
      await page.click(`__t.pageBtn('Sign in')`)
      check('the Google button, and nothing of the in-app view', await page.until(titleIs(TITLE.signin)) &&
        await page.ev(`!!__t.btn(${JSON.stringify(GOOGLE)}) && !__t.text().includes(${JSON.stringify(NOTICE)}) && !__t.btn(${JSON.stringify(OPEN)}) && !__t.dialog().querySelector('form')`), await page.ev('__t.text()'))
    })
  }

  // ── 4. another app's browser ───────────────────────────────────────────────────────
  const inAppView = `__t.text().includes(${JSON.stringify(NOTICE)}) && !!__t.btn(${JSON.stringify(OPEN)}) && !!__t.btn('Copy link') && !__t.btn(${JSON.stringify(GOOGLE)}) && !!__t.dialog().querySelector('form input[type="email"]')`
  const manual = `[...__t.dialog().querySelectorAll('[role="status"]')].some(el => el.textContent.includes(${JSON.stringify(MANUAL)}))`

  await run('4. Instagram on Android: the in-app view, email sign-up, the way out', '/?utm_source=ig&ref=ab12cd34', { ua: UA.igAndroid, screen: PHONE }, async (page) => {
    await page.click(`__t.pageBtn('Sign in')`)
    check('the notice, "Open in browser", "Copy link", the email form, and no Google button', await page.until(inAppView), await page.ev('__t.text()'))
    check('the way by hand is not shown before a try', !await page.ev(manual))
    // Copy link hands out the link for the real browser, not this page's address
    await page.ev(`(() => { navigator.clipboard.writeText = async (s) => { window.__copied = s } })()`)
    await page.click(`__t.btn('Copy link')`)
    check('"Copy link" copies the site, ?join=1 and the invite code, nothing else of the address',
      await page.until('!!window.__copied', 2000) && await page.ev('window.__copied') === 'https://alimne.app/?join=1&ref=AB12CD34', await page.ev('window.__copied + " (page: " + __t.at() + ")"'))
    // a wrong password here does not send the visitor to a Google button that is not there
    await page.focus(`__t.dialog().querySelector('input[type="email"]')`); await page.type('old@example.com')
    await page.focus(`__t.dialog().querySelector('input[type="password"]')`); await page.type('secret12')
    await page.press('Enter')
    check('a wrong password says to open Alimne in the browser for Google', await page.until(`__t.text().includes('open Alimne in your browser and sign in with Google.')`), await page.ev('__t.text()'))
    // sign-up is here, and it reaches Supabase's sign-up
    await page.click(`__t.btn('New here? Create a free account')`)
    check('the toggle turns the form into a sign-up', await page.until(`!!__t.btn('Create free account')`) &&
      await page.ev(`__t.dialog().querySelector('input[type="password"]').getAttribute('autocomplete') === 'new-password'`))
    await page.click(`__t.btn('Create free account')`)
    check('submitting it asks Supabase to SIGN UP, and the dialog says to check the inbox', await page.until(titleIs(TITLE.inbox)) &&
      page.to(SUPABASE + '/auth/v1/signup').some(r => r.method === 'POST' && r.body.includes('old@example.com')), await page.ev('__t.text()'))
  })

  await run('4b. Instagram on Android: "Open in browser" when the phone does not follow', '/', { ua: UA.igAndroid, screen: PHONE }, async (page) => {
    await page.click(`__t.pageBtn('Sign in')`)
    await page.until(inAppView)
    // the visitor looked at another app and came back before tapping: only what happens after the tap counts
    await page.ev(`(() => { for (const state of ['hidden', 'visible']) { Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state }); document.dispatchEvent(new Event('visibilitychange')) } })()`)
    await page.click(`__t.btn(${JSON.stringify(OPEN)})`)
    await sleep(600)
    check('the tap asks for an intent:// address with scheme=https (the default browser), once', page.asked.length === 1 &&
      page.asked[0] === 'intent://alimne.app/?join=1#Intent;scheme=https;end', page.asked)
    check('...and shows nothing more yet', !await page.ev(manual))
    check('about 2 s later, still in front: the way by hand shows, "Copy link" stays', await page.until(manual, 2500) && await page.ev(`!!__t.btn('Copy link') && !!__t.btn(${JSON.stringify(OPEN)})`))
    check('the page is still Alimne (no blank page, no other address)', await page.ev('location.href') === ORIGIN + '/' && await page.ev(inAppView))
    check('nothing navigates by itself afterwards', (await sleep(2200), page.asked.length === 1), page.asked)
  })

  await run('4c. Instagram on Android: "Open in browser" when the phone does follow', '/', { ua: UA.igAndroid, screen: PHONE }, async (page) => {
    await page.click(`__t.pageBtn('Sign in')`)
    await page.until(inAppView)
    await page.click(`__t.btn(${JSON.stringify(OPEN)})`)
    // the app went to the background: that is all the page can see of a hand-off that worked
    await page.ev(`(() => { Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' }); document.dispatchEvent(new Event('visibilitychange')) })()`)
    await sleep(2500)
    check('the page went to the background: no "Nothing opened?" when the visitor comes back', !await page.ev(manual) && page.asked.length === 1, page.asked)
  })

  await run('4d. an Android web view of an unknown app: no address is tried, the way by hand shows at once', '/', { ua: UA.plainWebView, screen: PHONE }, async (page) => {
    await page.click(`__t.pageBtn('Sign in')`)
    check('it gets the in-app view', await page.until(inAppView), await page.ev('__t.text()'))
    await page.click(`__t.btn(${JSON.stringify(OPEN)})`)
    check('the way by hand shows at once', await page.until(manual, 700))
    await sleep(2200)
    check('...and the page asked for no address it could be shown an error page for', page.asked.length === 0 && await page.ev('location.href') === ORIGIN + '/', page.asked)
  })

  await run('4e. an iPhone app this client does not know by name (LinkedIn) still gets the in-app view', '/', { ua: UA.linkedInIphone, screen: PHONE }, async (page) => {
    await page.click(`__t.pageBtn('3 free guides left')`)
    check('the gate\'s way in (sign-up) shows the notice, "Open in browser", email sign-up, and no Google button', await page.until(inAppView) &&
      await page.ev(`${titleIs(TITLE.signup)} && !!__t.btn('Create free account') && __t.text().includes('or sign up with email here')`), await page.ev('__t.text()'))
    await page.click(`__t.btn(${JSON.stringify(OPEN)})`)
    await sleep(600)
    check('"Open in browser" asks for x-safari-https://', page.asked.length === 1 && page.asked[0] === 'x-safari-https://alimne.app/?join=1', page.asked)
    check('...and the way by hand follows when the page is still in front', await page.until(manual, 2500))
  })

  await run('4f. Instagram on an iPhone', '/', { ua: UA.igIphone, screen: PHONE }, async (page) => {
    await page.click(`__t.pageBtn('Sign in')`)
    await page.until(inAppView)
    await page.click(`__t.btn(${JSON.stringify(OPEN)})`)
    await sleep(600)
    check('"Open in browser" asks for x-safari-https://', page.asked.length === 1 && page.asked[0] === 'x-safari-https://alimne.app/?join=1', page.asked)
  })

  await run('4g. ?join=1 opened inside an app again (the hand-off came back into it)', '/?join=1', { ua: UA.igAndroid, screen: PHONE }, async (page) => {
    check('the sign-up dialog opens on the in-app view', await page.until(`${titleIs(TITLE.signup)} && ${inAppView}`), await page.ev('__t.text()'))
    check('...with the way by hand on screen from the start, not the same button alone', await page.ev(manual))
    check('?join=1 comes off the address', await page.ev('__t.at()') === '/', await page.ev('__t.at()'))
  })
} catch (e) {
  failed++
  console.log(`  FAIL the run stopped: ${e.stack || e.message}`)
} finally {
  closing = true
  try { await Promise.race([send('Browser.close'), sleep(2000)]) } catch { /* it is closing */ }
  try { ws.close() } catch { /* closed with the browser */ }
  await Promise.race([gone, sleep(5000)])   // its files are free to delete once it has exited
}

console.log(`\n${passed} passed, ${failed} failed`)
process.exit(failed ? 1 : 0)
