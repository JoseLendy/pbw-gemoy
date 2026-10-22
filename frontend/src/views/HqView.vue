<script setup>
// 总部端: posting, weekly plan and today's distribution on the left; the new-product gate, frequent
// questions and the demo reset on the right.
import { onMounted, ref, watch } from 'vue'
import { RotateCcw, ShieldCheck } from 'lucide-vue-next'
import { cleanHtml, getJson, postJson } from '../api.js'

const props = defineProps({ active: Boolean })
const emit = defineEmits(['reset'])
const d = ref(null)
const confirmReset = ref(false)
async function load() { try { d.value = await getJson('/api/hq/view') } catch { /* keep */ } }
async function verify() { try { d.value = await postJson('/api/hq/verify') } catch { /* keep */ } }
async function reset() {
  confirmReset.value = false
  try { d.value = await postJson('/api/hq/reset'); emit('reset') } catch { /* keep */ }
}
watch(() => props.active, (on) => { if (on) load() })
onMounted(() => { if (props.active) load() })
</script>

<template>
  <div class="page page-wide-aside page-with-head">
    <header class="page-head">
      <h1>总部端</h1>
      <p>各门店发布情况、本周计划与今日推荐分布。</p>
    </header>

    <div class="page-main">
      <template v-if="d">
        <section class="card">
          <div class="card-head"><h2>发布情况</h2></div>
          <div class="table-host" v-html="d.posting"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>本周计划</h2></div>
          <div class="table-host" v-html="d.plan"></div>
        </section>
        <section class="card">
          <div class="card-head"><h2>推荐分布</h2><span class="muted small">今日一条</span></div>
          <div class="table-host" v-html="d.distribution"></div>
        </section>
      </template>
      <p v-else class="muted">正在加载…</p>
    </div>

    <aside v-if="d" class="page-aside" aria-label="审核与工具">
      <section class="card">
        <h3 class="aside-title">新品上市审核<span class="tag">演示</span></h3>
        <div class="table-host" v-html="d.release"></div>
        <button v-if="d.has_draft" class="btn btn-dark btn-block" @click="verify"><ShieldCheck :size="16" aria-hidden="true" />确认发布</button>
        <div v-if="d.verify_msg" class="server-html" v-html="cleanHtml(d.verify_msg)"></div>
      </section>
      <section class="card">
        <h3 class="aside-title">顾客高频问题</h3>
        <div class="table-host" v-html="d.questions"></div>
      </section>
      <section class="card">
        <h3 class="aside-title">重置演示</h3>
        <p class="muted small">重置新品状态、门店推荐、已发布标记与顾客提问。已准备的内容保留。</p>
        <button v-if="!confirmReset" class="btn btn-light btn-block" @click="confirmReset = true"><RotateCcw :size="16" aria-hidden="true" />重置演示</button>
        <div v-else class="row">
          <button class="btn btn-danger" @click="reset">确认重置</button>
          <button class="btn btn-light" @click="confirmReset = false">取消</button>
        </div>
        <div v-if="d.reset_msg" class="server-html" v-html="cleanHtml(d.reset_msg)"></div>
      </section>
    </aside>
  </div>
</template>
