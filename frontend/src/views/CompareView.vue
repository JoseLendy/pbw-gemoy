<script setup>
// 四店对比 (engineer demo): one product, one platform, four fixed stores; stored set first, live run on request.
import { onMounted, ref, watch } from 'vue'
import { ArrowRight } from 'lucide-vue-next'
import { cleanHtml, meta, metaReady, postJson, stream } from '../api.js'
const props = defineProps({ active: Boolean })
const model = ref('')
const platform = ref('朋友圈')
const html = ref('')
const summary = ref('')
const busy = ref(false)
const progress = ref([])
const EMPTY = '<div class="empty-box">选择产品与平台后，点击「生成四店对比」查看四家门店的手机预览与跨店相似度。</div>'

function ensureModel() { if (!model.value && meta.compare_products.length) model.value = meta.compare_products[0].model_id }
async function showStored() {
  await metaReady
  ensureModel()
  try {
    const r = await postJson('/api/compare/stored', { model_id: model.value, platform: platform.value })
    html.value = r.html || EMPTY
    summary.value = r.summary || ''
  } catch { html.value = EMPTY }
}
async function run() {
  if (busy.value) return
  ensureModel()
  busy.value = true
  progress.value = []
  try {
    await stream('/api/compare/run', { model_id: model.value, platform: platform.value }, (evt) => {
      if (evt.event === 'progress') progress.value = [...progress.value, evt.message]
      else if (evt.event === 'result') { html.value = evt.html || EMPTY; summary.value = evt.summary || '' }
      else if (evt.event === 'error') progress.value = [...progress.value, '出错：' + evt.message]
    })
  } catch (e) { progress.value = [...progress.value, '出错：' + (e.message || '请求失败')] }
  finally { busy.value = false }
}
watch(() => props.active, (on) => { if (on) showStored() })
watch([model, platform], () => { if (props.active) showStored() })
onMounted(() => { if (props.active) showStored() })
</script>

<template>
  <div class="page page-full">
    <div class="page-main">
      <header class="page-head">
        <h1>四店对比<span class="tag">演示功能</span></h1>
        <p>同一产品、同一平台，固定 S01 紫金港店 / S04 钱江新城店 / S08 九堡店 / S02 下沙高教园店；客群、场景、角度、语气与地标保留各店差异。</p>
      </header>
      <div class="card toolbar">
        <label class="field grow">
          <span class="field-label">产品（在售活动）</span>
          <select v-model="model" class="select">
            <option v-for="p in meta.compare_products" :key="p.model_id" :value="p.model_id">{{ p.display_name }}</option>
          </select>
        </label>
        <div class="field">
          <span class="field-label">平台</span>
          <div class="seg" role="radiogroup" aria-label="平台">
            <button v-for="p in meta.compare_platforms" :key="p" class="seg-item" role="radio" :aria-checked="platform === p" :class="{ on: platform === p }" @click="platform = p">{{ p }}</button>
          </div>
        </div>
        <button class="btn btn-dark" :disabled="busy" @click="run">生成四店对比<ArrowRight :size="16" aria-hidden="true" /></button>
      </div>
      <div v-if="busy || progress.length" class="progress-list" role="status" aria-live="polite">
        <div v-for="(l, i) in progress" :key="i">{{ l }}</div>
        <div v-if="busy && !progress.length">正在生成四店对比…</div>
      </div>
      <div v-if="summary" class="note info">{{ summary }}</div>
      <div class="compare-body" :class="{ 'is-busy': busy }" v-html="cleanHtml(html || EMPTY)"></div>
    </div>
  </div>
</template>
