<script setup>
// 登录: choose a shop, then sign in with a username + password backed by the server's account database.
// The demo-account list signs in with one click (when the default demo password is in use). A successful
// login goes straight to 门店端; reopening the 登录 tab shows the 账号信息 page (门店 / 账号 / 退出登录).
// The role decides which pages show: staff → 门店端 + 生成; manager → those + 总部端 (and confirming new
// products for their own store); developer → everything, including the demo-only 四店对比 / 对照组.
import { computed, onMounted, ref, watch } from 'vue'
import { Check, KeyRound, LogOut, Search, Store } from 'lucide-vue-next'
import { account, demoAccounts, loadMeta, login, logout, meta } from '../api.js'
import { tintFor } from '../components/tints.js'

const props = defineProps({ active: Boolean })

const storeId = ref('')
const username = ref('')
const password = ref('')
const busy = ref(false)
const msg = ref('')
const pwEl = ref(null)
const demo = ref({ accounts: [], password: '' })
const chosen = computed(() => meta.stores.find((s) => s.store_id === storeId.value))
// A shop search: useful as soon as the chain has more stores than one screen of cards.
const query = ref('')
const filteredStores = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return meta.stores
  return meta.stores.filter((s) => [s.store_name, s.district, s.anchor, s.store_id]
    .some((v) => (v || '').toLowerCase().includes(q)))
})
const userHint = computed(() => {
  const s = storeId.value.toLowerCase()
  return s ? `例如 staff-${s} 或 manager-${s}` : '例如 staff-s01'
})

const groups = computed(() => {
  const out = []
  const byStore = new Map()
  for (const a of demo.value.accounts) {
    if (a.role === 'developer') continue
    if (!byStore.has(a.store_id)) {
      const known = meta.stores.find((s) => s.store_id === a.store_id) || {}
      byStore.set(a.store_id, { store_id: a.store_id, store_name: a.store_name || known.store_name || a.store_id, accounts: [] })
      out.push(byStore.get(a.store_id))
    }
    byStore.get(a.store_id).accounts.push(a)
  }
  // The demo list always shows one shop's 店员 + 店长 (plus the developer below): the picked shop, or
  // the first shop when none is picked, so it stays a compact three-account list for every sign-out.
  const pick = storeId.value || (meta.stores[0] && meta.stores[0].store_id) || ''
  return out.filter((g) => g.store_id === pick)
})
const devAccounts = computed(() => demo.value.accounts.filter((a) => a.role === 'developer'))

async function loadDemo() {
  if (!meta.stores.length) await loadMeta()
  demo.value = await demoAccounts()
}
onMounted(loadDemo)
watch(() => props.active, (on) => { if (on && !account.role) loadDemo() })

async function submit() {
  if (!username.value.trim() || !password.value || busy.value) return
  busy.value = true
  msg.value = ''
  try {
    const r = await login(username.value, password.value, storeId.value)
    if (r.ok) {
      password.value = ''
      msg.value = ''
      emit('go', 'home')   // a successful login (manual or demo) lands on the recommendation page
    } else {
      msg.value = r.reason || '登录失败'
    }
  } catch (e) {
    msg.value = e.message || '暂时无法登录，请稍后再试'
  }
  busy.value = false
}

/** One-click demo sign-in; without a known demo password it only fills the account field. */
async function quick(a) {
  if (busy.value) return
  storeId.value = a.store_id || ''
  username.value = a.username
  if (!demo.value.password) {
    msg.value = '请输入该账号的密码'
    pwEl.value && pwEl.value.focus()
    return
  }
  password.value = demo.value.password
  await submit()
}

async function signOut() {
  await logout()
  msg.value = ''
}

const roleLine = computed(() => {
  if (account.role === 'developer') return '全部页面 · 四店对比 · 对照组'
  if (account.role === 'manager') return '门店端 · 生成 · 总部端'
  if (account.role === 'staff') return '门店端 · 生成'
  return ''
})
</script>

