<script setup>
// A frosted-glass panel. `tone` tints the left edge: none | ok | warn | err | note.
defineProps({ title: { type: String, default: '' }, tone: { type: String, default: '' }, tight: Boolean })
</script>

<template>
  <section class="panel" :class="[tone && 'tone-' + tone, tight && 'tight']">
    <header v-if="title || $slots.head" class="panel-head">
      <h3 v-if="title">{{ title }}</h3>
      <slot name="head"></slot>
    </header>
    <slot></slot>
  </section>
</template>
