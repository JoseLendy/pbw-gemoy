<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { loadMeta, meta, refreshStatus, status } from './api.js'
import StoreView from './views/StoreView.vue'
import CompareView from './views/CompareView.vue'
import HqView from './views/HqView.vue'
import BaselineView from './views/BaselineView.vue'
import ManualView from './views/ManualView.vue'

const TABS = [
  { key: 'store', label: '门店端·今日推荐' },
  { key: 'compare', label: '三店对比' },
  { key: 'hq', label: '总部端' },
  { key: 'baseline', label: '对照组' },
  { key: 'manual', label: '手动输入' },
]
function hashParams() {
  const h = (location.hash || '').replace(/^#/, '')
  const out = {}
  for (const kv of h.split('&')) { const [k, v] = kv.split('='); if (k) out[k] = decodeURIComponent(v || '') }
  return out
}
const initial = hashParams()
const tab = ref(TABS.some((t) => t.key === initial.tab) ? initial.tab : 'store')
const storeKey = ref(0)
let statusTimer = null

function onReset() { storeKey.value++ }   // 重置演示: the store view remounts and reloads on next open

onMounted(async () => {
  window.addEventListener('hashchange', () => { const p = hashParams(); if (TABS.some((t) => t.key === p.tab)) tab.value = p.tab })
  await loadMeta()
  refreshStatus()
  statusTimer = setInterval(refreshStatus, 2000)
})
onBeforeUnmount(() => clearInterval(statusTimer))
</script>

<template>
  <video class="hw-bg-video" autoplay muted loop playsinline src="/background.mp4"></video>
  <div class="hw-page">
    <header class="hw-top">
      <div class="hw-brand">
        <img class="hw-brand-logo" src="/logo.png" alt="HUAWEI" />
        <div>
          <div class="hw-brand-title">华为 PC 图文软文 Agent</div>
          <div class="hw-brand-sub">演示日期：{{ meta.today || status.today || '…' }}</div>
        </div>
      </div>
      <nav class="hw-tabs" role="tablist">
        <button v-for="t in TABS" :key="t.key" class="hw-tab" :class="{ on: tab === t.key }" role="tab" :aria-selected="tab === t.key" @click="tab = t.key">{{ t.label }}</button>
      </nav>
    </header>

    <main class="hw-main">
      <StoreView :key="storeKey" :active="tab === 'store'" v-show="tab === 'store'" />
      <CompareView :active="tab === 'compare'" v-show="tab === 'compare'" />
      <HqView :active="tab === 'hq'" v-show="tab === 'hq'" @reset="onReset" />
      <BaselineView :active="tab === 'baseline'" v-show="tab === 'baseline'" />
      <ManualView v-show="tab === 'manual'" />
    </main>

    <footer class="hw-foot-row"><div class="hw-status">
      <span class="hw-chip"><span class="hw-label">知识库：</span><span :class="status.checking ? 'hw-amber' : (status.kb_ok ? 'hw-ok' : 'hw-bad')">{{ status.kb_name }}（{{ status.kb_state || '…' }}）</span></span>
      <span class="hw-chip"><span class="hw-label">索引：</span><span :class="{ complete: 'hw-ok', partial: 'hw-amber', checking: 'hw-amber' }[status.index_status] || 'hw-bad'">{{ status.index_label || '…' }}</span></span>
      <span class="hw-chip"><span class="hw-label">模型：</span><span>{{ status.model || '未设置' }}</span></span>
      <span class="hw-chip"><span class="hw-label">密钥：</span><span :class="status.configured ? 'hw-ok' : 'hw-bad'">{{ status.configured ? '已配置 ✓' : '未配置' }}</span></span>
      <span v-if="status.dev_mode" class="hw-chip hw-dev-chip">开发模式：部分模块为模拟数据（{{ status.fake_fields.join('、') }}）</span>
      <span v-if="status.error" class="hw-chip hw-bad">{{ status.error }}</span>
    </div>

    <div class="hw-footer">知识库内容仅用于生成与核验，不提供原文浏览或批量导出。密钥仅存于环境变量。</div></footer>
  </div>
</template>
