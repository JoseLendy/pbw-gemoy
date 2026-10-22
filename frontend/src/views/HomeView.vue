<script setup>
// 门店端 (Home): today's recommendation on the left, the generated post below it; this week + customer
// questions + talk track on the right. Every rule lives server-side (ui/state.py); this renders its JSON view.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ArrowRight, Check, Copy, Download, FileDown, Image as ImageIcon, RefreshCw, RotateCcw, Send } from 'lucide-vue-next'
import { account, cleanHtml, copyText, downloadUrl, meta, postJson, stream } from '../api.js'
import PhoneStage from '../components/PhoneStage.vue'
import ProductArt from '../components/ProductArt.vue'
import ReportFold from '../components/ReportFold.vue'
import { tintFor } from '../components/tints.js'
import { typewrite } from '../components/typewriter.js'

const props = defineProps({ active: Boolean })
const emit = defineEmits(['go'])

const view = ref(null)
const busy = ref(false)
const progress = ref('')
const text = ref('')
const copied = ref(false)
const typing = ref(false)
const resultEl = ref(null)
let cancelType = null
let imageTimer = null
let suppressInput = false

const v = computed(() => view.value || {})
const panel = computed(() => v.value.panel || {})
const storeName = computed(() => (meta.stores.find((x) => x.store_id === v.value.store_id) || {}).store_name || '')
const tint = computed(() => tintFor(panel.value.product))
const hasResult = computed(() => busy.value || !!progress.value || (!!v.value.phone_html && !v.value.phone_html.includes('hw-phone-empty')))

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
  try { setView(await postJson(url, body)) } catch (e) { progress.value = '出错：' + (e.message || '请求失败') }
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

const setPlatform = (p) => call('/api/store/platform', { platform: p })
const toggleOther = () => call('/api/store/toggle-other')
const selectOther = (idx) => call('/api/store/select-other', { idx })
async function generate() {
  const run = slow('/api/store/generate')
  await nextTick()
  resultEl.value && resultEl.value.scrollIntoView({ behavior: 'smooth', block: 'start' })
  await run
}
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
function download(path) { const a = document.createElement('a'); a.href = downloadUrl(path); a.click() }

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
  // the 登录 account wins over the server default; a #store= deep link wins over both
  const m = /[#&]store=(S\d+)/.exec(location.hash || '')
  const want = m ? m[1] : (account.kind === 'store' ? account.store_id : '')
  if (want && view.value && view.value.store_id !== want) await call('/api/store/select', { store_id: want })
  if (account.kind === 'store' && view.value && view.value.role !== account.role) await call('/api/store/role', { role: account.role })
}
watch(() => props.active, (on) => { if (on) open() })
onMounted(() => { if (props.active) open() })
onBeforeUnmount(() => { clearInterval(imageTimer); if (cancelType) cancelType() })
</script>

