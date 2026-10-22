// Client-side typewriter over a finished text: reveals `target` into `setter` in small chunks. Returns a
// cancel function. Used when a *live* result arrives; stored/prepared text is shown at once.
export function typewrite(target, setter, { chunk = 3, delay = 12, onDone } = {}) {
  let cancelled = false
  let i = 0
  setter('')
  function step() {
    if (cancelled) return
    i = Math.min(target.length, i + chunk)
    setter(target.slice(0, i))
    if (i < target.length) setTimeout(step, delay)
    else if (onDone) onDone()
  }
  step()
  return () => { cancelled = true }
}
