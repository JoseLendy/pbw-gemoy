<script setup>
// 手机发布: the current store post as plain text + plain images, for a phone browser (long-press to save).
import { onMounted, ref, watch } from 'vue'
import { copyText, postJson } from '../api.js'
import Panel from '../components/Panel.vue'
const props = defineProps({ active: Boolean })
const data = ref(null)
const copied = ref(false)
async function load() { try { data.value = await postJson('/api/mobile/view') } catch { /* keep */ } }
async function copy() {
  if (data.value && data.value.ok) {
    await copyText(data.value.text)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  }
}
watch(() => props.active, (on) => { if (on) load() })
onMounted(() => { if (props.active) load() })
</script>

<template>
  <div class="mobile">
    <Panel class="mobile-card">
      <p class="muted">在手机上打开本页：先复制文案，再长按每张图片 → 保存图片。</p>
      <template v-if="data && data.ok">
        <div class="muted small">{{ data.head }}</div>
        <button class="btn btn-primary" @click="copy">{{ copied ? '已复制 ✓' : '复制文案' }}</button>
        <pre class="mobile-text">{{ data.text }}</pre>
        <div class="muted small">{{ data.note }}</div>
        <img v-for="(im, i) in data.images" :key="i" class="mobile-img" :src="im.src" :alt="im.alt" />
      </template>
      <div v-else-if="data" class="hw-banner note">{{ data.note }}</div>
    </Panel>
  </div>
</template>
