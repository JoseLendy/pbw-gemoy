<script setup>
// 手动输入: Davin's composer → result flow over the original pipeline (run / edit / 换平台 / 全平台).
import { computed, reactive, ref } from 'vue'
import { copyText, downloadUrl, meta, postJson, stream } from '../api.js'
import PhoneStage from '../components/PhoneStage.vue'
import ReportFold from '../components/ReportFold.vue'
import { typewrite } from '../components/typewriter.js'

const EXAMPLES = computed(() => meta.manual_examples.length ? meta.manual_examples : [
  'DemoBook 14 开学季 发小红书',
])
const exampleIndex = ref(0)
function shuffleExample() {
  if (EXAMPLES.value.length < 2) return
  let i = exampleIndex.value
  while (i === exampleIndex.value) i = Math.floor(Math.random() * EXAMPLES.value.length)
  exampleIndex.value = i
}

const text = ref('')
const view = ref('input')          // 'input' | 'result'
const busy = ref(false)
const progress = ref([])
const result = ref(null)           // {kind:'result', phone_html, talk_html, banner_html, report_md, pub_text, platform_label}
const stopHtml = ref('')
const clarification = ref(null)
const clarAnswers = reactive({})
const copyBox = ref('')
const copied = ref(false)
const platOpen = ref(false)
const allHtml = ref('')
let cancelType = null

function handle(data, live = true) {
  if (!data) return
  if (data.kind === 'clarification') {
    clarification.value = data
    for (const q of data.questions) if (!clarAnswers[q.slot]) clarAnswers[q.slot] = q.options[0]
    view.value = 'input'
    return
  }
  if (data.kind === 'stop') {
    stopHtml.value = data.html
    if (!result.value) view.value = 'input'
    return
  }
  result.value = data
  stopHtml.value = ''
  allHtml.value = ''
  platOpen.value = false
  view.value = 'result'
  if (cancelType) cancelType()
  if (live) cancelType = typewrite(data.pub_text || '', (t) => { copyBox.value = t }, { onDone: () => { cancelType = null } })
  else copyBox.value = data.pub_text || ''
}

async function run(url, body) {
  if (busy.value) return
  busy.value = true
  progress.value = []
  stopHtml.value = ''
  try {
    await stream(url, body, (evt) => {
      if (evt.event === 'progress') progress.value = [...progress.value, evt.message]
      else if (evt.event === 'done') handle(evt.data)
      else if (evt.event === 'error') stopHtml.value = `<div class="hw-stop">⛔ ${evt.message}</div>`
    })
  } catch (e) {
    stopHtml.value = `<div class="hw-stop">⛔ ${e.message || '请求失败'}</div>`
  } finally {
    busy.value = false
  }
}

function generate(form = null) {
  if (!text.value.trim()) return
  clarification.value = null
  if (!form) view.value = 'result'
  run('/api/manual/generate', { text: text.value, form })
}
function continueClarification() {
  const form = {}
  for (const q of clarification.value.questions) form[q.slot] = clarAnswers[q.slot]
  clarification.value = null
  view.value = 'result'
  run('/api/manual/generate', { text: text.value, form })
}
const editAction = (ins) => run('/api/manual/edit', { instruction: ins })
function pickPlatform(label) { platOpen.value = false; editAction('换成' + label) }
async function allPlatforms() {
  if (busy.value) return
  busy.value = true
  progress.value = []
  try {
    await stream('/api/manual/all-platforms', {}, (evt) => {
      if (evt.event === 'progress') progress.value = [...progress.value, evt.message]
      else if (evt.event === 'done') allHtml.value = evt.html || ''
    })
  } finally { busy.value = false }
}

