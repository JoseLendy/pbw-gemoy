<script setup>
// 总部端: offline panels + the demo new-product gate (确认发布) and 重置演示.
import { onMounted, ref, watch } from 'vue'
import { getJson, postJson } from '../api.js'
import Panel from '../components/Panel.vue'
const props = defineProps({ active: Boolean })
const emit = defineEmits(['reset'])
const d = ref(null)
const confirmReset = ref(false)
async function load() { try { d.value = await getJson('/api/hq/view') } catch { /* keep */ } }
async function verify() { try { d.value = await postJson('/api/hq/verify') } catch { /* keep */ } }
async function reset() {
  confirmReset.value = false
  try {
    d.value = await postJson('/api/hq/reset')
    emit('reset')
  } catch { /* keep */ }
}
watch(() => props.active, (on) => { if (on) load() })
onMounted(() => { if (props.active) load() })
</script>

<template>
  <div class="hq">
    <div class="view-intro">
      <h2>总部视图</h2>
      <p>发布情况、新品审核、顾客问题、本周计划与推荐分布。</p>
    </div>
    <template v-if="d">
      <div class="hq-grid">
        <Panel title="发布情况"><div class="table-host" v-html="d.posting"></div></Panel>
        <Panel title="顾客高频问题"><div class="table-host" v-html="d.questions"></div></Panel>
        <Panel title="演示：模拟新品上市审核流程">
          <div class="table-host" v-html="d.release"></div>
          <div class="btn-row">
            <button v-if="d.has_draft" class="btn btn-primary" @click="verify">确认发布</button>
          </div>
          <div v-if="d.verify_msg" v-html="d.verify_msg"></div>
        </Panel>
        <Panel title="本周计划"><div class="table-host" v-html="d.plan"></div></Panel>
      </div>
      <Panel title="推荐分布（今日一条）"><div class="table-host" v-html="d.distribution"></div></Panel>
      <Panel class="reset-panel">
        <div class="btn-row">
          <button v-if="!confirmReset" class="btn btn-ghost" @click="confirmReset = true">重置演示</button>
          <template v-else>
            <span class="muted">重置新品状态、门店推荐、已发布标记与顾客提问（已准备的内容保留）。</span>
            <button class="btn btn-danger" @click="reset">确认重置</button>
            <button class="btn btn-ghost" @click="confirmReset = false">取消</button>
          </template>
        </div>
        <div v-if="d.reset_msg" v-html="d.reset_msg"></div>
      </Panel>
    </template>
  </div>
</template>
