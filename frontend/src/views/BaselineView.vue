<script setup>
// 对照组: the labelled, unverified single-shot baseline (left) vs our verified result (right).
import { computed, onMounted, ref, watch } from 'vue'
import { marked } from 'marked'
import { meta, metaReady, postJson, stream } from '../api.js'
const props = defineProps({ active: Boolean })
const store = ref('')
const left = ref('')
const right = ref('')
const metaLine = ref('')
const busy = ref(false)
const progress = ref([])
const EMPTY_LEFT = '<div class="hw-empty-box">点击「生成对照」查看普通模型输出</div>'
const EMPTY_RIGHT = '<div class="hw-empty-box">点击「生成对照」查看我们经过核验的结果</div>'
const metaHtml = computed(() => (metaLine.value ? marked.parseInline(metaLine.value) : ''))

function ensureStore() { if (!store.value && meta.stores.length) store.value = meta.stores[0].store_id }
async function showStored() {
  await metaReady
  ensureStore()
  try {
    const r = await postJson('/api/baseline/stored', { store_id: store.value })
    left.value = r.left || EMPTY_LEFT
    right.value = r.right || EMPTY_RIGHT
    metaLine.value = r.meta || ''
  } catch {
    left.value = EMPTY_LEFT
    right.value = EMPTY_RIGHT
  }
}
async function run() {
  if (busy.value) return
  ensureStore()
  busy.value = true
  progress.value = []
  try {
    await stream('/api/baseline/run', { store_id: store.value }, (evt) => {
      if (evt.event === 'progress') progress.value = [...progress.value, evt.message]
      else if (evt.event === 'partial' || evt.event === 'result') {
        left.value = evt.left || EMPTY_LEFT
        right.value = evt.right || EMPTY_RIGHT
        metaLine.value = evt.meta || ''
      } else if (evt.event === 'error') progress.value = [...progress.value, '出错：' + evt.message]
    })
  } catch (e) { progress.value = [...progress.value, '出错：' + (e.message || '请求失败')] }
  finally { busy.value = false }
}
watch(() => props.active, (on) => { if (on) showStored() })
watch(store, () => { if (props.active) showStored() })
onMounted(() => { if (props.active) showStored() })
</script>

<template>
  <div class="baseline">
    <div class="view-intro">
      <h2>对照组：普通大模型 vs 我们的核验流程</h2>
      <p>选一家门店的今日一条，左边是一次普通生成，右边是经过知识库核验的结果。对照组始终明确标注，绝不作为门店可用文案。</p>
    </div>
    <div class="store-controls">
      <label class="field grow">
        <span class="field-label">门店</span>
        <select class="select" v-model="store">
          <option v-for="s in meta.stores" :key="s.store_id" :value="s.store_id">{{ s.store_name }}</option>
        </select>
      </label>
      <button class="btn btn-primary" :disabled="busy" @click="run">生成对照</button>
    </div>
    <div v-if="busy || progress.length" class="hw-progress-box" role="status" aria-live="polite">
      <div v-for="(l, i) in progress" :key="i">{{ l }}</div>
      <div v-if="busy && !progress.length">· 正在生成对照…</div>
    </div>
    <div v-if="metaLine" class="hw-banner note summary" v-html="metaHtml"></div>
    <div class="baseline-grid">
      <div class="baseline-col" v-html="left || EMPTY_LEFT"></div>
      <div class="baseline-col" v-html="right || EMPTY_RIGHT"></div>
    </div>
  </div>
</template>