async function copy() {
  if (!copyBox.value) return
  await copyText(result.value ? result.value.pub_text : copyBox.value)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
function download() { const a = document.createElement('a'); a.href = downloadUrl('/api/manual/download-md'); a.click() }

function backToInput() { if (!busy.value) view.value = 'input' }
async function reset() {
  if (busy.value) return
  try { await postJson('/api/manual/reset') } catch { /* ignore */ }
  result.value = null; stopHtml.value = ''; clarification.value = null; copyBox.value = ''; allHtml.value = ''
  text.value = ''; view.value = 'input'
  for (const k in clarAnswers) delete clarAnswers[k]
}
</script>

<template>
  <div class="manual">
    <transition name="page" mode="out-in">
      <div v-if="view === 'input'" key="input" class="hw-input-view">
        <div class="hw-hero">
          <h1 class="hw-hero-title">输入一句顾客描述</h1>
          <p class="hw-hero-sub">生成经知识库核验、可直接发布的平台软文。</p>
        </div>
        <div class="composer">
          <textarea v-model="text" rows="2" spellcheck="false" placeholder="例如：一位妈妈想给上大学的女儿买 DemoBook 14（演示版），发小红书" @keydown.enter.exact.prevent="generate()"></textarea>
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
        <div v-if="clarification" class="report clar">
          <b>还需要补充一点信息：</b>
          <div v-for="q in clarification.questions" :key="q.slot" class="clar-q">
            <div class="clar-text">{{ q.text }}</div>
            <div class="pills">
              <button v-for="opt in q.options" :key="opt" class="pill" :class="{ on: clarAnswers[q.slot] === opt }" @click="clarAnswers[q.slot] = opt">{{ opt }}</button>
            </div>
          </div>
          <div class="btn-row end"><button class="btn btn-primary" :disabled="busy" @click="continueClarification">继续生成</button></div>
        </div>
        <div v-if="stopHtml" v-html="stopHtml"></div>
      </div>

      <div v-else key="result" class="hw-result-view">
        <div v-if="busy || progress.length" class="hw-progress-box center">
          <div v-for="(l, i) in progress" :key="i">{{ l }}</div>
          <div v-if="busy && !progress.length">· 正在理解需求…</div>
        </div>
        <PhoneStage :html="result ? result.phone_html : ''" :busy="busy && !result">
          <template #tools>
            <div class="hw-plat-wrap">
              <button class="hw-round" title="换平台" :disabled="busy || !result" @click="platOpen = !platOpen">换</button>
              <div v-if="platOpen" class="hw-side-sel">
                <label v-for="p in meta.manual_platforms" :key="p">
                  <input type="radio" name="platform" :checked="result && result.platform_label === p" @change="pickPlatform(p)" />
                  {{ p }}
                </label>
              </div>
            </div>
          </template>
        </PhoneStage>
        <div v-if="stopHtml" v-html="stopHtml"></div>
        <template v-if="result">
          <div v-if="result.talk_html" v-html="result.talk_html"></div>
          <div v-if="result.banner_html" v-html="result.banner_html"></div>
          <div class="actions">
            <button class="btn btn-ghost" :disabled="busy" @click="editAction('短一点')">短一点</button>
            <button class="btn btn-ghost" :disabled="busy" @click="editAction('换卖点')">换卖点</button>
            <button class="btn btn-ghost" :disabled="busy" @click="editAction('换个角度')">换个角度</button>
            <button class="btn btn-ghost" :disabled="busy" @click="allPlatforms">全平台</button>
          </div>
          <div class="copy-box">
            <textarea :value="copyBox" readonly spellcheck="false"></textarea>
            <div class="copy-row">
              <button class="btn btn-ghost" @click="copy">{{ copied ? '已复制 ✓' : '复制正文' }}</button>
              <button class="btn btn-ghost" @click="download">下载 .md</button>
            </div>
          </div>
          <div v-if="allHtml" class="all-platforms" v-html="allHtml"></div>
          <ReportFold :md="result.report_md" />
        </template>
        <div class="back-row"><button class="btn btn-ghost btn-sm" :disabled="busy" @click="backToInput">← 重新输入</button></div>
      </div>
    </transition>
  </div>
</template>
