<script setup>
// The phone preview: server-rendered phone HTML (skins, fact popovers, flagged spans) inside a zoomable
// stage with Davin's round tools. `html` is trusted server output (ui.components.phone_html).
import { ref } from 'vue'
const props = defineProps({ html: { type: String, default: '' }, busy: Boolean, busyText: { type: String, default: '正在生成，请稍候' }, tools: { type: Boolean, default: true }, scale: { type: Number, default: 1 } })
const zoom = ref(1.0)
function zoomBy(f) { zoom.value = Math.round(Math.min(1.4, Math.max(0.7, zoom.value * f)) * 100) / 100 }
</script>

<template>
  <div class="hw-stage" :style="{ '--zoom': zoom * scale }">
    <div class="hw-phone-stage">
      <div class="hw-phone-wrap" :style="{ zoom: zoom * scale }">
        <div v-if="html" class="hw-phone-host" v-html="html"></div>
        <div v-else class="hw-phone">
          <div class="notch"></div>
          <div class="screen hw-empty"><img class="hw-logo-img" src="/logo.png" alt="HUAWEI" /></div>
        </div>
        <div v-if="busy" class="hw-loading-overlay">
          <div class="hw-spinner"></div>
          <div class="hw-thinking-title">{{ busyText }}</div>
        </div>
      </div>
    </div>
    <div v-if="tools" class="hw-tools">
      <button class="hw-round" title="放大" @click="zoomBy(1.1)">＋</button>
      <button class="hw-round" title="缩小" @click="zoomBy(0.9)">－</button>
      <slot name="tools"></slot>
    </div>
  </div>
</template>
