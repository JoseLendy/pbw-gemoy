<script setup>
// A tiny phone that shows each platform's page shape, so the 平台 step is a picture, not a word.
defineProps({ platform: { type: String, default: '' } })
const clip = 'ptc' + Math.random().toString(36).slice(2, 8)   // per-instance clip id
</script>

<template>
  <svg class="platform-thumb" viewBox="0 0 96 168" aria-hidden="true">
    <rect x="2" y="2" width="92" height="164" rx="16" fill="#FFFFFF" stroke="#E6DDD3" stroke-width="2" />
    <rect x="36" y="8" width="24" height="5" rx="2.5" fill="#E6DDD3" />
    <clipPath :id="clip"><rect x="4" y="16" width="88" height="148" rx="12" /></clipPath>
    <g :clip-path="`url(#${clip})`"><g class="pt-feed">

    <g v-if="platform.includes('小红书')">
      <rect x="10" y="20" width="36" height="46" rx="5" fill="#FBD3DC" />
      <rect x="50" y="20" width="36" height="34" rx="5" fill="#F3E3C9" />
      <rect x="10" y="70" width="30" height="4" rx="2" fill="#2B2B2B" />
      <rect x="50" y="58" width="30" height="4" rx="2" fill="#2B2B2B" />
      <rect x="10" y="84" width="36" height="34" rx="5" fill="#E2E9F7" />
      <rect x="50" y="68" width="36" height="46" rx="5" fill="#FBD3DC" />
      <rect x="10" y="122" width="26" height="4" rx="2" fill="#2B2B2B" />
      <rect x="50" y="118" width="30" height="4" rx="2" fill="#2B2B2B" />
      <rect x="10" y="140" width="76" height="16" rx="8" fill="#FF2E4D" />
    </g>

    <g v-else-if="platform.includes('朋友圈')">
      <rect x="2" y="16" width="92" height="40" fill="#E8EDF2" />
      <rect x="62" y="44" width="22" height="22" rx="4" fill="#B9C6D3" stroke="#FFFFFF" stroke-width="2" />
      <rect x="10" y="76" width="12" height="12" rx="2" fill="#C8D3DD" />
      <rect x="26" y="76" width="22" height="4" rx="2" fill="#576B95" />
      <rect x="26" y="84" width="56" height="3" rx="1.5" fill="#9AA1A9" />
      <rect x="26" y="90" width="44" height="3" rx="1.5" fill="#9AA1A9" />
      <g fill="#DCE3EA">
        <rect x="26" y="98" width="17" height="17" rx="2" /><rect x="45" y="98" width="17" height="17" rx="2" /><rect x="64" y="98" width="17" height="17" rx="2" />
        <rect x="26" y="117" width="17" height="17" rx="2" /><rect x="45" y="117" width="17" height="17" rx="2" /><rect x="64" y="117" width="17" height="17" rx="2" />
      </g>
      <rect x="26" y="142" width="20" height="3" rx="1.5" fill="#B7BCC2" />
    </g>

    <g v-else-if="platform.includes('公众号')">
      <rect x="10" y="22" width="70" height="6" rx="3" fill="#2B2B2B" />
      <rect x="10" y="32" width="40" height="3" rx="1.5" fill="#576B95" />
      <rect x="10" y="42" width="76" height="40" rx="4" fill="#DDEFE4" />
      <rect x="10" y="90" width="76" height="3" rx="1.5" fill="#A3A8AE" />
      <rect x="10" y="97" width="70" height="3" rx="1.5" fill="#A3A8AE" />
      <rect x="10" y="104" width="74" height="3" rx="1.5" fill="#A3A8AE" />
      <rect x="10" y="111" width="52" height="3" rx="1.5" fill="#A3A8AE" />
      <rect x="10" y="124" width="76" height="24" rx="4" fill="#F2F4F5" />
      <rect x="16" y="133" width="40" height="5" rx="2.5" fill="#07C160" />
    </g>

    <g v-else-if="platform.includes('海报')">
      <rect x="8" y="16" width="80" height="144" rx="8" fill="#26262B" />
      <rect x="16" y="30" width="58" height="10" rx="3" fill="#FFFFFF" />
      <rect x="16" y="46" width="40" height="5" rx="2.5" fill="#FFD54F" />
      <rect x="16" y="62" width="64" height="44" rx="4" fill="#3A3A42" />
      <rect x="16" y="114" width="3" height="10" fill="#FFD54F" /><rect x="23" y="116" width="46" height="4" rx="2" fill="#C9C9CF" />
      <rect x="16" y="130" width="3" height="10" fill="#FFD54F" /><rect x="23" y="132" width="38" height="4" rx="2" fill="#C9C9CF" />
    </g>

    <g v-else>
      <rect x="8" y="16" width="80" height="144" rx="8" fill="#141418" />
      <rect x="14" y="24" width="68" height="92" rx="4" fill="#2E2E36" />
      <circle cx="76" cy="96" r="5" fill="#FFFFFF" opacity="0.8" /><circle cx="76" cy="110" r="5" fill="#FFFFFF" opacity="0.8" />
      <rect x="14" y="124" width="44" height="4" rx="2" fill="#FFFFFF" />
      <rect x="14" y="132" width="58" height="3" rx="1.5" fill="#8C8C96" />
      <rect x="14" y="140" width="36" height="3" rx="1.5" fill="#25F4EE" />
    </g>
    </g></g>
  </svg>
</template>
