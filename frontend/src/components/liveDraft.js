// Live draft for the streaming phone (Davin's pattern): the server sends `draft` once the first draft is
// written and `revision` after every targeted rewrite. The displayed copy types itself toward the newest
// target — typing where it falls short, backspacing before a changed tail — so the clerk watches the copy
// being written instead of a spinner. The final `result` view replaces it.
import { ref } from 'vue'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

export function useLiveDraft({ chunk = 3, typeDelay = 14, backDelay = 10 } = {}) {
  const live = ref(null)   // { platform, post: {title,intro,body[],cta,tags[]}, images: [{idx,position,caption}] }
  let target = null        // the newest full text; the visible copy converges on it
  let running = false      // one drain loop at a time; a newer target is picked up by the same loop

  function reset() { target = null; live.value = null }

  function snapshot(data) {
    const p = data.post || {}
    return {
      platform: data.platform,
      post: {
        title: p.title || '',
        intro: p.intro || '',
        body: [...(p.body || [])],
        cta: p.cta || '',
        tags: [...(p.tags || [])],
      },
      images: data.images || [],
    }
  }

  function getField(field, index) {
    const p = live.value.post
    return field === 'body' ? (p.body[index] || '') : (p[field] || '')
  }

  function setField(field, index, text) {
    const p = live.value.post
    if (field === 'body') {
      while (p.body.length <= index) p.body.push('')
      p.body[index] = text
    } else {
      p[field] = text
    }
  }

  function diffPrefix(a, b) {
    let i = 0
    while (i < a.length && i < b.length && a[i] === b[i]) i++
    return i
  }

  /** The first field (title → intro → each paragraph → CTA) that still differs from the target. */
  function firstDiff() {
    if (!live.value || !target) return null
    const cur = live.value.post
    const t = target.post
    for (const f of ['title', 'intro', 'cta']) {
      if ((cur[f] || '') !== t[f]) return { field: f, index: 0, text: t[f] }
    }
    const n = Math.max(cur.body.length, t.body.length)
    for (let i = 0; i < n; i++) {
      if ((cur.body[i] || '') !== (t.body[i] || '')) return { field: 'body', index: i, text: t.body[i] || '' }
    }
    return null
  }

  async function drain() {
    if (running) return
    running = true
    try {
      while (true) {
        const d = firstDiff()
        if (!d) break
        const cur = getField(d.field, d.index)
        if (cur.length > d.text.length) {
          setField(d.field, d.index, cur.slice(0, Math.max(d.text.length, cur.length - chunk)))
          await sleep(backDelay)
        } else {
          const keep = diffPrefix(cur, d.text)
          setField(d.field, d.index, cur.slice(0, keep) + d.text.slice(keep, keep + chunk))
          await sleep(typeDelay)
        }
      }
    } finally {
      running = false
    }
  }

  /** The first draft: open an empty phone and let the drain loop type it in, field by field. */
  function applyDraft(data) {
    target = snapshot(data)
    live.value = {
      platform: target.platform,
      post: { title: '', intro: '', body: [], cta: '', tags: target.post.tags },
      images: target.images,
    }
    drain()
  }

  /** A rewrite: keep what stayed the same, backspace the rest, retype the new tail. */
  function applyRevision(data) {
    if (!live.value || live.value.platform !== data.platform) { applyDraft(data); return }
    target = snapshot(data)
    live.value.platform = target.platform
    live.value.images = target.images
    live.value.post.tags = target.post.tags
    drain()
  }

  return { live, applyDraft, applyRevision, reset }
}
