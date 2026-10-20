<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import PhoneSimulator from './components/PhoneSimulator.vue'

const EXAMPLES = [
  'MateBook D 14 开学季 发小红书',
  '一位妈妈想给上大学的女儿买 MateBook D 14，发小红书',
  '经常出差的销售想换一台轻薄本，发朋友圈',
  '职场新人想要一台能开会做 PPT 的电脑，发公众号',
  '设计师想找一台屏幕好的笔记本修图，发小红书',
  '大学生纠结重量和续航，想买第一台笔记本，发朋友圈',
  '内容创作者想剪视频，需要性能强一点，发抖音',
  'MateBook D 14 门店到店 发海报',
]
const exampleIndex = ref(0)

function shuffleExample() {
  let i = exampleIndex.value
  while (i === exampleIndex.value) i = Math.floor(Math.random() * EXAMPLES.length)
  exampleIndex.value = i
}
const PLATFORMS = [
  { key: 'xiaohongshu', label: '小红书' },
  { key: 'moments', label: '门店朋友圈' },
  { key: 'wechat_article', label: '公众号' },
  { key: 'poster', label: '门店海报' },
  { key: 'douyin', label: '抖音图文' },
]

const status = ref({})
const text = ref('')
const result = ref(null)
const busy = ref(false)
const progressMsg = ref('')
const error = ref('')
const clarification = ref(null)
const clarAnswers = reactive({})
const zoom = ref(1.0)
const platOpen = ref(false)
const copyText = ref('')
const copied = ref(false)
const sessionId = ref(crypto.randomUUID())
const view = ref('input')
const liveResult = ref(null)
let typeOps = []
let typeRunning = false
const cacheReady = ref(false)
let cachePollTimer = null

const connected = computed(() => status.value.connected)
const idxLabel = computed(() => {
  const m = { complete: '完整', partial: '部分', stale: '可能过期' }
  return m[status.value.index_status] || (status.value.index_status || 'stale')
})
const idxValueClass = computed(() => {
  const m = { complete: 'hw-ok', partial: 'hw-amber', stale: 'hw-bad' }
  return m[status.value.index_status] || ''
})

async function streamRequest(url, body, onEvent) {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok || !resp.body) throw new Error('请求失败 ' + resp.status)
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
      if (['result', 'clarification', 'needs_human', 'error', 'ok'].includes(evt.event)) return
    }
  }
}

function handleEvent(evt) {
  if (evt.event === 'progress') progressMsg.value = evt.message
  else if (evt.event === 'draft') scheduleDraft(evt.data)
  else if (evt.event === 'revision') scheduleRevision(evt.data)
  else if (evt.event === 'result') {
    typeOps = []
    liveResult.value = null
    result.value = evt.data
    copyText.value = evt.data.publishable
    if (evt.session_id) sessionId.value = evt.session_id
    platOpen.value = false
    view.value = 'result'
  } else if (evt.event === 'clarification') {
    clarification.value = evt
    for (const q of evt.questions) if (!clarAnswers[q.slot]) clarAnswers[q.slot] = q.options[0]
    view.value = 'input'
  } else if (evt.event === 'needs_human' || evt.event === 'error') {
    error.value = evt.message || '生成失败'
  }
}

