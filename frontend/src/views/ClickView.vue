<script setup>
// 点击输入: two ways in. 点选 picks 产品 → 顾客 → 场景 → 平台 with pictures (the picks become one plain sentence for
// intake and answer any clarification themselves); 直接输入 takes one sentence typed by the clerk. Both share the
// result view: phone preview, quick edits, copy / download, report.
import { computed, reactive, ref } from 'vue'
import {
  ArrowLeft, ArrowRight, BookOpen, Briefcase, Check, Clapperboard, Copy, FileDown, Gift, GraduationCap,
  HeartHandshake, MessageSquareText, MousePointerClick, Palette, Pencil, RotateCcw, Shuffle, Sofa, Users,
} from 'lucide-vue-next'
import { cleanHtml, copyText, downloadUrl, meta, postJson, stream } from '../api.js'
import PhoneStage from '../components/PhoneStage.vue'
import PlatformThumb from '../components/PlatformThumb.vue'
import ProductArt from '../components/ProductArt.vue'
import ReportFold from '../components/ReportFold.vue'
import { tintFor } from '../components/tints.js'
import { typewrite } from '../components/typewriter.js'

const AUDIENCES = [
  { key: '大学生', phrase: '一位大学生', hint: '上课、宿舍、图书馆', icon: GraduationCap, tint: 'sky' },
  { key: '上班族', phrase: '一位上班族', hint: '通勤、会议、出差', icon: Briefcase, tint: 'lilac' },
  { key: '家长', phrase: '一位给孩子选电脑的家长', hint: '网课、作业、全家用', icon: Users, tint: 'mint' },
  { key: '送礼', phrase: '一位想送礼的顾客', hint: '送家人、朋友', icon: Gift, tint: 'rose' },
  { key: '创作者', phrase: '一位内容创作者', hint: '剪辑、设计、修图', icon: Palette, tint: 'peach' },
  { key: '长辈', phrase: '一位长辈', hint: '上手简单、看得清', icon: HeartHandshake, tint: 'butter' },
]
const SCENARIO_ART = {
  开学季: { icon: BookOpen, hint: '新生入学，换新电脑', tint: 'sky' },
  职场办公: { icon: Briefcase, hint: '办公效率，移动办公', tint: 'lilac' },
  内容创作: { icon: Clapperboard, hint: '剪辑设计，多任务', tint: 'peach' },
  家庭换新: { icon: Sofa, hint: '全家共用，旧机换新', tint: 'mint' },
}
const TINT_BG = { sky: '#E8F2FD', lilac: '#F1ECFB', mint: '#E6F5EE', rose: '#FDECF2', peach: '#FFEEE4', butter: '#FFF5DA' }
const TINT_INK = { sky: '#3569AD', lilac: '#6C55C2', mint: '#2C8564', rose: '#B54068', peach: '#C25A30', butter: '#946A0B' }

const STEPS = [
  { key: 'product', label: '产品', ask: '推荐哪款产品？' },
  { key: 'audience', label: '顾客', ask: '顾客是谁？' },
  { key: 'scenario', label: '场景', ask: '在什么场景下用？' },
  { key: 'platform', label: '平台', ask: '发到哪个平台？' },
]

const inputMode = ref('pick')     // 'pick' (点选) | 'type' (直接输入)
const stage = ref('input')        // 'input' | 'result'

// ---- 点选
const pick = reactive({ product: null, audience: null, scenario: null, platform: null })
const step = ref(0)
const dir = ref('fwd')            // step slide direction
// The catalog is empty when the local KB mirror is missing; fall back to the products in today's campaigns
// (store demo data) so the step still has something to pick. Intake resolves the name against the catalog again.
const products = computed(() => (meta.manual_products && meta.manual_products.length
  ? meta.manual_products
  : (meta.compare_products || []).map((p) => ({ model_id: p.model_id, name: p.display_name, route: '' }))))
