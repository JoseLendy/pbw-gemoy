<script setup>
// 三店对比: one product, one platform, four fixed stores; stored set first, live run on request.
import { onMounted, ref, watch } from 'vue'
import { meta, metaReady, postJson, stream } from '../api.js'
const props = defineProps({ active: Boolean })
const model = ref('')
const platform = ref('朋友圈')
const html = ref('')
const summary = ref('')
const busy = ref(false)
const progress = ref([])
const EMPTY = '<div class="hw-empty-box">选择产品与平台后，点击「生成四店对比」查看四家门店的手机预览与跨店相似度。</div>'

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
  <div class="compare">
    <div class="view-intro">
      <h2>同一个产品，四家门店各自表达</h2>
      <p>固定 S01 紫金港店 / S04 钱江新城店 / S08 九堡店 / S02 下沙高教园店；产品与平台统一，客群、场景、角度、语气与地标保留各店差异。</p>
    </div>
    <div class="store-controls">
      <label class="field grow">
        <span class="field-label">产品（在售活动）</span>
        <select class="select" v-model="model">
          <option v-for="p in meta.compare_products" :key="p.model_id" :value="p.model_id">{{ p.display_name }}</option>
        </select>
      </label>
      <div class="field">
        <span class="field-label">平台</span>
        <div class="pills">
          <button v-for="p in meta.compare_platforms" :key="p" class="pill" :class="{ on: platform === p }" @click="platform = p">{{ p }}</button>
        </div>
      </div>
      <button class="btn btn-primary" :disabled="busy" @click="run">生成四店对比</button>
    </div>
    <div v-if="busy || progress.length" class="hw-progress-box" role="status" aria-live="polite">
      <div v-for="(l, i) in progress" :key="i">{{ l }}</div>
      <div v-if="busy && !progress.length">· 正在生成四店对比…</div>
    </div>
    <div v-if="summary" class="hw-banner note summary">{{ summary }}</div>
    <div class="compare-body" :class="{ 'is-busy': busy }" v-html="html || EMPTY"></div>
  </div>
</template>
