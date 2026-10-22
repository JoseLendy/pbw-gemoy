<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Building2, Columns3, FlaskConical, LogIn, MousePointerClick, Scale, Store } from 'lucide-vue-next'
import { account, engineer, loadMeta, meta, refreshStatus, status } from './api.js'
import HomeView from './views/HomeView.vue'
import ClickView from './views/ClickView.vue'
import HqView from './views/HqView.vue'
import LoginView from './views/LoginView.vue'
import CompareView from './views/CompareView.vue'
import BaselineView from './views/BaselineView.vue'

const NAV = [
  { key: 'home', label: '门店端', icon: Store },
  { key: 'click', label: '点击输入', icon: MousePointerClick },
  { key: 'hq', label: '总部端', icon: Building2 },
  { key: 'login', label: '登录', icon: LogIn },
]
const DEMO = [
  { key: 'compare', label: '四店对比', icon: Columns3 },
  { key: 'baseline', label: '对照组', icon: Scale },
]
const ALIASES = { store: 'home', manual: 'click' }   // old #tab= links keep working

function hashParams() {
  const h = (location.hash || '').replace(/^#/, '')
  const out = {}
  for (const kv of h.split('&')) { const [k, v] = kv.split('='); if (k) out[k] = decodeURIComponent(v || '') }
  return out
}
function allowed(key) {
  return NAV.some((n) => n.key === key) || (engineer.unlocked && DEMO.some((n) => n.key === key))
}
function fromHash() {
  const k = ALIASES[hashParams().tab] || hashParams().tab
  return allowed(k) ? k : 'home'
}

const tab = ref(fromHash())
const homeKey = ref(0)
let statusTimer = null

function go(key) { if (allowed(key)) tab.value = key }
function onReset() { homeKey.value++ }   // 重置演示: the store view remounts and reloads on next open
watch(tab, (key) => {
  window.scrollTo({ top: 0 })
  if (hashParams().tab !== key) history.replaceState(null, '', '#tab=' + key)
})
watch(() => engineer.unlocked, (on) => { if (!on && DEMO.some((n) => n.key === tab.value)) tab.value = 'login' })

const who = computed(() => {
  if (account.kind === 'hq') return { name: '总部运营', sub: '总部账号', mark: '总' }
  if (account.kind === 'store') return { name: account.store_name, sub: account.role, mark: (account.store_name || '店').slice(0, 1) }
  return { name: '未登录', sub: '演示账号', mark: '访' }
})
const kbTone = computed(() => (status.checking ? 'amber' : status.kb_ok ? 'ok' : 'bad'))

onMounted(async () => {
  window.addEventListener('hashchange', () => { const k = fromHash(); if (k !== tab.value) tab.value = k })
  await loadMeta()
  refreshStatus()
  statusTimer = setInterval(refreshStatus, 2000)
})
onBeforeUnmount(() => clearInterval(statusTimer))
</script>

<template>
  <a class="skip-link" href="#main">跳到主要内容</a>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">
        <img class="brand-logo" src="/logo.png" alt="HUAWEI" />
        <div>
          <div class="brand-name">PC 软文助手</div>
          <div class="brand-sub">演示日期 {{ meta.today || status.today || '…' }}</div>
        </div>
      </div>

      <nav class="nav" aria-label="主导航">
        <button v-for="n in NAV" :key="n.key" class="nav-item" :class="{ on: tab === n.key }"
                :aria-current="tab === n.key ? 'page' : undefined" @click="go(n.key)">
          <component :is="n.icon" :size="18" :stroke-width="1.9" aria-hidden="true" />
          <span>{{ n.label }}</span>
        </button>
        <template v-if="engineer.unlocked">
          <div class="nav-group"><FlaskConical :size="14" aria-hidden="true" />演示功能</div>
          <button v-for="n in DEMO" :key="n.key" class="nav-item" :class="{ on: tab === n.key }"
                  :aria-current="tab === n.key ? 'page' : undefined" @click="go(n.key)">
            <component :is="n.icon" :size="18" :stroke-width="1.9" aria-hidden="true" />
            <span>{{ n.label }}</span>
          </button>
        </template>
      </nav>

      <div class="side-foot">
        <button class="who" @click="go('login')">
          <span class="who-mark">{{ who.mark }}</span>
          <span class="who-text"><b>{{ who.name }}</b><small>{{ who.sub }}</small></span>
        </button>
        <details class="sys">
          <summary><span class="dot" :class="kbTone"></span>系统状态<span v-if="status.dev_mode" class="sys-dev">开发模式</span></summary>
          <dl>
            <dt>知识库</dt><dd>{{ status.kb_state || '…' }}</dd>
            <dt>索引</dt><dd>{{ status.index_label || '…' }}</dd>
            <dt>模型</dt><dd>{{ status.model || '未设置' }}</dd>
            <dt>密钥</dt><dd>{{ status.configured ? '已配置' : '未配置' }}</dd>
          </dl>
          <p v-if="status.dev_mode" class="sys-note">部分模块为模拟数据：{{ status.fake_fields.join('、') }}</p>
          <p v-if="status.error" class="sys-note err">{{ status.error }}</p>
          <p class="sys-note">知识库内容仅用于生成与核验，不提供原文浏览或批量导出。</p>
        </details>
      </div>
    </aside>

    <main id="main" class="main" tabindex="-1">
      <HomeView :key="homeKey" :active="tab === 'home'" v-show="tab === 'home'" @go="go" />
      <ClickView v-show="tab === 'click'" />
      <HqView :active="tab === 'hq'" v-show="tab === 'hq'" @reset="onReset" />
      <LoginView :active="tab === 'login'" v-show="tab === 'login'" @go="go" />
      <CompareView v-if="engineer.unlocked" :active="tab === 'compare'" v-show="tab === 'compare'" />
      <BaselineView v-if="engineer.unlocked" :active="tab === 'baseline'" v-show="tab === 'baseline'" />
    </main>

    <nav class="tabbar" aria-label="主导航">
      <button v-for="n in NAV" :key="n.key" class="tabbar-item" :class="{ on: tab === n.key }"
              :aria-current="tab === n.key ? 'page' : undefined" @click="go(n.key)">
        <component :is="n.icon" :size="20" :stroke-width="1.9" aria-hidden="true" />
        <span>{{ n.label }}</span>
      </button>
    </nav>
  </div>
</template>