const scenarios = computed(() => (meta.manual_scenarios && meta.manual_scenarios.length ? meta.manual_scenarios : Object.keys(SCENARIO_ART)))
const platforms = computed(() => meta.manual_platforms || [])
const complete = computed(() => STEPS.every((s) => pick[s.key]))
const current = computed(() => STEPS[step.value])

function valueLabel(key) {
  const v = pick[key]
  if (!v) return ''
  return key === 'product' ? v.name : key === 'audience' ? v.key : v
}
const sentence = computed(() => {
  if (!complete.value) return ''
  return `${pick.audience.phrase}顾客，${pick.scenario}，想买 ${pick.product.name}，发${pick.platform}`
})
function choose(key, value) { pick[key] = value }
function firstOpen() { const i = STEPS.findIndex((s) => !pick[s.key]); return i < 0 ? STEPS.length - 1 : i }
function goStep(i) { if (i <= firstOpen() && i !== step.value) { dir.value = i > step.value ? 'fwd' : 'back'; step.value = i } }
function next() { if (pick[current.value.key] && step.value < STEPS.length - 1) goStep(step.value + 1) }
function back() { if (step.value > 0) goStep(step.value - 1) }

// ---- 直接输入
const typed = ref('')
const EXAMPLES = computed(() => (meta.manual_examples.length ? meta.manual_examples : ['一位妈妈想给上大学的女儿买 DemoBook 14（演示版），发小红书']))
const exampleIndex = ref(0)
function shuffleExample() {
  if (EXAMPLES.value.length < 2) return
  let i = exampleIndex.value
  while (i === exampleIndex.value) i = Math.floor(Math.random() * EXAMPLES.value.length)
  exampleIndex.value = i
}

// ---- generation + result (the original manual pipeline)
const busy = ref(false)
const progress = ref([])
const result = ref(null)
const stopHtml = ref('')
const clarification = ref(null)
const clarAnswers = reactive({})
const copyBox = ref('')
const copied = ref(false)
const platOpen = ref(false)
const allHtml = ref('')
const lastText = ref('')          // the sentence sent to intake; a clarification follow-up must resend it unchanged
let cancelType = null
let followUp = null               // a clarification the picks already answer: resent once the stream ends

function formFromPicks() {
  return { product: pick.product.name, audience: pick.audience.key, scenario: pick.scenario, platform: pick.platform }
}

function handle(data) {
  if (!data) return
  if (data.kind === 'clarification') {
    const form = inputMode.value === 'pick' && complete.value ? formFromPicks() : {}
    const open = data.questions.filter((q) => !q.options.includes(form[q.slot]))
    if (inputMode.value === 'pick' && !open.length && !clarification.value) { clarification.value = { auto: true }; followUp = form; return }
    clarification.value = data
    for (const q of data.questions) clarAnswers[q.slot] = q.options.includes(form[q.slot]) ? form[q.slot] : q.options[0]
    return
  }
  if (data.kind === 'stop') { stopHtml.value = data.html; return }
  clarification.value = null
  result.value = data
  stopHtml.value = ''
  allHtml.value = ''
  platOpen.value = false
  if (cancelType) cancelType()
  cancelType = typewrite(data.pub_text || '', (t) => { copyBox.value = t }, { onDone: () => { cancelType = null } })
}

function onEvent(evt) {
  if (evt.event === 'progress') progress.value = [...progress.value, evt.message]
  else if (evt.event === 'done') handle(evt.data)
  else if (evt.event === 'error') stopHtml.value = `<div class="hw-stop">出错：${evt.message}</div>`
}
async function runPipeline(url, body) {
  busy.value = true
  progress.value = []
  stopHtml.value = ''
  try {
    await stream(url, body, onEvent)
    if (followUp) {
      const form = followUp
      followUp = null
      await stream('/api/manual/generate', { text: lastText.value, form }, onEvent)
    }
  } catch (e) {
    stopHtml.value = `<div class="hw-stop">出错：${e.message || '请求失败'}</div>`
  } finally {
    followUp = null
    busy.value = false
  }
}

