<script setup>
// 门店端·今日推荐, split into two pages: overview (store + card + questions) and detail (phone + text).
// Every rule lives server-side (ui/state.py); this view renders the JSON view and sends the user's actions.
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { copyText, downloadUrl, meta, postJson, stream } from '../api.js'
import Panel from '../components/Panel.vue'
import PhoneStage from '../components/PhoneStage.vue'
import ReportFold from '../components/ReportFold.vue'
import { typewrite } from '../components/typewriter.js'

const props = defineProps({ active: Boolean })

const view = ref(null)
const busy = ref(false)
const progress = ref('')            // single latest generation-status line
const text = ref('')            // the editable 正文 box
const copied = ref(false)
const typing = ref(false)
const page = ref(1)             // 1 = overview, 2 = phone + text
watch(page, () => window.scrollTo({ top: 0 }))   // page 2 opens at its top, not at page 1's scroll
let cancelType = null
let imageTimer = null
let suppressInput = false

const v = computed(() => view.value || {})
const panel = computed(() => v.value.panel || {})
const greeting = computed(() => {
  const s = meta.stores.find(x => x.store_id === v.value.store_id)
  return s ? `你好，${s.store_name}` : '你好'
})

function setView(data, { live = false } = {}) {
  view.value = data
  const nextText = data.pub_text || ''
  if (cancelType) { cancelType(); cancelType = null }
  suppressInput = true
  if (live && nextText) {
    typing.value = true
    cancelType = typewrite(nextText, (t) => { text.value = t }, { onDone: () => { typing.value = false; cancelType = null } })
  } else {
    text.value = nextText
    typing.value = false
  }
  setTimeout(() => { suppressInput = false }, 0)
  scheduleImagePoll()
}

async function call(url, body = {}) {
  try {
    setView(await postJson(url, body))
  } catch (e) {
    progress.value = '出错：' + (e.message || '请求失败')
  }
}

async function slow(url, body = {}) {
  if (busy.value) return
  busy.value = true
  progress.value = ''
  try {
    await stream(url, body, (evt) => {
      if (evt.event === 'progress') progress.value = evt.message
      else if (evt.event === 'view') { progress.value = ''; setView(evt.data, { live: true }) }
      else if (evt.event === 'error') progress.value = '出错：' + evt.message
    })
  } catch (e) {
    progress.value = '出错：' + (e.message || '请求失败')
  } finally {
    busy.value = false
  }
}

// ---- actions
const selectStore = (e) => call('/api/store/select', { store_id: e.target.value })
const setPlatform = (p) => call('/api/store/platform', { platform: p })
const setRole = (r) => call('/api/store/role', { role: r })
const toggleOther = () => call('/api/store/toggle-other')
const selectOther = (idx) => call('/api/store/select-other', { idx })
const generate = () => { page.value = 2; slow('/api/store/generate') }
const quickEdit = (ins) => slow('/api/store/quick-edit', { instruction: ins })
const recovery = () => call('/api/store/recovery')
const publish = () => call('/api/store/publish')
const chip = (id) => call('/api/store/chip', { chip_id: id })
const revert = () => call('/api/store/revert')
const checkSave = () => call('/api/store/check-save', { text: text.value })

let inputTimer = null
function onInput() {
  if (suppressInput || typing.value) return
  clearTimeout(inputTimer)
  inputTimer = setTimeout(async () => {
    try {
      const r = await postJson('/api/store/text-input', { text: text.value })
      if (view.value) view.value = { ...view.value, edit_status_html: r.edit_status_html, can_copy: r.can_copy, can_export: r.can_export }
    } catch { /* ignore */ }
  }, 250)
}

async function copy() {
  if (!v.value.can_copy) return
  await copyText(v.value.final_text)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}

function download(path) {
  const a = document.createElement('a')
  a.href = downloadUrl(path)
  a.click()
}

