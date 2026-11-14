import React, { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import WhatYouSee from './WhatYouSee.jsx'
import { COLORS, fmtDay, fmtDayTime, highlightNumbers, hexA, inr, pct, short, typ } from '../util'

function Gauge({ value, color }) {
  const [v, setV] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => setV(value))
    return () => cancelAnimationFrame(id)
  }, [value])
  const R = 36, C = 2 * Math.PI * R
  return (
    <div className="gauge">
      <svg width="84" height="84" viewBox="0 0 84 84">
        <circle cx="42" cy="42" r={R} fill="none" stroke="#14223c" strokeWidth="8" />
        <circle cx="42" cy="42" r={R} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round" strokeDasharray={C}
          strokeDashoffset={C * (1 - v / 100)} style={{ transition: 'stroke-dashoffset 1.1s cubic-bezier(.2,.8,.2,1)', filter: `drop-shadow(0 0 6px ${color})` }} />
      </svg>
      <b style={{ color }}>{Math.round(value)}</b>
    </div>
  )
}

/** The money trail as an interactive left-to-right graph. Press replay to walk it in time order. */
function MiniFlow({ flow, events, color, onTrace }) {
  const W = 392, H = 290, P = 34
  const [step, setStep] = useState(events.length)
  const [play, setPlay] = useState(false)
  const [tip, setTip] = useState(null)
  useEffect(() => {
    setStep(events.length)
    setPlay(false)
  }, [events])
  useEffect(() => {
    if (!play) return
    if (step >= events.length) { setPlay(false); return }
    const id = setTimeout(() => setStep((s) => s + 1), 520)
    return () => clearTimeout(id)
  }, [play, step, events.length])
  const { pos, role, edges } = flow
  const ids = Object.keys(pos)
  const xs = ids.map((i) => pos[i][0]), ys = ids.map((i) => pos[i][1])
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)]
  const px = (v) => (x1 === x0 ? W / 2 : P + ((v - x0) / (x1 - x0)) * (W - 2 * P))
  const py = (v) => (y1 === y0 ? H / 2 : P + 10 + ((v - y0) / (y1 - y0)) * (H - 2 * P - 20))
  const firstIdx = useMemo(() => {
    const m = {}
    events.forEach((e, i) => { const k = `${e.src}|${e.dst}`; if (!(k in m)) m[k] = i })
    return m
  }, [events])
  const cur = events[Math.min(step, events.length) - 1]
  const roleStyle = { entry: ['#4fb3a9', 'diamond'], exit: ['#ff3b5c', 'square'], internal: [color, 'circle'], ext_in: ['#5b6b8c', 'ring'], ext_out: ['#5b6b8c', 'ring'] }
  const path = (a, b) => {
    const [ax, ay, bx, by] = [px(pos[a][0]), py(pos[a][1]), px(pos[b][0]), py(pos[b][1])]
    if (bx <= ax) {
      const cy = Math.min(ay, by) - 44 - Math.abs(bx - ax) * 0.1
      return `M${ax},${ay} Q${(ax + bx) / 2},${cy} ${bx},${by}`
    }
    const m = (ax + bx) / 2
    return `M${ax},${ay} C${m},${ay} ${m},${by} ${bx},${by}`
  }
  return (
    <div>
      <div className="svgbox" style={{ position: 'relative' }}>
        <svg width="100%" viewBox={`0 0 ${W} ${H}`} onMouseLeave={() => setTip(null)}>
          <defs>
            <marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
              <path d="M0,0 L10,5 L0,10 z" fill={color} />
            </marker>
          </defs>
          {edges.map((e, i) => {
            if (!pos[e.src] || !pos[e.dst] || e.src === e.dst) return null
            const fi = firstIdx[`${e.src}|${e.dst}`]
            const live = e.kind === 'external' || e.kind === 'owner' ? true : fi === undefined || fi < step
            const c = e.kind === 'external' ? '#4a5a7c' : e.kind === 'trade' ? '#a78bfa' : e.kind === 'owner' ? '#8aa0cf' : color
            return (
              <g key={i} onMouseEnter={() => setTip({ x: (px(pos[e.src][0]) + px(pos[e.dst][0])) / 2, y: (py(pos[e.src][1]) + py(pos[e.dst][1])) / 2 - 12, t: `${short(e.src)} → ${short(e.dst)} · ${e.amount ? inr(e.amount) : 'owner link'}${e.n > 1 ? ` · ${e.n}×` : ''}` })}>
                <path d={path(e.src, e.dst)} fill="none" stroke="transparent" strokeWidth="12" />
                <path d={path(e.src, e.dst)} fill="none" stroke={c} strokeWidth={e.kind === 'external' ? 1 : 1.8 + Math.min(2.4, Math.log10(1 + e.amount) / 3)}
                  opacity={live ? 0.9 : 0.12} className={live && e.kind !== 'owner' ? 'flow-edge' : ''}
                  strokeDasharray={e.kind === 'owner' ? '2 4' : e.kind === 'external' ? '2 3' : undefined} markerEnd={e.kind === 'money' || e.kind === 'trade' ? 'url(#arr)' : undefined} />
              </g>
            )
          })}
          {ids.map((id) => {
            const r = role[id] || 'internal'
            const [c, shape] = roleStyle[r]
            const x = px(pos[id][0]), y = py(pos[id][1])
            const hot = cur && (cur.src === id || cur.dst === id)
            return (
              <g key={id} style={{ cursor: 'pointer' }} onClick={() => onTrace(id)} onMouseEnter={() => setTip({ x, y: y - 16, t: `${id} · ${r.replace('_', ' ')} · click to trace` })}>
                {hot && <circle cx={x} cy={y} r="17" fill={hexA(c, 0.22)} className="pulse" />}
                {shape === 'diamond' && <path d={`M${x},${y - 11} L${x + 11},${y} L${x},${y + 11} L${x - 11},${y} Z`} fill={c} stroke="#101214" strokeWidth="2" />}
                {shape === 'square' && <rect x={x - 8.5} y={y - 8.5} width="17" height="17" rx="3" fill={c} stroke="#101214" strokeWidth="2" />}
                {shape === 'circle' && <circle cx={x} cy={y} r="8" fill={c} stroke="#101214" strokeWidth="2" />}
                {shape === 'ring' && <circle cx={x} cy={y} r="6" fill="none" stroke={c} strokeWidth="1.6" strokeDasharray="2 2" />}
                {ids.length <= 12 && <text x={x} y={y + 22} textAnchor="middle" fontSize="9" fill="#8ea2c9" fontFamily="monospace">{short(id)}</text>}
              </g>
            )
          })}
          {tip && (
            <g pointerEvents="none">
              <rect x={Math.min(W - 230, Math.max(4, tip.x - 100))} y={Math.max(4, tip.y - 20)} width="226" height="20" rx="6" fill="#050a16" stroke="#243553" />
              <text x={Math.min(W - 230, Math.max(4, tip.x - 100)) + 8} y={Math.max(4, tip.y - 20) + 14} fontSize="10" fill="#d6e0f5" fontFamily="monospace">{tip.t}</text>
            </g>
          )}
        </svg>
      </div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 8 }}>
        <button className="btn sm" onClick={() => { if (step >= events.length) setStep(0); setPlay(!play) }}>{play ? '❚❚ Pause' : '▶ Replay the money trail'}</button>
        <span className="sub" style={{ fontFamily: 'var(--mono)' }}>
          {cur ? `${fmtDayTime(cur.t)} · ${short(cur.src)}→${short(cur.dst)} · ${inr(cur.amt)}` : 'press replay'}
        </span>
      </div>
    </div>
  )
}