async function start(text) {
  if (!text || busy.value) return
  lastText.value = text
  stage.value = 'result'
  result.value = null
  clarification.value = null
  copyBox.value = ''
  window.scrollTo({ top: 0 })
  await runPipeline('/api/manual/generate', { text })
}
const generate = () => { if (complete.value) start(sentence.value) }
const generateTyped = () => start(typed.value.trim())

function continueClarification() {
  const form = inputMode.value === 'pick' && complete.value ? formFromPicks() : {}
  for (const q of clarification.value.questions) form[q.slot] = clarAnswers[q.slot]
  clarification.value = { auto: true }
  runPipeline('/api/manual/generate', { text: lastText.value, form })
}
const editAction = (ins) => { if (!busy.value) runPipeline('/api/manual/edit', { instruction: ins }) }
function pickPlatform(label) {
  platOpen.value = false
  if (inputMode.value === 'pick') pick.platform = label
  editAction('换成' + label)
}
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
  if (!result.value) return
  await copyText(result.value.pub_text || copyBox.value)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
function download() { const a = document.createElement('a'); a.href = downloadUrl('/api/manual/download-md'); a.click() }
function edit(i) { if (busy.value) return; inputMode.value = 'pick'; stage.value = 'input'; dir.value = 'back'; step.value = i }
function backToInput() { if (!busy.value) stage.value = 'input' }
async function restart() {
  if (busy.value) return
  try { await postJson('/api/manual/reset') } catch { /* ignore */ }
  for (const k of Object.keys(pick)) pick[k] = null
  result.value = null; stopHtml.value = ''; clarification.value = null; copyBox.value = ''; allHtml.value = ''
  stage.value = 'input'; step.value = 0; dir.value = 'back'
}
</script>