<template>
  <div class="page page-with-head">
    <header class="page-head">
      <h1>你好，{{ storeName || '门店' }}</h1>
      <p>{{ meta.today }} · {{ v.role || '店员' }} · 今天为你准备了一条推荐</p>
    </header>

    <div class="page-main">
      <!-- today's recommendation: a product tile in the vmall manner -->
      <section class="rec" :style="{ background: tint.tile }" aria-labelledby="rec-title">
        <div class="rec-copy">
          <template v-if="panel.empty">
            <h2 id="rec-title" class="rec-title">今日暂无推荐</h2>
            <p class="muted">可以点「换一条」看看其他推荐。</p>
          </template>
          <template v-else>
            <div class="tag-row">
              <span class="tag tag-red">{{ panel.head || '今日一条' }}</span>
              <span v-if="panel.platform" class="tag">{{ panel.platform }}</span>
            </div>
            <h2 id="rec-title" class="rec-title">{{ panel.product }}</h2>
            <div v-if="panel.locked" class="note warn">{{ panel.locked }}</div>
            <div v-if="panel.notice" class="note info">{{ panel.notice }}</div>
            <ul v-if="panel.reasons && panel.reasons.length" class="reasons" aria-label="为什么推这条">
              <li v-for="(r, i) in panel.reasons" :key="i">
                <Check :size="16" :stroke-width="2.4" aria-hidden="true" />
                <span>{{ r.text }}<span v-if="r.is_demo" class="tag tag-amber">模拟数据</span></span>
              </li>
            </ul>
          </template>

          <div class="seg" role="radiogroup" aria-label="发布平台">
            <button v-for="p in (v.platforms || meta.platforms)" :key="p" class="seg-item" role="radio"
                    :aria-checked="v.platform === p" :class="{ on: v.platform === p }" :disabled="busy" @click="setPlatform(p)">{{ p }}</button>
          </div>

          <div class="actions">
            <button v-if="v.action && v.action.visible" class="btn btn-dark btn-lg" :disabled="busy" @click="generate">
              {{ v.action.label }}<ArrowRight :size="18" aria-hidden="true" />
            </button>
            <button class="btn btn-light" :disabled="busy" @click="toggleOther"><RefreshCw :size="16" aria-hidden="true" />换一条</button>
          </div>
          <div v-if="v.show_other && v.slots && v.slots.length" class="slot-list">
            <button v-for="s in v.slots" :key="s.idx" class="slot" :disabled="busy" @click="selectOther(s.idx)">{{ s.label }}</button>
          </div>
        </div>
        <div class="rec-art" aria-hidden="true"><ProductArt :name="panel.product" /></div>
      </section>

      <!-- the generated post -->
      <section v-if="hasResult" ref="resultEl" class="card result" aria-labelledby="result-title">
        <div class="card-head">
          <h2 id="result-title">文案预览</h2>
          <span class="muted small">{{ panel.product }} · {{ v.platform }}</span>
        </div>
        <div v-if="busy || progress" class="progress-line" role="status" aria-live="polite">{{ progress || '正在准备…' }}</div>

        <div class="result-grid">
          <PhoneStage :html="v.phone_html" :busy="busy" />
          <div class="result-side">
            <template v-if="!busy">
              <div v-if="v.editable" class="quick">
                <span class="field-label">快速调整</span>
                <div class="chip-row">
                  <button v-for="q in (v.quick_edits || meta.quick_edits)" :key="q" class="chip" @click="quickEdit(q)">{{ q }}</button>
                </div>
              </div>

              <div v-if="v.edit_msg_html" class="server-html" v-html="cleanHtml(v.edit_msg_html)"></div>
              <div v-if="v.recovery && v.recovery.visible" class="note err recovery">
                <span>{{ cleanHtml(v.recovery.message) }}</span>
                <button class="btn btn-light btn-sm" @click="recovery">显示最近一次真实运行结果</button>
              </div>
              <div v-if="v.status_html" class="server-html" v-html="cleanHtml(v.status_html)"></div>
              <div v-if="v.banner_html" class="server-html" v-html="cleanHtml(v.banner_html)"></div>

              <div v-if="v.publishable" class="editor">
                <label class="field-label" for="home-pub-text">正文（可直接修改，改完点「检查并保存」）</label>
                <textarea id="home-pub-text" class="textarea" v-model="text" rows="10" spellcheck="false" @input="onInput"></textarea>
                <div v-if="v.edit_status_html" class="server-html" v-html="cleanHtml(v.edit_status_html)"></div>
                <div v-if="v.editable" class="row end">
                  <button class="btn btn-light btn-sm" @click="revert"><RotateCcw :size="15" aria-hidden="true" />恢复原文</button>
                  <button class="btn btn-dark btn-sm" @click="checkSave">检查并保存</button>
                </div>
              </div>

              <div v-if="v.publishable || v.downloadable" class="action-grid">
                <button v-if="v.publishable" class="btn btn-dark" :disabled="!v.can_copy" @click="copy">
                  <component :is="copied ? Check : Copy" :size="16" aria-hidden="true" />{{ copied ? '已复制' : '复制文案' }}
                </button>
                <button v-if="v.downloadable" class="btn btn-light" @click="download('/api/store/download-md')"><FileDown :size="16" aria-hidden="true" />下载 .md</button>
                <button v-if="v.publishable" class="btn btn-light" :disabled="!v.can_export" :title="v.can_export ? '' : '图片就绪后可下载'" @click="download('/api/store/export-zip')"><Download :size="16" aria-hidden="true" />发布包</button>
                <button v-if="v.image_ok" class="btn btn-light" @click="download('/api/store/save-image')"><ImageIcon :size="16" aria-hidden="true" />保存图片</button>
              </div>
              <button v-if="v.publishable" class="btn btn-block" :class="v.published ? 'btn-done' : 'btn-outline'" :disabled="!v.can_copy && !v.published" @click="publish">
                <Send :size="16" aria-hidden="true" />{{ v.publish_label }}
              </button>
            </template>
          </div>
        </div>
        <ReportFold v-if="!busy" :md="v.report_md" />
      </section>
    </div>

    <aside class="page-aside" aria-label="门店信息">
      <section v-if="v.progress_html" class="card">
        <h3 class="aside-title">本周发布</h3>
        <div class="server-html" v-html="cleanHtml(v.progress_html)"></div>
      </section>

      <section class="card">
        <h3 class="aside-title">今天顾客问了什么？</h3>
        <p class="muted small">顾客问到就点一下，总部会汇总高频问题。</p>
        <div class="chip-row">
          <button v-for="c in meta.chips" :key="c.chip_id" class="chip" :class="{ on: (v.tapped_chips || []).includes(c.chip_id) }"
                  :aria-pressed="(v.tapped_chips || []).includes(c.chip_id)" @click="chip(c.chip_id)">{{ c.text }}</button>
        </div>
        <p v-if="v.chip_status" class="muted small chip-status">{{ v.chip_status }}</p>
      </section>

      <section v-if="v.talk_html && !busy" class="card server-html" v-html="cleanHtml(v.talk_html)"></section>

      <button v-if="account.kind !== 'store'" class="card card-link" @click="emit('go', 'login')">
        <span><b>切换门店账号</b><small>在「登录」选择门店与身份</small></span>
        <ArrowRight :size="18" aria-hidden="true" />
      </button>
    </aside>
  </div>
</template>
