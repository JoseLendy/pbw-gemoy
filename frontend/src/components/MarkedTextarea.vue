<script setup>
// 正文 with the failing sentences marked. `flagged` is the server's list (the same sentences 「检查并保存」
// requires to be rewritten or removed), so what is red here is exactly what blocks the save.
//   · a backdrop behind the transparent textarea repeats the text with <mark> on each flagged sentence
//   · the list above it jumps to a sentence (scrolls the box there and selects it)
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  flagged: { type: Array, default: () => [] },
  readonly: Boolean,
  rows: { type: Number, default: 10 },
  id: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'input'])

const ta = ref(null)
const back = ref(null)
const missing = ref('')     // the sentence a click could not find (already edited)

const items = computed(() => [...new Set((props.flagged || []).map((s) => (s || '').trim()).filter(Boolean))])
const present = (s) => props.modelValue.includes(s)
const left = computed(() => items.value.filter(present).length)

function esc(t) {
  return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
// The text with every occurrence of each flagged sentence wrapped in <mark data-i="n">. Longer sentences first,
// so a short one inside a long one does not split it. The trailing space keeps a last empty line the same height.
const marked = computed(() => {
  const text = props.modelValue || ''
  const hits = []
  items.value.map((s, i) => ({ s, i })).sort((a, b) => b.s.length - a.s.length).forEach(({ s, i }) => {
    let from = 0
    let at
    while ((at = text.indexOf(s, from)) !== -1) {
      const end = at + s.length
      if (!hits.some((h) => at < h.end && end > h.start)) hits.push({ start: at, end, i })
      from = end
    }
  })
  hits.sort((a, b) => a.start - b.start)
  let out = ''
  let pos = 0
  for (const h of hits) {
    out += esc(text.slice(pos, h.start)) + `<mark data-i="${h.i}">` + esc(text.slice(h.start, h.end)) + '</mark>'
    pos = h.end
  }
  return out + esc(text.slice(pos)) + ' '
})

function sync() { if (back.value && ta.value) back.value.scrollTop = ta.value.scrollTop }
function onInput(e) {
  emit('update:modelValue', e.target.value)
  emit('input', e)
  nextTick(sync)
}

async function jump(s, i) {
  missing.value = ''
  const at = props.modelValue.indexOf(s)
  if (at === -1 || !ta.value) { missing.value = s; return }
  ta.value.focus({ preventScroll: true })
  ta.value.setSelectionRange(at, at + s.length)
  // Browsers do not reliably scroll a textarea to its selection; the backdrop knows where the mark sits.
  await nextTick()
  const mark = back.value && back.value.querySelector(`mark[data-i="${i}"]`)
  if (mark) ta.value.scrollTop = Math.max(0, mark.offsetTop - ta.value.clientHeight / 3)
  sync()
}
watch(() => props.modelValue, () => nextTick(sync))
</script>

<template>
  <div class="marked">
    <div v-if="items.length" class="flag-list" role="list" aria-label="需要修改的句子">
      <span class="flag-list-head">需要修改的句子（{{ left }}/{{ items.length }}）· 点一下定位到正文</span>
      <button v-for="(s, i) in items" :key="s" type="button" class="flag-item" :class="{ done: !present(s) }"
              role="listitem" @click="jump(s, i)">
        <span class="flag-text">「{{ s }}」</span>
        <span v-if="!present(s)" class="flag-done">已修改</span>
      </button>
      <span v-if="missing" class="flag-miss" role="status">这句已修改，正文里找不到原句了。</span>
    </div>
    <div class="marked-wrap">
      <div ref="back" class="textarea marked-back" aria-hidden="true" v-html="marked"></div>
      <textarea :id="id || undefined" ref="ta" class="textarea marked-input" :value="modelValue" :rows="rows"
                spellcheck="false" :readonly="readonly" @input="onInput" @scroll="sync"></textarea>
    </div>
  </div>
</template>
