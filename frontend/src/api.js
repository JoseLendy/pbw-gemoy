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

// ---- demo account (登录) and the engineer gate, both per browser tab like the session id
function readJson(key, fallback) {
  try { return JSON.parse(sessionStorage.getItem(key)) || fallback } catch { return fallback }
}
function writeJson(key, value) {
  try { sessionStorage.setItem(key, JSON.stringify(value)) } catch { /* private mode: keep in memory */ }
}
/** kind: 'store' | 'hq'; store_id / store_name / role only for a store account. Empty until 登录. */
export const account = reactive(readJson('hwpc-account', { kind: '', store_id: '', store_name: '', role: '店员' }))
export function setAccount(next) {
  Object.assign(account, next)
  writeJson('hwpc-account', { ...account })
}
export const engineer = reactive({ unlocked: readJson('hwpc-engineer', false) === true })
export async function unlockEngineer(code) {
  const r = await postJson('/api/engineer/unlock', { code })
  if (r.ok) { engineer.unlocked = true; writeJson('hwpc-engineer', true) }
  return r
}
export function lockEngineer() { engineer.unlocked = false; writeJson('hwpc-engineer', false) }

/** Server banners still carry emoji status marks; the UI draws its own tone, so drop them. */
const EMOJI_MARKS = /(?:✅|❌|⚠️|⚠|ℹ️|ℹ|💬|🔒|⛔|⏱️|⏱|✏️|✏)️?\s?/g
export function cleanHtml(html) { return (html || '').replace(EMOJI_MARKS, '') }
export const status = reactive({ kb_name: '', kb_state: '', kb_ok: false, checking: true, index_label: '',
  index_status: '', model: '', model_fast: '', configured: false, dev_mode: false, fake_fields: [], error: '', today: '' })

export async function postJson(url, body = {}) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId.value, ...body }),
  })
  if (!resp.ok) throw new Error('请求失败 ' + resp.status)
  return resp.json()
}

export async function getJson(url) {
  const resp = await fetch(url)
  if (!resp.ok) throw new Error('请求失败 ' + resp.status)
  return resp.json()
}

/** POST and read an NDJSON stream; onEvent gets every parsed line. A plain JSON response (rate limit,
 *  validation) is delivered as one event. Resolves when the stream ends. */
export async function stream(url, body, onEvent) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId.value, ...body }),
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
}

export function downloadUrl(path) {
  return `${path}?session_id=${encodeURIComponent(sessionId.value)}&t=${Date.now()}`
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