function TxChart({ events, color }) {
  const W = 392, H = 190, L = 40, B = 24
  const [tip, setTip] = useState(null)
  if (!events.length) return <div className="empty">No events.</div>
  const ts = events.map((e) => e.t)
  const t0 = Math.min(...ts), t1 = Math.max(...ts)
  const sp = Math.max(t1 - t0, 0.05)
  const amts = events.map((e) => Math.log10(e.amt + 1))
  const a0 = Math.floor(Math.min(...amts)), a1 = Math.ceil(Math.max(...amts))
  const X = (t) => L + ((t - t0) / sp) * (W - L - 14)
  const Y = (a) => H - B - ((Math.log10(a + 1) - a0) / Math.max(1, a1 - a0)) * (H - B - 12)
  const ticks = []
  for (let v = a0; v <= a1; v++) ticks.push(v)
  const thr = 50000
  return (
    <div className="svgbox" style={{ position: 'relative' }}>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} onMouseLeave={() => setTip(null)}>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={L} x2={W - 10} y1={Y(10 ** v)} y2={Y(10 ** v)} stroke="#14223c" />
            <text x={L - 6} y={Y(10 ** v) + 3} fontSize="9" fill="#6f7f9f" textAnchor="end" fontFamily="monospace">{inr(10 ** v).replace('₹', '')}</text>
          </g>
        ))}
        {Math.log10(thr) >= a0 && Math.log10(thr) <= a1 && (
          <g>
            <line x1={L} x2={W - 10} y1={Y(thr)} y2={Y(thr)} stroke="#ffb020" strokeDasharray="4 3" opacity="0.7" />
            <text x={W - 12} y={Y(thr) - 4} fontSize="9" fill="#ffb020" textAnchor="end">₹50,000 reporting threshold</text>
          </g>
        )}
        <polyline fill="none" stroke={color} strokeOpacity="0.35" points={events.filter((e) => e.kind === 'money').map((e) => `${X(e.t)},${Y(e.amt)}`).join(' ')} />
        {events.map((e, i) => (
          <circle key={i} cx={X(e.t)} cy={Y(e.amt)} r={4.2} fill={e.kind === 'trade' ? '#a78bfa' : color} opacity="0.9" stroke="#101214"
            onMouseEnter={() => setTip({ x: X(e.t), y: Y(e.amt), e })} />
        ))}
        <text x={L} y={H - 6} fontSize="9" fill="#6f7f9f" fontFamily="monospace">{fmtDayTime(t0)}</text>
        <text x={W - 10} y={H - 6} fontSize="9" fill="#6f7f9f" textAnchor="end" fontFamily="monospace">{fmtDayTime(t1)}</text>
        {tip && (
          <g pointerEvents="none">
            <rect x={Math.min(W - 196, Math.max(4, tip.x - 90))} y={Math.max(4, tip.y - 38)} width="192" height="32" rx="6" fill="#050a16" stroke="#243553" />
            <text x={Math.min(W - 196, Math.max(4, tip.x - 90)) + 8} y={Math.max(4, tip.y - 38) + 13} fontSize="10" fill="#d6e0f5" fontFamily="monospace">{short(tip.e.src)} → {short(tip.e.dst)}</text>
            <text x={Math.min(W - 196, Math.max(4, tip.x - 90)) + 8} y={Math.max(4, tip.y - 38) + 26} fontSize="10" fill="#4fb3a9" fontFamily="monospace">{inr(tip.e.amt)}{tip.e.price ? ` · ${tip.e.qty}@${tip.e.price.toFixed(1)} (ref ${tip.e.ref.toFixed(1)})` : ''}</text>
          </g>
        )}
      </svg>
    </div>
  )
}

