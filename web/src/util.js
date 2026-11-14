export const TYP = {
  fan_out: { label: 'Dispersion', long: 'Fan-out dispersion', color: '#d1713e', glyph: '⇶' },
  fan_in_structuring: { label: 'Structuring', long: 'Fan-in with structuring', color: '#d19f29', glyph: '⇉' },
  fan_in: { label: 'Aggregation', long: 'Fan-in aggregation', color: '#d1b162', glyph: '⇉' },
  round_trip: { label: 'Round-trip', long: 'Round-tripping', color: '#d13f73', glyph: '↻' },
  mule_chain: { label: 'Mule chain', long: 'Mule / pass-through chain', color: '#d1304b', glyph: '⛓' },
  wash_trading: { label: 'Wash trading', long: 'Wash / circular trading', color: '#b5703f', glyph: '⟳' },
  loss_booking: { label: 'Loss-booking', long: 'Loss-booking / non-genuine trades', color: '#b5703f', glyph: '⇅' },
  market_layering: { label: 'Market layering', long: 'Layering through the market', color: '#aa9c8a', glyph: '⛛' },
  unclassified_anomaly: { label: 'Anomaly', long: 'Unclassified anomalous cluster', color: '#766855', glyph: '◇' },
}
export const typ = (k) => TYP[k] || TYP.unclassified_anomaly

export const COLORS = {
  bank: '#4f6d7a', demat: '#b5703f', bankDim: '#b9c6cb', crematDim: '#dcc3ae', amber: '#d1901a', green: '#25bb80',
  red: '#d1304b', cyan: '#5d6b2f', ink: '#393329', muted: '#8a7a63',
}

export const inr = (x) => {
  x = Number(x) || 0
  if (x >= 1e7) return `₹${(x / 1e7).toFixed(1)}Cr`
  if (x >= 1e5) return `₹${(x / 1e5).toFixed(1)}L`
  return `₹${Math.round(x).toLocaleString('en-IN')}`
}
export const pct = (x, d = 0) => `${(x * 100).toFixed(d)}%`
export const short = (id) => (id.length > 9 ? `${id.slice(0, 2)}…${id.slice(-4)}` : id)

const T0 = new Date('2025-01-01T00:00:00')
export const dayDate = (d) => new Date(T0.getTime() + d * 86400000)
export const fmtDay = (d) => dayDate(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
export const fmtDayTime = (d) =>
  dayDate(d).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })

export const hexA = (hex, a) => {
  const n = parseInt(hex.slice(1), 16)
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
}

// wrap numbers / rupee amounts in a summary so they glow
export const highlightNumbers = (s) =>
  s.split(/(INR [\d.,]+(?:L|Cr)?|\d[\d,]*(?:\.\d+)?%?)/g).map((p, i) => ({ t: p, num: i % 2 === 1 }))

export const clamp = (x, a, b) => Math.max(a, Math.min(b, x))