<template>
  <div class="page page-with-head">
    <header class="page-head">
      <h1>{{ account.role ? '账号信息' : '登录' }}</h1>
      <p v-if="account.role">已登录。左侧菜单里的页面按你的身份开放。</p>
      <p v-else>选择门店，再输入账号和密码登录。不同身份看到的页面不同，店长可在总部端确认本店新品。</p>
    </header>

    <!-- signed in: just this account, the shop it belongs to, and a way out -->
    <div v-if="account.role" class="page-main">
      <section class="card" aria-labelledby="acct-title">
        <div class="card-head">
          <h2 id="acct-title">账号信息</h2>
          <span class="muted small">{{ account.role_label }}</span>
        </div>
        <div class="login-who">
          <span class="store-mark" :style="{ background: tintFor(account.store_id || 'hq').tile, color: tintFor(account.store_id || 'hq').ink }">
            {{ (account.store_name || account.display_name || '开').slice(0, 1) }}
          </span>
          <div>
            <b>{{ account.display_name || account.username }}</b>
            <div class="muted small">{{ roleLine }}</div>
          </div>
        </div>
        <dl class="acct-info">
          <dt>门店</dt><dd>{{ account.store_name || '全部门店' }}</dd>
          <dt>账号</dt><dd>{{ account.username }}</dd>
        </dl>
        <button class="btn btn-light btn-block" @click="signOut"><LogOut :size="16" aria-hidden="true" />退出登录</button>
      </section>
    </div>

    <template v-else>
      <div class="page-main">
        <section class="card" aria-labelledby="login-store">
          <div class="card-head">
            <h2 id="login-store">选择门店</h2>
            <span class="muted small">{{ filteredStores.length }} / {{ meta.stores.length }} 家门店</span>
          </div>
          <div class="login-search">
            <Search :size="16" aria-hidden="true" />
            <input v-model="query" class="input" type="search" placeholder="搜索门店名、区域或地标"
                   aria-label="搜索门店" autocomplete="off" spellcheck="false" />
          </div>
          <div class="store-scroll">
            <div class="store-grid" role="radiogroup" aria-labelledby="login-store">
              <button v-for="s in filteredStores" :key="s.store_id" class="store-opt" role="radio"
                      :aria-checked="storeId === s.store_id" :class="{ on: storeId === s.store_id }"
                      @click="storeId = s.store_id">
                <span class="store-mark" :style="{ background: tintFor(s.store_id).tile, color: tintFor(s.store_id).ink }">{{ s.store_name.slice(0, 1) }}</span>
                <span class="store-text"><b>{{ s.store_name }}</b><small>{{ s.district }}<template v-if="s.anchor"> · {{ s.anchor }}</template></small></span>
                <span class="opt-check" aria-hidden="true"><Check :size="14" :stroke-width="3" /></span>
              </button>
            </div>
            <p v-if="!filteredStores.length" class="muted small store-empty">没有匹配的门店，换个关键词试试。</p>
          </div>
          <p class="muted small">店员与店长必须选对本店；开发者账号不用选门店。</p>
        </section>

        <section class="card" aria-labelledby="login-form">
          <div class="card-head">
            <h2 id="login-form">账号登录</h2>
            <span class="muted small">{{ chosen ? chosen.store_name : '未选择门店' }}</span>
          </div>
          <form class="login-form" @submit.prevent="submit">
            <label class="field-label" for="login-user">账号</label>
            <input id="login-user" v-model="username" class="input" type="text" autocomplete="username"
                   :placeholder="userHint" spellcheck="false" />
            <label class="field-label" for="login-pass">密码</label>
            <div class="row">
              <input id="login-pass" ref="pwEl" v-model="password" class="input" type="password"
                     autocomplete="current-password" />
              <button class="btn btn-dark" :disabled="!username.trim() || !password || busy">
                {{ busy ? '正在登录…' : '登录' }}
              </button>
            </div>
            <p v-if="msg" class="field-msg" role="alert">{{ msg }}</p>
          </form>
        </section>

        <section class="card" aria-labelledby="login-demo">
          <div class="card-head">
            <h2 id="login-demo">演示账号</h2>
            <span class="muted small">点一下选好门店并登录</span>
          </div>
          <p v-if="demo.password" class="muted small">统一演示密码：<b>{{ demo.password }}</b></p>
          <p v-else class="muted small">管理员已自定义演示密码，请手动输入。</p>

          <div v-for="g in groups" :key="g.store_id" class="demo-store">
            <div class="demo-store-head"><Store :size="15" aria-hidden="true" /><b>{{ g.store_name }}</b></div>
            <div class="role-grid">
              <button v-for="a in g.accounts" :key="a.username" class="role-opt" :class="{ on: account.username === a.username }"
                      @click="quick(a)">
                <b>{{ a.role_label }}</b><small>{{ a.username }}</small>
              </button>
            </div>
          </div>

          <div v-if="devAccounts.length" class="demo-store">
            <div class="demo-store-head"><KeyRound :size="15" aria-hidden="true" /><b>开发者</b></div>
            <div class="role-grid">
              <button v-for="a in devAccounts" :key="a.username" class="role-opt" :class="{ on: account.username === a.username }"
                      @click="quick(a)">
                <b>{{ a.role_label }}</b><small>{{ a.username }} · 全部页面 + 演示功能</small>
              </button>
            </div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>
