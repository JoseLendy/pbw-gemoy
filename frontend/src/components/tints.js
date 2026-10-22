// Pastel tints for product tiles and illustrations. A product keeps the same tint everywhere (hash of its id).
export const TINTS = [
  { name: 'lilac', tile: 'linear-gradient(135deg, #F3EEFC 0%, #E7EEFB 100%)', wall: ['#C9B8F2', '#8FB3F5'], ink: '#6C55C2' },
  { name: 'mint', tile: 'linear-gradient(135deg, #E8F7F0 0%, #E6F3FA 100%)', wall: ['#9EE0C5', '#9FD0F2'], ink: '#2C8564' },
  { name: 'peach', tile: 'linear-gradient(135deg, #FFF0E6 0%, #FFF6DD 100%)', wall: ['#FFBFA0', '#FFD98F'], ink: '#C25A30' },
  { name: 'sky', tile: 'linear-gradient(135deg, #E8F2FD 0%, #EFEAFB 100%)', wall: ['#9CC8F5', '#C7B9F2'], ink: '#3569AD' },
  { name: 'rose', tile: 'linear-gradient(135deg, #FDEEF3 0%, #F3EEFC 100%)', wall: ['#F5B0C6', '#C9B8F2'], ink: '#B54068' },
  { name: 'butter', tile: 'linear-gradient(135deg, #FFF7DD 0%, #EAF7EF 100%)', wall: ['#FFDB85', '#A6DEC0'], ink: '#946A0B' },
]

export function tintFor(key) {
  let h = 0
  for (const c of String(key || '')) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return TINTS[h % TINTS.length]
}

/** Laptop unless the name says desktop / all-in-one. */
export function productKind(name) {
  return /台式|一体机|Station|Desk|主机/i.test(name || '') ? 'desktop' : 'laptop'
}