async function generate(form = null) {
  if (!text.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  clarification.value = null
  progressMsg.value = ''
  liveResult.value = null
  typeOps = []
  try {
    let needsClar = false
    await streamRequest('/api/check', { text: text.value, form }, (evt) => {
      if (evt.event === 'progress') progressMsg.value = evt.message
      else if (evt.event === 'clarification') {
        needsClar = true
        clarification.value = evt
        for (const q of evt.questions) if (!clarAnswers[q.slot]) clarAnswers[q.slot] = q.options[0]
      }
    })
    if (needsClar) {
      view.value = 'input'
      return
    }
    view.value = 'result'
    await streamRequest('/api/generate', { text: text.value, form, session_id: sessionId.value }, handleEvent)
    startCachePoll()
  } catch (e) {
    error.value = e.message
    view.value = 'input'
  } finally {
    busy.value = false
    progressMsg.value = ''
  }
}

async function editAction(instruction) {
  if (!result.value || busy.value) return
  busy.value = true
  error.value = ''
  liveResult.value = null
  typeOps = []
  try {
    await streamRequest('/api/edit', { instruction, session_id: sessionId.value }, handleEvent)
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
    progressMsg.value = ''
  }
}

function continueClarification() {
  const form = {}
  for (const q of clarification.value.questions) form[q.slot] = clarAnswers[q.slot]
  clarification.value = null
  generate(form)
}

function pickPlatform(label) {
  platOpen.value = false
  editAction('换成' + label)
}

function zoomBy(f) {
  zoom.value = Math.round(Math.min(1.4, Math.max(0.7, zoom.value * f)) * 100) / 100
}

async function copy() {
  if (!copyText.value) return
  try {
    await navigator.clipboard.writeText(copyText.value)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = copyText.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

function download() {
  if (!result.value) return
  const blob = new Blob([result.value.download_md], { type: 'text/markdown;charset=utf-8' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = (result.value.model || 'article').replace(/[^\w一-鿿]+/g, '_') + '_' + result.value.platform_label + '.md'
  a.click()
  URL.revokeObjectURL(a.href)
}

async function downloadImages() {
  if (!result.value) return
  try {
    const resp = await fetch('/api/download-images', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId.value }),
    })
    if (!resp.ok) throw new Error('下载失败 ' + resp.status)
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = (result.value.model || 'article').replace(/[^\w一-鿿]+/g, '_') + '_图片.zip'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    error.value = '下载图片失败：' + (e.message || e)
  }
}

// ---- typewriter (type + backspace + retype on revisions) ----
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

function getFieldText(field, index) {
  const p = liveResult.value && liveResult.value.post
  if (!p) return ''
  return field === 'body' ? (p.body[index] || '') : (p[field] || '')
}

function setFieldText(field, index, text) {
  const p = liveResult.value && liveResult.value.post
  if (!p) return
  if (field === 'body') {
    while (p.body.length <= index) p.body.push('')
    p.body[index] = text
  } else {
    p[field] = text
  }
}

function diffPrefix(a, b) {
  let p = 0
  while (p < a.length && p < b.length && a[p] === b[p]) p++
  return p
}

function enqueueBack(field, index, count) {
  if (count > 0) typeOps.push({ kind: 'back', field, index, count })
}

function enqueueType(field, index, text) {
  if (text) typeOps.push({ kind: 'type', field, index, text })
}

async function processQueue() {
  if (typeRunning) return
  typeRunning = true
  while (typeOps.length) {
    const op = typeOps.shift()
    if (op.kind === 'type') {
      let i = 0
      while (i < op.text.length) {
        const chunk = op.text.slice(i, i + 3)
        i += chunk.length
        setFieldText(op.field, op.index, getFieldText(op.field, op.index) + chunk)
        await sleep(14)
      }
    } else {
      for (let k = 0; k < op.count; k += 3) {
        const cur = getFieldText(op.field, op.index)
        const cut = Math.min(3, cur.length)
        setFieldText(op.field, op.index, cur.slice(0, cur.length - cut))
        await sleep(10)
      }
    }
  }
  typeRunning = false
}

function scheduleDraft(draft) {
  typeOps = []
  liveResult.value = {
    platform: draft.platform,
    post: { title: '', intro: '', body: [], cta: '', tags: (draft.post && draft.post.tags) || [] },
    images: draft.images || [],
  }
  const p = draft.post || {}
  enqueueType('title', 0, p.title || '')
  enqueueType('intro', 0, p.intro || '')
  ;(p.body || []).forEach((b, i) => enqueueType('body', i, b))
  enqueueType('cta', 0, p.cta || '')
  processQueue()
}

function scheduleRevision(rev) {
  if (!liveResult.value) { scheduleDraft(rev); return }
  const oldP = liveResult.value.post
  const newP = rev.post || {}
  for (const f of ['title', 'intro', 'cta']) {
    const o = oldP[f] || ''
    const n = newP[f] || ''
    if (o !== n) {
      const p = diffPrefix(o, n)
      enqueueBack(f, 0, o.length - p)
      enqueueType(f, 0, n.slice(p))
    }
  }
  const maxBody = Math.max(oldP.body.length, (newP.body || []).length)
  for (let i = 0; i < maxBody; i++) {
    const o = oldP.body[i] || ''
    const n = (newP.body || [])[i] || ''
    if (o !== n) {
      const p = diffPrefix(o, n)
      enqueueBack('body', i, o.length - p)
      enqueueType('body', i, n.slice(p))
    }
  }
  liveResult.value.post.tags = newP.tags || []
  liveResult.value.images = rev.images || liveResult.value.images
  processQueue()
}

function startCachePoll() {
  stopCachePoll()
  cacheReady.value = false
  cachePollTimer = setInterval(async () => {
    try {
      const resp = await fetch('/api/cache-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId.value }),
      })
      const data = await resp.json()
      if (data.ready) {
        cacheReady.value = true
        stopCachePoll()
      }
    } catch {}
  }, 1000)
}

function stopCachePoll() {
  if (cachePollTimer) {
    clearInterval(cachePollTimer)
    cachePollTimer = null
  }
}

function cancelPrefetch(sid) {
  if (!sid) return
  fetch('/api/cancel', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sid }),
  }).catch(() => {})
}