// ---- image poll: prepared posts render with placeholders until the cache is warm (never block load)
function scheduleImagePoll() {
  clearInterval(imageTimer)
  imageTimer = null
  if (!view.value || !view.value.image_pending) return
  imageTimer = setInterval(async () => {
    try {
      const r = await postJson('/api/store/image-tick')
      if (r.changed) {
        const keepText = text.value
        view.value = r.data
        text.value = view.value.pub_text || keepText
        if (!r.data.image_pending) { clearInterval(imageTimer); imageTimer = null }
      }
    } catch { /* retry next tick */ }
  }, 1500)
}

async function open() {
  await call('/api/store/view')
  const m = /[#&]store=(S\d+)/.exec(location.hash || '')
  if (m && view.value && view.value.store_id !== m[1]) await call('/api/store/select', { store_id: m[1] })
}
watch(() => props.active, (on) => { if (on) open() })
onMounted(() => { if (props.active) open() })
onBeforeUnmount(() => { clearInterval(imageTimer); if (cancelType) cancelType() })
</script>

<template>
  <div class="store">
    <transition name="page" mode="out-in">
      <!-- ================= PAGE 1: overview ================= -->
      <div v-if="page === 1" key="overview" class="store-page overview-page">
        <!-- greeting -->
        <div class="overview-hero">
          <h1>{{ greeting }}</h1>
          <p>这是今天为门店准备的推荐，选好门店后点「生成」查看手机预览与文案。</p>
        </div>

        <!-- store panel -->
        <div class="store-controls">
          <label class="field">
            <span class="field-label">演示模式：切换门店账号</span>
            <select class="select" :value="v.store_id" @change="selectStore">
              <option v-for="s in meta.stores" :key="s.store_id" :value="s.store_id">{{ s.store_name }}</option>
            </select>
          </label>
          <div class="field">
            <span class="field-label">演示身份</span>
            <div class="pills">
              <button v-for="r in ['店员', '店长']" :key="r" class="pill" :class="{ on: v.role === r }" @click="setRole(r)">{{ r }}</button>
            </div>
          </div>
          <div class="field">
            <span class="field-label">平台版本</span>
            <div class="pills">
              <button v-for="p in (v.platforms || meta.platforms)" :key="p" class="pill" :class="{ on: v.platform === p }" @click="setPlatform(p)">{{ p }}</button>
            </div>
          </div>
        </div>

        <!-- this week -->
        <div v-if="v.progress_html" class="store-progress" v-html="v.progress_html"></div>

        <div class="store-stack">
          <!-- recommendation panel -->
          <Panel class="card-panel">
            <template v-if="panel.empty"><p class="muted">今日暂无推荐。</p></template>
            <template v-else>
              <div class="card-head">{{ panel.head }}</div>
              <div class="card-product"><b>{{ panel.product }}</b><span class="card-platform">{{ panel.platform }}</span></div>
              <div v-if="panel.locked" class="hw-banner warn">{{ panel.locked }}</div>
              <div v-if="panel.notice" class="hw-banner note">{{ panel.notice }}</div>
              <div v-if="panel.reasons && panel.reasons.length" class="card-reasons">
                <div class="card-reasons-title">为什么推这条</div>
                <ul>
                  <li v-for="(r, i) in panel.reasons" :key="i">{{ r.text }}<span v-if="r.is_demo" class="hw-dev">模拟数据</span></li>
                </ul>
              </div>
            </template>
            <div class="btn-row end">
              <button class="btn btn-ghost" :disabled="busy" @click="toggleOther">换一条</button>
              <button v-if="v.action && v.action.visible" class="btn btn-primary" :disabled="busy" @click="generate">{{ v.action.label }}</button>
            </div>
            <div v-if="v.show_other && v.slots && v.slots.length" class="slot-row">
              <button v-for="s in v.slots" :key="s.idx" class="btn btn-ghost btn-sm" :disabled="busy" @click="selectOther(s.idx)">{{ s.label }}</button>
            </div>
          </Panel>

          <!-- customer questions -->
          <Panel title="今天顾客问了什么？" class="chips-panel">
            <div class="chips">
              <button v-for="c in meta.chips" :key="c.chip_id" class="example-bubble" :class="{ on: (v.tapped_chips || []).includes(c.chip_id) }" @click="chip(c.chip_id)">{{ c.text }}</button>
            </div>
            <div class="muted small chip-status">{{ v.chip_status }}</div>
          </Panel>
        </div>

        <div class="btn-row center page-nav">
          <button class="btn btn-primary btn-lg" @click="page = 2">查看手机预览与文案 →</button>
        </div>
      </div>

      <!-- ================= PAGE 2: phone + text ================= -->
      <div v-else key="detail" class="store-page">
        <div class="detail-top">
          <button class="btn btn-ghost btn-sm" :disabled="busy" @click="page = 1">← 返回</button>
          <span class="muted small">{{ panel.product }} · {{ panel.platform }}</span>
        </div>

        <div class="store-stack">
          <div v-if="busy || progress" class="hw-progress-line" role="status" aria-live="polite">{{ progress || '· 正在准备…' }}</div>

          <PhoneStage :html="v.phone_html" :busy="busy" />

          <template v-if="!busy">
            <div v-if="v.editable" class="btn-row quick center">
              <button v-for="q in (v.quick_edits || meta.quick_edits)" :key="q" class="btn btn-ghost" @click="quickEdit(q)">{{ q }}</button>
            </div>

            <div v-if="v.edit_msg_html" v-html="v.edit_msg_html"></div>
            <div v-if="v.recovery && v.recovery.visible" class="hw-banner err recovery">
              <div>{{ v.recovery.message }}</div>
              <button class="btn btn-ghost btn-sm" @click="recovery">显示最近一次真实运行结果</button>
            </div>
            <div v-if="v.talk_html" v-html="v.talk_html"></div>
            <div v-if="v.status_html" v-html="v.status_html"></div>
            <div v-if="v.banner_html" v-html="v.banner_html"></div>

            <Panel v-if="v.publishable" class="pub-panel">
              <label class="field-label" for="store-pub-text">正文（可直接修改，改完点「检查并保存」）</label>
              <textarea id="store-pub-text" class="pub-text" v-model="text" rows="9" spellcheck="false" @input="onInput"></textarea>
              <div v-if="v.editable" class="btn-row end">
                <button class="btn btn-ghost btn-sm" @click="revert">恢复原文</button>
                <button class="btn btn-primary btn-sm" @click="checkSave">检查并保存</button>
              </div>
              <div v-if="v.edit_status_html" v-html="v.edit_status_html"></div>
            </Panel>

            <div v-if="v.publishable || v.downloadable" class="btn-row center action-btns">
              <button v-if="v.publishable" class="btn btn-primary" :disabled="!v.can_copy" @click="copy">{{ copied ? '已复制 ✓' : '复制文案' }}</button>
              <button v-if="v.downloadable" class="btn btn-ghost" @click="download('/api/store/download-md')">下载 .md</button>
              <button v-if="v.publishable" class="btn btn-ghost" :disabled="!v.can_export" :title="v.can_export ? '' : '图片就绪后可下载'" @click="download('/api/store/export-zip')">下载发布包</button>
              <button v-if="v.image_ok" class="btn btn-ghost" @click="download('/api/store/save-image')">保存图片</button>
            </div>
            <div v-if="v.publishable" class="btn-row center">
              <button class="btn" :class="v.published ? 'btn-done' : 'btn-ghost'" :disabled="!v.can_copy && !v.published" @click="publish">{{ v.publish_label }}</button>
            </div>

            <ReportFold :md="v.report_md" />
          </template>
        </div>
      </div>
    </transition>
  </div>
</template>