<template>
  <div class="page">
    <div class="page-main">
      <header class="page-head">
        <h1>点击输入</h1>
        <p>点选或直接说一句，生成经知识库核验、可直接发布的平台软文。</p>
      </header>

      <div v-if="stage === 'input'" class="seg seg-lg" role="radiogroup" aria-label="输入方式">
        <button class="seg-item" role="radio" :aria-checked="inputMode === 'pick'" :class="{ on: inputMode === 'pick' }" @click="inputMode = 'pick'">
          <MousePointerClick :size="16" aria-hidden="true" />点选
        </button>
        <button class="seg-item" role="radio" :aria-checked="inputMode === 'type'" :class="{ on: inputMode === 'type' }" @click="inputMode = 'type'">
          <MessageSquareText :size="16" aria-hidden="true" />直接输入
        </button>
      </div>

      <Transition name="swap" mode="out-in">
        <!-- ============ 点选 ============ -->
        <div v-if="stage === 'input' && inputMode === 'pick'" key="pick" class="stack">
          <ol class="stepper" aria-label="步骤">
            <li v-for="(s, i) in STEPS" :key="s.key" :class="{ on: i === step, done: pick[s.key] && i !== step }">
              <button :disabled="i > firstOpen()" :aria-current="i === step ? 'step' : undefined" @click="goStep(i)">
                <span class="step-num"><Check v-if="pick[s.key] && i !== step" :size="14" :stroke-width="3" aria-hidden="true" /><template v-else>{{ i + 1 }}</template></span>
                <span class="step-label">{{ s.label }}</span>
              </button>
            </li>
          </ol>

          <section class="card pick-card" :aria-labelledby="'ask-' + current.key">
            <Transition :name="'step-' + dir" mode="out-in">
              <div :key="current.key">
                <h2 :id="'ask-' + current.key" class="pick-ask">{{ current.ask }}</h2>

                <div v-if="current.key === 'product'" class="opt-grid opt-grid-product" role="radiogroup" :aria-label="current.ask">
                  <button v-for="(p, i) in products" :key="p.model_id" class="opt opt-product" role="radio" :style="{ '--i': i }"
                          :aria-checked="!!pick.product && pick.product.model_id === p.model_id"
                          :class="{ on: pick.product && pick.product.model_id === p.model_id }" @click="choose('product', p)">
                    <span class="opt-tile" :style="{ background: tintFor(p.name).tile }"><ProductArt :name="p.name" /></span>
                    <span class="opt-name">{{ p.name }}</span>
                    <span v-if="p.route" class="opt-hint">{{ p.route === 'harmonyos' ? '鸿蒙版' : p.route === 'windows' ? 'Windows' : '资料以文字为主' }}</span>
                    <span class="opt-check" aria-hidden="true"><Check :size="14" :stroke-width="3" /></span>
                  </button>
                  <p v-if="!products.length" class="note warn">知识库产品目录为空：本地知识库镜像未加载。可以先用「直接输入」，或请队友拷贝知识库镜像后重启服务。</p>
                </div>

                <div v-else-if="current.key === 'audience'" class="opt-grid" role="radiogroup" :aria-label="current.ask">
                  <button v-for="(a, i) in AUDIENCES" :key="a.key" class="opt opt-icon" role="radio" :style="{ '--i': i }"
                          :aria-checked="!!pick.audience && pick.audience.key === a.key"
                          :class="{ on: pick.audience && pick.audience.key === a.key }" @click="choose('audience', a)">
                    <span class="opt-badge" :style="{ background: TINT_BG[a.tint], color: TINT_INK[a.tint] }"><component :is="a.icon" :size="28" :stroke-width="1.7" aria-hidden="true" /></span>
                    <span class="opt-name">{{ a.key }}</span>
                    <span class="opt-hint">{{ a.hint }}</span>
                    <span class="opt-check" aria-hidden="true"><Check :size="14" :stroke-width="3" /></span>
                  </button>
                </div>

                <div v-else-if="current.key === 'scenario'" class="opt-grid" role="radiogroup" :aria-label="current.ask">
                  <button v-for="(s, i) in scenarios" :key="s" class="opt opt-icon" role="radio" :style="{ '--i': i }" :aria-checked="pick.scenario === s"
                          :class="{ on: pick.scenario === s }" @click="choose('scenario', s)">
                    <span class="opt-badge" :style="{ background: TINT_BG[(SCENARIO_ART[s] || {}).tint || 'sky'], color: TINT_INK[(SCENARIO_ART[s] || {}).tint || 'sky'] }">
                      <component :is="(SCENARIO_ART[s] || {}).icon || BookOpen" :size="28" :stroke-width="1.7" aria-hidden="true" />
                    </span>
                    <span class="opt-name">{{ s }}</span>
                    <span class="opt-hint">{{ (SCENARIO_ART[s] || {}).hint || '' }}</span>
                    <span class="opt-check" aria-hidden="true"><Check :size="14" :stroke-width="3" /></span>
                  </button>
                </div>

                <div v-else class="opt-grid opt-grid-platform" role="radiogroup" :aria-label="current.ask">
                  <button v-for="(p, i) in platforms" :key="p" class="opt opt-platform" role="radio" :style="{ '--i': i }" :aria-checked="pick.platform === p"
                          :class="{ on: pick.platform === p }" @click="choose('platform', p)">
                    <span class="opt-thumb"><PlatformThumb :platform="p" /></span>
                    <span class="opt-name">{{ p }}</span>
                    <span class="opt-check" aria-hidden="true"><Check :size="14" :stroke-width="3" /></span>
                  </button>
                </div>
              </div>
            </Transition>

            <div class="pick-foot">
              <button class="btn btn-light" :disabled="step === 0" @click="back"><ArrowLeft :size="16" aria-hidden="true" />上一步</button>
              <button v-if="step < STEPS.length - 1" class="btn btn-dark btn-go" :disabled="!pick[current.key]" @click="next">下一步<ArrowRight :size="16" aria-hidden="true" /></button>
              <button v-else class="btn btn-dark btn-go" :disabled="!complete" @click="generate">生成软文<ArrowRight :size="16" aria-hidden="true" /></button>
            </div>
          </section>
        </div>

        <!-- ============ 直接输入 ============ -->
        <section v-else-if="stage === 'input'" key="type" class="card composer" aria-labelledby="type-title">
          <h2 id="type-title" class="pick-ask">顾客想要什么？</h2>
          <label class="field-label" for="type-text">用一句话描述：产品、顾客或场景、发到哪个平台</label>
          <textarea id="type-text" v-model="typed" class="textarea composer-text" rows="3" spellcheck="false"
                    placeholder="例如：一位妈妈想给上大学的女儿买 DemoBook 14（演示版），发小红书"
                    @keydown.enter.exact.prevent="generateTyped"></textarea>
          <div class="composer-foot">
            <div class="examples">
              <span class="field-label">试试</span>
              <Transition name="swap" mode="out-in">
                <button :key="exampleIndex" class="chip" @click="typed = EXAMPLES[exampleIndex]">{{ EXAMPLES[exampleIndex] }}</button>
              </Transition>
              <button v-if="EXAMPLES.length > 1" class="round round-sm" title="换一个例子" aria-label="换一个例子" @click="shuffleExample"><Shuffle :size="15" aria-hidden="true" /></button>
            </div>
            <button class="btn btn-dark btn-go" :disabled="!typed.trim() || busy" @click="generateTyped">生成软文<ArrowRight :size="16" aria-hidden="true" /></button>
          </div>
          <p class="muted small">按 Enter 生成，Shift + Enter 换行。缺少的信息会再请你点选补充。</p>
        </section>

        <!-- ============ result ============ -->
        <section v-else key="result" class="card result" aria-labelledby="click-result-title">
          <div class="card-head">
            <h2 id="click-result-title">文案预览</h2>
            <span v-if="inputMode === 'pick'" class="muted small">{{ valueLabel('product') }} · {{ pick.platform }}</span>
            <span v-else-if="result" class="muted small">{{ result.platform_label }}</span>
          </div>
          <div v-if="busy || progress.length" class="progress-list" role="status" aria-live="polite">
            <div v-for="(l, i) in progress" :key="i">{{ l }}</div>
            <div v-if="busy && !progress.length">正在理解需求…</div>
          </div>

          <div v-if="clarification && !clarification.auto" class="clar">
            <b>还需要确认一点：</b>
            <div v-for="q in clarification.questions" :key="q.slot" class="clar-q">
              <div class="clar-text">{{ q.text }}</div>
              <div class="chip-row">
                <button v-for="o in q.options" :key="o" class="chip" :class="{ on: clarAnswers[q.slot] === o }" @click="clarAnswers[q.slot] = o">{{ o }}</button>
              </div>
            </div>
            <div class="row end"><button class="btn btn-dark" :disabled="busy" @click="continueClarification">继续生成</button></div>
          </div>
          <div v-if="stopHtml" class="server-html" v-html="cleanHtml(stopHtml)"></div>

          <div class="result-grid">
            <PhoneStage :html="result ? result.phone_html : ''" :busy="busy && !result">
              <template #tools>
                <div class="plat-wrap">
                  <button class="round" title="换平台" aria-label="换平台" aria-haspopup="true" :aria-expanded="platOpen" :disabled="busy || !result" @click="platOpen = !platOpen">换</button>
                  <div v-if="platOpen" class="plat-menu">
                    <label v-for="p in platforms" :key="p">
                      <input type="radio" name="click-platform" :checked="result && result.platform_label === p" @change="pickPlatform(p)" />{{ p }}
                    </label>
                  </div>
                </div>
              </template>
            </PhoneStage>
            <div v-if="result" class="result-side">
              <div class="quick">
                <span class="field-label">快速调整</span>
                <div class="chip-row">
                  <button class="chip" :disabled="busy" @click="editAction('短一点')">短一点</button>
                  <button class="chip" :disabled="busy" @click="editAction('换卖点')">换卖点</button>
                  <button class="chip" :disabled="busy" @click="editAction('换个角度')">换个角度</button>
                  <button class="chip" :disabled="busy" @click="allPlatforms">全平台</button>
                </div>
              </div>
              <div v-if="result.banner_html" class="server-html" v-html="cleanHtml(result.banner_html)"></div>
              <div class="editor">
                <label class="field-label" for="click-copy">正文</label>
                <textarea id="click-copy" class="textarea" :value="copyBox" readonly rows="10" spellcheck="false"></textarea>
              </div>
              <div class="row wrap">
                <button class="btn btn-dark" @click="copy"><component :is="copied ? Check : Copy" :size="16" aria-hidden="true" />{{ copied ? '已复制' : '复制正文' }}</button>
                <button class="btn btn-light" @click="download"><FileDown :size="16" aria-hidden="true" />下载 .md</button>
              </div>
            </div>
          </div>
          <div v-if="allHtml" class="all-platforms" v-html="cleanHtml(allHtml)"></div>
          <ReportFold v-if="result" :md="result.report_md" />
        </section>
      </Transition>
    </div>

    <aside class="page-aside" aria-label="你的输入">
      <section v-if="inputMode === 'pick'" class="card summary">
        <h3 class="aside-title">你的选择</h3>
        <ul class="summary-list">
          <li v-for="(s, i) in STEPS" :key="s.key" :class="{ empty: !pick[s.key] }">
            <span class="summary-step">{{ s.label }}</span>
            <Transition name="swap" mode="out-in"><span :key="valueLabel(s.key)" class="summary-value">{{ valueLabel(s.key) || '未选择' }}</span></Transition>
            <button v-if="pick[s.key]" class="link" :disabled="busy" :aria-label="'修改' + s.label" @click="edit(i)"><Pencil :size="14" aria-hidden="true" />修改</button>
          </li>
        </ul>
        <p v-if="sentence" class="summary-sentence">{{ sentence }}</p>
        <p v-else class="muted small">选完四项后即可生成。</p>
        <button v-if="stage === 'input'" class="btn btn-dark btn-block btn-lg btn-go" :disabled="!complete || busy" @click="generate">生成软文<ArrowRight :size="18" aria-hidden="true" /></button>
        <button v-else class="btn btn-light btn-block" :disabled="busy" @click="restart"><RotateCcw :size="16" aria-hidden="true" />重新选择</button>
        <p class="muted small">内容只取自知识库，生成后自动核验产品事实与图片。</p>
      </section>

      <section v-else class="card summary">
        <h3 class="aside-title">{{ stage === 'result' ? '你的输入' : '怎么写更准' }}</h3>
        <template v-if="stage === 'result'">
          <p class="summary-sentence">{{ lastText }}</p>
          <button class="btn btn-light btn-block" :disabled="busy" @click="backToInput"><Pencil :size="16" aria-hidden="true" />改一改再生成</button>
        </template>
        <ul v-else class="tips">
          <li><b>产品</b>写型号全名，例如 DemoBook 14</li>
          <li><b>顾客</b>是谁，或在什么场景用</li>
          <li><b>平台</b>小红书、朋友圈、公众号、海报或抖音</li>
        </ul>
        <p class="muted small">内容只取自知识库，生成后自动核验产品事实与图片。</p>
      </section>

      <Transition name="swap">
        <section v-if="result && result.talk_html && !busy" class="card server-html" v-html="cleanHtml(result.talk_html)"></section>
      </Transition>
    </aside>
  </div>
</template>