function backToInput() {
  if (busy.value) return
  cancelPrefetch(sessionId.value)
  stopCachePoll()
  cacheReady.value = false
  sessionId.value = crypto.randomUUID()
  result.value = null
  liveResult.value = null
  typeOps = []
  error.value = ''
  clarification.value = null
  copyText.value = ''
  progressMsg.value = ''
  platOpen.value = false
  view.value = 'input'
}

function reset() {
  if (busy.value) return
  cancelPrefetch(sessionId.value)
  stopCachePoll()
  cacheReady.value = false
  result.value = null
  liveResult.value = null
  typeOps = []
  error.value = ''
  clarification.value = null
  copyText.value = ''
  progressMsg.value = ''
  zoom.value = 1.0
  platOpen.value = false
  text.value = ''
  sessionId.value = crypto.randomUUID()
  view.value = 'input'
  for (const k in clarAnswers) delete clarAnswers[k]
}

onMounted(async () => {
  try {
    const r = await fetch('/api/status')
    status.value = await r.json()
  } catch { /* backend not up yet */ }
})
</script>

<template>
  <video class="hw-bg-video" autoplay muted loop playsinline src="/background.mp4"></video>
  <div class="hw-page">
    <div class="hw-status">
      <span class="hw-chip"><span class="hw-label">知识库：</span><span :class="connected ? 'hw-ok' : 'hw-bad'">{{ connected ? '已连接' : '未连接' }}</span></span>
      <span class="hw-chip"><span class="hw-label">索引：</span><span :class="idxValueClass">{{ idxLabel }}</span></span>
      <span class="hw-chip"><span class="hw-label">模型：</span><span :class="status.model ? '' : 'hw-bad'">{{ status.model || '未设置' }}</span></span>
      <span class="hw-chip"><span class="hw-label">快速：</span><span :class="status.model_fast ? '' : 'hw-bad'">{{ status.model_fast || '未设置' }}</span></span>
      <span class="hw-chip"><span class="hw-label">密钥：</span><span :class="status.configured ? 'hw-ok' : 'hw-bad'">{{ status.configured ? '已配置' : '未配置' }}</span></span>
    </div>

    <transition name="page" mode="out-in">
      <div v-if="view === 'input'" key="input" class="hw-input-view">
        <div class="hw-hero">
          <h1 class="hw-hero-title">华为 PC 图文软文 Agent</h1>
          <p class="hw-hero-sub">输入一句顾客描述，生成经知识库核验、可直接发布的平台软文。</p>
        </div>

        <div class="composer">
          <textarea v-model="text" rows="2" spellcheck="false" placeholder="输入顾客描述，例如：一位妈妈想给上大学的女儿买 DemoBook 14（演示版），发小红书" @keydown.enter.exact.prevent="generate()"></textarea>
          <div class="composer-foot">
            <div class="examples">
              <transition name="bubble" mode="out-in">
                <button :key="exampleIndex" class="example-bubble" @click="text = EXAMPLES[exampleIndex]">{{ EXAMPLES[exampleIndex] }}</button>
              </transition>
              <button class="btn btn-ghost btn-sm" @click="shuffleExample">换一个</button>
            </div>
            <div class="composer-btns">
              <button class="btn btn-ghost btn-sm" :disabled="busy" @click="reset">重置</button>
              <button class="btn btn-primary btn-sm" :disabled="busy" @click="generate()">生成</button>
            </div>
          </div>
        </div>

        <div class="hw-progress">{{ busy ? (progressMsg || '正在理解需求…') : '' }}</div>

        <div v-if="clarification" class="report">
          <b>还需要补充一点信息：</b>
          <div v-for="q in clarification.questions" :key="q.slot" style="margin:10px 0">
            <div style="font-weight:600;margin-bottom:6px">{{ q.text }}</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button v-for="opt in q.options" :key="opt" class="example"
                      :style="clarAnswers[q.slot] === opt ? 'border-color:var(--hw-red);color:var(--hw-red)' : ''"
                      @click="clarAnswers[q.slot] = opt">{{ opt }}</button>
            </div>
          </div>
          <div style="display:flex;justify-content:flex-end">
            <button class="btn btn-primary" :disabled="busy" @click="continueClarification">继续生成</button>
          </div>
        </div>

        <div v-if="error" class="hw-stop">⛔ {{ error }}</div>
      </div>

      <div v-else key="result" class="hw-result-view" :class="{ 'is-loading': !result }">
        <div class="hw-progress">{{ busy ? (progressMsg || '正在生成…') : '' }}</div>

        <div class="hw-stage" :style="{ '--zoom': zoom }">
          <div class="hw-phone-stage">
            <div class="hw-phone-wrap" :style="{ zoom: zoom }">
              <PhoneSimulator v-if="liveResult || result" :result="liveResult || result" />
              <div v-else class="hw-phone">
                <div class="notch"></div>
                <div class="screen hw-empty">
                  <img class="hw-logo-img" src="/logo.png" alt="HUAWEI" style="width:80px;height:auto" />
                </div>
              </div>
              <div v-if="busy && !liveResult" class="hw-loading-overlay">
                <div class="hw-spinner"></div>
                <div class="hw-thinking-title">正在生成，请稍候</div>
              </div>
            </div>
          </div>
          <div class="hw-tools">
            <button class="hw-round" title="放大" @click="zoomBy(1.1)">＋</button>
            <button class="hw-round" title="缩小" @click="zoomBy(0.9)">－</button>
            <div class="hw-plat-wrap">
              <button class="hw-round" title="换平台" :disabled="busy || !cacheReady" @click="platOpen = !platOpen">换</button>
              <div v-if="platOpen" class="hw-side-sel">
                <label v-for="p in PLATFORMS" :key="p.key">
                  <input type="radio" name="platform" :checked="result && result.platform === p.key" @change="pickPlatform(p.label)" />
                  {{ p.label }}
                </label>
              </div>
            </div>
          </div>
        </div>

        <div v-if="error" class="hw-stop">⛔ {{ error }}</div>

        <template v-if="result && !busy">
          <div v-if="result.talk_card && result.talk_card.length" class="hw-talk">
            <h4>💬 导购话术（{{ result.model }}）</h4>
            <ol><li v-for="t in result.talk_card" :key="t">{{ t }}</li></ol>
          </div>

          <div v-if="result.banner.passed && !result.banner.pending.length && !result.banner.warns.length" class="hw-banner ok">
            ✅ 已核验：所有产品事实均来自知识库台账，图片属于目标型号，未发现合规问题。（{{ result.post.selling_points.length }} 个事实点 · {{ result.images.length }} 张图 · 改写 {{ result.banner.loops }} 轮）
          </div>
          <div v-if="result.banner.errors.length" class="hw-banner err">
            ❌ {{ result.banner.errors.length }} 处未通过核验
            <ul><li v-for="e in result.banner.errors" :key="e.code">{{ e.message }}<span v-if="e.span">：「{{ e.span }}」</span></li></ul>
          </div>
          <div v-if="result.banner.warns.length || result.banner.pending.length" class="hw-banner warn">
            ⚠️ 待确认
            <ul>
              <li v-for="w in result.banner.warns" :key="w.code">{{ w.message }}</li>
              <li v-for="p in result.banner.pending" :key="p">{{ p }}</li>
            </ul>
          </div>

          <div class="actions">
            <button class="btn btn-ghost" :disabled="busy" @click="editAction('短一点')">短一点</button>
            <button class="btn btn-ghost" :disabled="busy" @click="editAction('换卖点')">换卖点</button>
            <button class="btn btn-ghost" :disabled="busy" @click="editAction('换个角度')">换个角度</button>
          </div>

          <div class="copy-box">
            <textarea :value="copyText" readonly spellcheck="false"></textarea>
            <div class="copy-row">
              <button class="btn btn-ghost" @click="copy">{{ copied ? '已复制 ✓' : '复制正文' }}</button>
              <button class="btn btn-ghost" @click="download">下载 .md</button>
              <button class="btn btn-ghost" @click="downloadImages">下载图片</button>
            </div>
          </div>

          <details class="report">
            <summary>详细信息（四段式输出）</summary>
            <pre>{{ result.report }}</pre>
          </details>
        </template>

        <div class="back-row">
          <button class="btn btn-ghost btn-sm" :disabled="busy" @click="backToInput">← 重新输入</button>
        </div>
      </div>
    </transition>

    <div class="hw-footer">
      知识库内容仅用于生成与核验，不提供原文浏览或批量导出。密钥仅存于环境变量。
    </div>
  </div>
</template>
