// Shared client state + API helpers. One session id per browser tab (sessionStorage).
import { ref, reactive } from 'vue'

function makeId() {
  try {
    const k = 'hwpc-session'
    let v = sessionStorage.getItem(k)
    if (!v) {
      v = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now()).replace(/-/g, '')
      sessionStorage.setItem(k, v)
    }
    return v
  } catch {
    return String(Math.random()).slice(2) + Date.now()
  }
}

export const sessionId = ref(makeId())
export const meta = reactive({ today: '', stores: [], chips: [], platforms: [], compare_products: [],
  compare_platforms: [], manual_platforms: [], manual_examples: [], manual_products: [], manual_scenarios: [],
  quick_edits: [] })

// ---- demo account (登录), per browser tab like the session id
function readJson(key, fallback) {
  try { return JSON.parse(sessionStorage.getItem(key)) || fallback } catch { return fallback }
}
function writeJson(key, value) {
  try { sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* private mode: keep in memory */ }
}
/** The signed-in account. role: 'staff' | 'manager' | 'developer' | '' (not signed in).
 *  kind is 'store' for staff/manager and 'dev' for the developer. */
const EMPTY_ACCOUNT = { username: '', role: '', role_label: '', store_id: '', store_name: '',
  display_name: '', kind: '' }
export const account = reactive({ ...EMPTY_ACCOUNT, ...readJson('hwpc-account', {}) })
export function setAccount(next) {
  Object.assign(account, EMPTY_ACCOUNT, next || {})
  writeJson('hwpc-account', { ...account })
}
export function clearAccount() { setAccount(null) }

/** POST /api/auth/login; the server owns the session→account binding. A store account must sign in
 *  under the shop picked on the login screen; the developer account is company-wide. */
export async function login(username, password, storeId = '') {
  abortStreams()   // a new account must never inherit an old account's in-flight generation
  const r = await postJson('/api/auth/login', { username, password, store_id: storeId })
  if (r.ok && r.account) setAccount(r.account)
  return r
}
export async function logout() {
  abortStreams()   // stop any running generation before the account is cleared
  try { await postJson('/api/auth/logout') } catch { /* the client still signs out */ }
  clearAccount()
}
/** Reconcile with the server on page load: a stale tab after a server restart must sign in again. */
export async function refreshAccount() {
  try {
    const r = await postJson('/api/auth/me')
    if (r && r.account) setAccount(r.account)
    else clearAccount()
  } catch { /* backend down: keep what we had */ }
}
export async function demoAccounts() {
  try { return await getJson('/api/auth/demo-accounts') } catch { return { accounts: [], password: '' } }
}
/** Create an account for a lower role (developer → manager/staff, manager → staff). */
export async function createAccount(payload) {
  return postJson('/api/auth/create', payload)
}
/** Change your own password. */
export async function changePassword(payload) {
  return postJson('/api/auth/change-password', payload)
}
/** Remove a lower-role account (developer → manager/staff any store, manager → staff own store). */
export async function removeUser(payload) {
  return postJson('/api/auth/remove', payload)
}
/** Current API config (developer only; secrets are never returned, only their configured flags). */
export async function getSettings() {
  try { return await getJson('/api/settings') } catch { return { base_url: '', model: '', key_configured: false, ima_configured: false } }
}
/** Update the API config (developer only; a blank api_key keeps the current one). */
export async function saveSettings(payload) {
  return postJson('/api/settings', payload)
}

/** Server banners still carry emoji status marks; the UI draws its own tone, so drop them. */
const EMOJI_MARKS = /(?:✅|❌|⚠️|⚠|ℹ️|ℹ|💬|🔒|⛔|⏱️|⏱|✏️|✏)️?\s?/g
export function cleanHtml(html) { return (html || '').replace(EMOJI_MARKS, '') }
export const status = reactive({ kb_name: '', kb_state: '', kb_ok: false, checking: true, index_label: '',
  index_status: '', model: '', model_fast: '', configured: false, dev_mode: false, fake_fields: [], error: '', today: '' })

async function failure(resp) {
  let detail = ''
  try {
    const body = await resp.json()
    detail = body.detail || body.reason || body.error || ''
  } catch { /* not JSON */ }
  return new Error(detail || '请求失败 ' + resp.status)
}

export async function postJson(url, body = {}) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId.value, ...body }),
  })
  if (!resp.ok) throw await failure(resp)
  return resp.json()
}

export async function getJson(url) {
  const sep = url.includes('?') ? '&' : '?'
  const resp = await fetch(`${url}${sep}session_id=${encodeURIComponent(sessionId.value)}`)
  if (!resp.ok) throw await failure(resp)
  return resp.json()
}

/** Abort every in-flight NDJSON stream. login / logout call this so a new account never keeps receiving
 *  (or keeps displaying) an earlier account's generation. */
const ACTIVE_STREAMS = new Set()
export function abortStreams() {
  for (const ctrl of ACTIVE_STREAMS) { try { ctrl.abort() } catch { /* ignore */ } }
  ACTIVE_STREAMS.clear()
}

/** POST and read an NDJSON stream; onEvent gets every parsed line. A plain JSON response (rate limit,
 *  validation) is delivered as one event. Resolves when the stream ends or is aborted. */
export async function stream(url, body, onEvent) {
  const ctrl = new AbortController()
  ACTIVE_STREAMS.add(ctrl)
  try {
    const resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId.value, ...body }),
      signal: ctrl.signal,
    })
    if (!resp.ok) throw new Error('请求失败 ' + resp.status)
    const ctype = resp.headers.get('content-type') || ''
    if (!ctype.includes('ndjson') || !resp.body) {
      onEvent(await resp.json())
      return
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, idx).trim()
        buf = buf.slice(idx + 1)
        if (!line) continue
        let evt
        try { evt = JSON.parse(line) } catch { continue }
        onEvent(evt)
      }
    }
    if (buf.trim()) {
      try { onEvent(JSON.parse(buf.trim())) } catch { /* partial tail */ }
    }
  } finally {
    ACTIVE_STREAMS.delete(ctrl)
  }
}

export function downloadUrl(path) {
  return `${path}?session_id=${encodeURIComponent(sessionId.value)}&t=${Date.now()}`
}

/** Download a server file as a blob. This keeps an error response (e.g. 图片还没准备好) from navigating
 *  the tab to a raw JSON page: it throws the server's message instead. */
export async function downloadFile(url, fallbackName = 'download') {
  const resp = await fetch(url)
  if (!resp.ok) {
    let msg = '下载失败'
    try { msg = (await resp.json()).error || msg } catch { /* not a JSON error body */ }
    throw new Error(msg)
  }
  const blob = await resp.blob()
  const cd = resp.headers.get('content-disposition') || ''
  let name = fallbackName
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd) || /filename="?([^";]+)"?/.exec(cd)
  if (m) { try { name = decodeURIComponent(m[1]) } catch { name = m[1] } }
  const objUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objUrl
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(objUrl), 1000)
}

export async function copyText(text) {
  if (!text) return false
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  return true
}

let _metaResolve
export const metaReady = new Promise((r) => { _metaResolve = r })
export async function loadMeta() {
  try { Object.assign(meta, await getJson('/api/meta')) } catch { /* backend not up yet */ }
  _metaResolve()
}

export async function refreshStatus() {
  try { Object.assign(status, await getJson('/api/status')) } catch { /* keep the last one */ }
}
