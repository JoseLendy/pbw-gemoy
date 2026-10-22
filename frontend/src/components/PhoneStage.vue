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
        <div v-if="busy" class="hw-loading-overlay" role="img" :aria-label="busyText">
          <div class="skel" aria-hidden="true">
            <span class="skel-img"></span>
            <span class="skel-line w90"></span>
            <span class="skel-line w70"></span>
            <span class="skel-line w80"></span>
            <span class="skel-row"><span class="skel-img sm"></span><span class="skel-img sm"></span><span class="skel-img sm"></span></span>
            <span class="skel-line w60"></span>
          </div>
          <div class="hw-thinking-title">{{ busyText }}<span class="dots" aria-hidden="true"><i></i><i></i><i></i></span></div>
        </div>
      </div>
    </div>
    <div v-if="tools" class="stage-tools">
      <button class="round" title="放大" aria-label="放大预览" :disabled="zoom >= 1.4" @click="zoomBy(1.1)">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none" /></svg>
      </button>
      <button class="round" title="缩小" aria-label="缩小预览" :disabled="zoom <= 0.7" @click="zoomBy(0.9)">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" fill="none" /></svg>
      </button>
      <slot name="tools"></slot>
    </div>
  </div>
</template>
