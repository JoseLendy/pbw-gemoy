<script setup>
// 登录: a demo account picker (no password) — a store account with a role, or the HQ account. The right
// column holds the engineer entry that unlocks the demo-only views.
import { computed, ref, watch } from 'vue'
import { ArrowRight, Building2, Check, Columns3, KeyRound, LockKeyhole, Scale, Store } from 'lucide-vue-next'
import { account, engineer, lockEngineer, meta, postJson, setAccount, unlockEngineer } from '../api.js'
import { tintFor } from '../components/tints.js'

const props = defineProps({ active: Boolean })
const emit = defineEmits(['go'])

const ROLES = [
  { key: '店员', hint: '日常推荐与发布，全部平台都能生成' },
  { key: '店长', hint: '负责门店账号，全部平台都能生成' },
]
const kind = ref(account.kind || 'store')
const storeId = ref(account.store_id || '')
const role = ref(account.role || '店员')
watch(() => props.active, (on) => { if (on) { kind.value = account.kind || 'store'; storeId.value = account.store_id || storeId.value } })
const chosen = computed(() => meta.stores.find((s) => s.store_id === storeId.value))
const busy = ref(false)

async function enter() {
  if (kind.value === 'hq') { setAccount({ kind: 'hq', store_id: '', store_name: '' }); emit('go', 'hq'); return }
  if (!chosen.value) return
  busy.value = true
  try {
    await postJson('/api/store/select', { store_id: chosen.value.store_id })
    await postJson('/api/store/role', { role: role.value })
  } catch { /* the home view applies the account again when it opens */ }
  setAccount({ kind: 'store', store_id: chosen.value.store_id, store_name: chosen.value.store_name, role: role.value })
  busy.value = false
  emit('go', 'home')
}

const code = ref('')
const codeMsg = ref('')
const unlocking = ref(false)
async function unlock() {
  if (!code.value || unlocking.value) return
  unlocking.value = true
  codeMsg.value = ''
  try {
    const r = await unlockEngineer(code.value)
    codeMsg.value = r.ok ? '' : r.reason || '口令不正确'
    if (r.ok) code.value = ''
  } catch { codeMsg.value = '暂时无法验证，请稍后再试' }
  unlocking.value = false
}
</script>

<template>
  <div class="page page-with-head page-with-tools">
    <header class="page-head">
      <h1>登录</h1>
      <p>选择演示账号，无需密码。</p>
    </header>

    <div class="seg seg-lg page-tools" role="radiogroup" aria-label="账号类型">
      <button class="seg-item" role="radio" :aria-checked="kind === 'store'" :class="{ on: kind === 'store' }" @click="kind = 'store'"><Store :size="16" aria-hidden="true" />门店账号</button>
      <button class="seg-item" role="radio" :aria-checked="kind === 'hq'" :class="{ on: kind === 'hq' }" @click="kind = 'hq'"><Building2 :size="16" aria-hidden="true" />总部账号</button>
    </div>

    <div class="page-main">
      <template v-if="kind === 'store'">
        <section class="card" aria-labelledby="login-store">
          <div class="card-head"><h2 id="login-store">选择门店</h2><span class="muted small">{{ meta.stores.length }} 家门店</span></div>
          <div class="store-grid" role="radiogroup" aria-labelledby="login-store">
            <button v-for="s in meta.stores" :key="s.store_id" class="store-opt" role="radio" :aria-checked="storeId === s.store_id"
                    :class="{ on: storeId === s.store_id }" @click="storeId = s.store_id">
              <span class="store-mark" :style="{ background: tintFor(s.store_id).tile, color: tintFor(s.store_id).ink }">{{ s.store_name.slice(0, 1) }}</span>
              <span class="store-text"><b>{{ s.store_name }}</b><small>{{ s.district }}<template v-if="s.anchor"> · {{ s.anchor }}</template></small></span>
              <span class="opt-check" aria-hidden="true"><Check :size="14" :stroke-width="3" /></span>
            </button>
          </div>
        </section>

        <section class="card" aria-labelledby="login-role">
          <div class="card-head"><h2 id="login-role">身份</h2></div>
          <div class="role-grid" role="radiogroup" aria-labelledby="login-role">
            <button v-for="r in ROLES" :key="r.key" class="role-opt" role="radio" :aria-checked="role === r.key" :class="{ on: role === r.key }" @click="role = r.key">
              <b>{{ r.key }}</b><small>{{ r.hint }}</small>
            </button>
          </div>
        </section>

        <div class="row">
          <button class="btn btn-dark btn-lg" :disabled="!chosen || busy" @click="enter">进入门店端<ArrowRight :size="18" aria-hidden="true" /></button>
          <span v-if="!chosen" class="muted small">先选择一家门店</span>
        </div>
      </template>

      <template v-else>
        <section class="card hq-login">
          <span class="store-mark big" :style="{ background: tintFor('hq').tile, color: tintFor('hq').ink }"><Building2 :size="26" aria-hidden="true" /></span>
          <div>
            <h2>总部运营</h2>
            <p class="muted">查看各门店发布情况、审核新品上市资料、汇总顾客高频问题。</p>
          </div>
        </section>
        <div class="row"><button class="btn btn-dark btn-lg" @click="enter">进入总部端<ArrowRight :size="18" aria-hidden="true" /></button></div>
      </template>
    </div>

    <aside class="page-aside" aria-label="工程师入口">
      <section class="card">
        <h3 class="aside-title">当前账号</h3>
        <p v-if="account.kind === 'store'"><b>{{ account.store_name }}</b> · {{ account.role }}</p>
        <p v-else-if="account.kind === 'hq'"><b>总部运营</b></p>
        <p v-else class="muted">尚未选择账号，门店端默认显示第一家门店。</p>
      </section>

      <section class="card">
        <h3 class="aside-title"><KeyRound :size="16" aria-hidden="true" />工程师入口</h3>
        <template v-if="!engineer.unlocked">
          <p class="muted small">四店对比与对照组仅供工程师调试和评审演示。</p>
          <form class="code-form" @submit.prevent="unlock">
            <label class="field-label" for="eng-code">口令</label>
            <div class="row">
              <input id="eng-code" v-model="code" class="input" type="password" autocomplete="off" :aria-invalid="!!codeMsg" aria-describedby="eng-msg" />
              <button class="btn btn-dark" :disabled="!code || unlocking">解锁</button>
            </div>
            <p id="eng-msg" class="field-msg" role="alert">{{ codeMsg }}</p>
          </form>
        </template>
        <template v-else>
          <p class="muted small">已解锁，可以打开下面两个演示功能。</p>
          <button class="card-link inset" @click="emit('go', 'compare')"><span><Columns3 :size="16" aria-hidden="true" /><b>四店对比</b></span><ArrowRight :size="16" aria-hidden="true" /></button>
          <button class="card-link inset" @click="emit('go', 'baseline')"><span><Scale :size="16" aria-hidden="true" /><b>对照组</b></span><ArrowRight :size="16" aria-hidden="true" /></button>
          <button class="btn btn-light btn-block" @click="lockEngineer"><LockKeyhole :size="16" aria-hidden="true" />锁定</button>
        </template>
      </section>
    </aside>
  </div>
</template>