export default function CaseFile({ alertId, onTrace, onZoom, onReplay, onLower, thr }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState(null)
  const [view, setView] = useState('flow')
  useEffect(() => {
    if (!alertId) return
    setD(null)
    setErr(null)
    api.alert(alertId).then(setD).catch((e) => setErr(String(e)))
  }, [alertId])
  if (!alertId) return <div className="empty"><big>⚑</big>Pick an alert from the inbox<br />or click a glowing cluster on the board.</div>
  if (err) return <div className="empty">Could not load: {err}</div>
  if (!d) return <div className="empty"><div className="spin" />Opening case file…</div>
  const a = d.alert
  const c = typ(a.typology).color
  const ev = a.evidence
  const facts = [
    ['window', `${fmtDayTime(a.t_start / 86400)} → ${fmtDayTime(a.t_end / 86400)}`], ['accounts', a.accounts.length], ['amount involved', inr(ev.amount_inr || 0)],
    ['confidence', pct(a.confidence)], ['layer', a.layer === 'bridge' ? 'bank ↔ trades' : a.layer], ['period', a.split === 'test' ? 'held-out test' : a.split],
    ...Object.entries(ev).filter(([k, v]) => typeof v === 'number' && !k.startsWith('driver') && !['risk_score', 'amount_inr', 'n_accounts'].includes(k)).slice(0, 8)
      .map(([k, v]) => [k.replace(/_/g, ' '), Math.abs(v) >= 1000 ? Math.round(v).toLocaleString('en-IN') : Number.isInteger(v) ? v : Number(v).toFixed(3)]),
  ]
  const truth = a.truth.matched_rings
  const below = a.score < thr[a.layer === 'money' ? 'money' : 'trade']
  const tr = a.entry_nodes[0] || a.accounts[0]
  return (
    <div>
      <div className="case-h">
        <Gauge value={a.score} color={c} />
        <div style={{ minWidth: 0 }}>
          <h2 style={{ color: c }}>{typ(a.typology).glyph} {a.typology_name}</h2>
          <div className="sub">{a.alert_id}{a.secondary_typology ? ` · also: ${a.secondary_typology.replace(/_/g, ' ')}` : ''} · {fmtDay(a.t_start / 86400)}</div>
        </div>
      </div>
      {below && <div className="truth" style={{ borderColor: '#ffb020', color: '#ffcb6b' }}>Below the current alert threshold. It would not have fired. <button className="btn sm" style={{ marginLeft: 6 }} onClick={() => onLower(a)}>Lower the bar to catch it</button></div>}
      <div className="summary">{highlightNumbers(a.summary).map((p, i) => (p.num ? <span key={i} className="num">{p.t}</span> : <span key={i}>{p.t}</span>))}</div>
      <div className="pills">
        {a.entry_nodes.slice(0, 4).map((x) => <button key={x} className="pill entry" onClick={() => onTrace(x)}>↘ in · {short(x)}</button>)}
        {a.exit_nodes.slice(0, 4).map((x) => <button key={x} className="pill exit" onClick={() => onTrace(x)}>↗ out · {short(x)}</button>)}
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="btn sm primary" onClick={() => onTrace(tr)}>⤳ Trace the money</button>
        <button className="btn sm" onClick={onZoom}>◎ Show on board</button>
        <button className="btn sm" onClick={() => onReplay(a)}>▶ Replay on board</button>
      </div>
      <div className="subtabs seg" style={{ display: 'flex' }}>
        {[['flow', 'Money trail'], ['time', 'Timeline'], ['why', 'Why flagged'], ['facts', 'Evidence']].map(([k, l]) => (
          <button key={k} className={view === k ? 'on' : ''} style={{ flex: 1 }} onClick={() => setView(k)}>{l}</button>
        ))}
      </div>
      {view === 'flow' && (
        <>
          <WhatYouSee kind="alert" alert={a} />
          <MiniFlow flow={d.flow} events={d.events} color={c} onTrace={onTrace} />
        </>
      )}
      {view === 'time' && <TxChart events={d.events} color={c} />}
      {view === 'why' && (
        <div className="sect" style={{ marginTop: 4 }}>
          <h4>Top score drivers (TreeSHAP)</h4>
          {a.contributions.length ? a.contributions.map((x) => <Driver key={x.feature} x={x} />) : <div className="sub">No breakdown stored.</div>}
          <div className="sub" style={{ marginTop: 10, lineHeight: 1.5 }}>Every number in the summary above is taken straight from this alert&apos;s evidence. Nothing is generated freehand.</div>
        </div>
      )}
      {view === 'facts' && <div className="kv">{facts.map(([k, v]) => <div key={k}><span>{k}</span><b>{String(v)}</b></div>)}</div>}
      <div className={'truth' + (truth.length ? '' : ' fa')}>
        <b>{truth.length ? '✓ synthetic ground truth' : '✕ synthetic ground truth'}</b>{' '}
        {truth.length ? `matches planted ring ${truth[0]}` : 'no planted ring matches: this alert is a false alarm'}
      </div>
    </div>
  )
}

function Driver({ x }) {
  const [w, setW] = useState(0)
  useEffect(() => {
    const id = setTimeout(() => setW(x.share * 100), 60)
    return () => clearTimeout(id)
  }, [x.share])
  return (
    <div className="drv">
      <div className="l"><span>{x.label}</span><b style={{ fontFamily: 'var(--mono)' }}>{Math.round(x.share * 100)}%</b></div>
      <div className="tr"><div style={{ width: `${w}%` }} /></div>
    </div>
  )
}
