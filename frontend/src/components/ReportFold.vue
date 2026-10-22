<script setup>
// 「详细信息（四段式输出）」: the formatter's markdown (headings 一、二、三、四 verbatim) rendered client-side.
import { computed } from 'vue'
import { marked } from 'marked'
const props = defineProps({ md: { type: String, default: '' }, title: { type: String, default: '详细信息（四段式输出）' }, open: Boolean })
const html = computed(() => (props.md ? marked.parse(props.md, { breaks: false, gfm: true }) : ''))
</script>

<template>
  <details v-if="md" class="report" :open="open">
    <summary>{{ title }}</summary>
    <div class="report-body" v-html="html"></div>
  </details>
</template>
