<script setup>
// Product illustration (drawn, not a KB image): a laptop or desktop whose wallpaper takes the product's tint.
import { computed } from 'vue'
import { productKind, tintFor } from './tints.js'

const props = defineProps({ name: { type: String, default: '' }, tintKey: { type: String, default: '' } })
let seq = 0
const uid = 'pa' + Math.random().toString(36).slice(2, 8) + (seq++)
const kind = computed(() => productKind(props.name))
const wall = computed(() => tintFor(props.tintKey || props.name).wall)
</script>

<template>
  <svg class="product-art" viewBox="0 0 320 220" role="img" :aria-label="name ? name + ' 示意图' : '产品示意图'">
    <defs>
      <linearGradient :id="uid + 'shell'" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#F4F5F8" />
        <stop offset="1" stop-color="#CDD1D9" />
      </linearGradient>
      <linearGradient :id="uid + 'base'" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#E9EBF0" />
        <stop offset="1" stop-color="#B9BEC8" />
      </linearGradient>
      <linearGradient :id="uid + 'wall'" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" :stop-color="wall[0]" />
        <stop offset="1" :stop-color="wall[1]" />
      </linearGradient>
      <radialGradient :id="uid + 'shadow'" cx="0.5" cy="0.5" r="0.5">
        <stop offset="0" stop-color="#5A3C1E" stop-opacity="0.22" />
        <stop offset="1" stop-color="#5A3C1E" stop-opacity="0" />
      </radialGradient>
      <filter :id="uid + 'blur'" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="14" /></filter>
      <clipPath :id="uid + 'screen'"><rect :x="kind === 'laptop' ? 58 : 50" :y="kind === 'laptop' ? 28 : 22" :width="kind === 'laptop' ? 204 : 220" :height="kind === 'laptop' ? 129 : 132" rx="4" /></clipPath>
    </defs>

    <ellipse cx="160" cy="203" rx="140" ry="12" :fill="`url(#${uid}shadow)`" />

    <template v-if="kind === 'laptop'">
      <rect x="46" y="16" width="228" height="153" rx="12" :fill="`url(#${uid}shell)`" />
      <rect x="53" y="23" width="214" height="139" rx="7" fill="#15161A" />
      <g :clip-path="`url(#${uid}screen)`">
        <rect x="58" y="28" width="204" height="129" :fill="`url(#${uid}wall)`" />
        <circle class="pa-blob pa-blob-a" cx="110" cy="70" r="46" fill="#FFFFFF" opacity="0.55" :filter="`url(#${uid}blur)`" />
        <circle class="pa-blob pa-blob-b" cx="220" cy="130" r="54" :fill="wall[0]" opacity="0.9" :filter="`url(#${uid}blur)`" />
        <path class="pa-wave" d="M40 120 C 100 92, 170 150, 280 104 L 280 160 L 40 160 Z" fill="#FFFFFF" opacity="0.28" />
        <rect class="pa-glint" x="20" y="10" width="34" height="170" fill="#FFFFFF" opacity="0.35" transform="skewX(-20)" />
      </g>
      <circle cx="160" cy="25.5" r="1.4" fill="#3A3C44" />
      <path d="M18 171 H302 L294 185 Q291 190 285 190 H35 Q29 190 26 185 Z" :fill="`url(#${uid}base)`" />
      <rect x="132" y="171" width="56" height="5" rx="2.5" fill="#A7ACB7" />
    </template>

    <template v-else>
      <rect x="38" y="10" width="244" height="156" rx="10" :fill="`url(#${uid}shell)`" />
      <rect x="45" y="17" width="230" height="142" rx="6" fill="#15161A" />
      <g :clip-path="`url(#${uid}screen)`">
        <rect x="50" y="22" width="220" height="132" :fill="`url(#${uid}wall)`" />
        <circle class="pa-blob pa-blob-a" cx="100" cy="64" r="48" fill="#FFFFFF" opacity="0.55" :filter="`url(#${uid}blur)`" />
        <circle class="pa-blob pa-blob-b" cx="230" cy="128" r="56" :fill="wall[0]" opacity="0.9" :filter="`url(#${uid}blur)`" />
        <path class="pa-wave" d="M32 118 C 96 90, 168 148, 288 102 L 288 158 L 32 158 Z" fill="#FFFFFF" opacity="0.28" />
        <rect class="pa-glint" x="10" y="4" width="36" height="170" fill="#FFFFFF" opacity="0.35" transform="skewX(-20)" />
      </g>
      <path d="M150 166 H170 L174 192 H146 Z" :fill="`url(#${uid}base)`" />
      <rect x="112" y="190" width="96" height="8" rx="4" :fill="`url(#${uid}base)`" />
    </template>
  </svg>
</template>
