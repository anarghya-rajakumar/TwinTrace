import React, { useEffect, useRef, useState } from 'react'
import ForceGraph from 'force-graph'
import { forceY } from 'd3-force'
import WhatYouSee from './WhatYouSee.jsx'
import { api } from '../api'
import { COLORS, fmtDay, hexA, inr, short } from '../util'

const COL = 230

/** Click-to-trace: where did the money come from (left) and where did it go (right), across bank and trades. */
export default function TraceView({ account, onClose, onOpenAlert }) {
  const el = useRef(null)
  const gref = useRef(null)
  const dataRef = useRef(null)
  const [stack, setStack] = useState([account])
  const [depth, setDepth] = useState(2)
  const [per, setPer] = useState(4)
  const [dir, setDir] = useState('both')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const cur = stack[stack.length - 1]

  useEffect(() => setStack([account]), [account])
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [])

  useEffect(() => {
    setLoading(true)
    setErr(null)
    api.trace(cur, depth, per, dir).then((d) => { setData(d); dataRef.current = d; setLoading(false) }).catch((e) => { setErr(String(e)); setLoading(false) })
  }, [cur, depth, per, dir])

  useEffect(() => {
    const g = ForceGraph()(el.current)
      .backgroundColor('rgba(237, 235, 231, 0)')
      .nodeId('id')
      .nodeRelSize(5)
      .nodeLabel((n) => `<b>${n.id}</b><br/>${n.k === 'b' ? 'bank account' : 'trading account'}${n.alerts.length ? '<br/><span style="color:#d17183">⚑ ' + n.alerts.join(', ') + '</span>' : ''}<br/><span style="color:#92816a">click to follow from here</span>`)
      .nodeCanvasObject((n, ctx, gs) => draw(n, ctx, gs, dataRef.current && dataRef.current.origin))
      .nodePointerAreaPaint((n, color, ctx) => { ctx.fillStyle = color; ctx.beginPath(); ctx.arc(n.x, n.y, 11, 0, 6.2832); ctx.fill() })
      .linkColor((l) => (l.kind === 'trade' ? hexA('#8b6b4e', 0.55) : l.kind === 'owner' ? hexA('#635747', 0.5) : hexA('#7a1f33', 0.55)))
      .linkWidth((l) => (l.kind === 'owner' ? 1 : 1 + Math.log10(l.amount + 10) / 2.6))
      .linkLineDash((l) => (l.kind === 'trade' ? [4, 3] : l.kind === 'owner' ? [1, 3] : null))
      .linkDirectionalArrowLength(6)
      .linkDirectionalArrowRelPos(0.92)
      .linkCurvature((l) => (l.curv || 0))
      .linkLabel((l) => `${short(l.src)} → ${short(l.dst)}<br/>${l.kind === 'owner' ? 'same owner (bank ↔ trading)' : inr(l.amount) + ' · ' + l.n + '×'}${l.t0 ? '<br/>' + fmtDay(l.t0) + ' → ' + fmtDay(l.t1) : ''}`)
      .onNodeClick((n) => {
        if (n.id !== dataRef.current.origin) setStack((s) => [...s, n.id])
      })
      .onRenderFramePost((ctx, gs) => {
        const now = performance.now() / 1000
        const links = g.graphData().links
        for (const l of links) {
          if (!l.source || l.source.x === undefined) continue
          for (let k = 0; k < 2; k++) {
            const p = (now * 0.5 + (l.seed || 0) + k * 0.5) % 1
            const x = l.source.x + (l.target.x - l.source.x) * p
            const y = l.source.y + (l.target.y - l.source.y) * p
            ctx.beginPath()
            ctx.arc(x, y, 1.9, 0, 6.2832)
            ctx.fillStyle = l.kind === 'trade' ? '#8b6b4e' : '#7a1f33'
            ctx.shadowColor = ctx.fillStyle
            ctx.shadowBlur = 8
            ctx.fill()
          }
        }
        ctx.shadowBlur = 0
      })
      .cooldownTicks(140)
      .d3VelocityDecay(0.3)
      .onEngineStop(() => g.zoomToFit(500, 70))
    g.d3Force('charge').strength(-90).distanceMax(220)
    g.d3Force('link').strength(0)
    g.d3Force('y', forceY(0).strength(0.085))
    gref.current = g
    const resize = () => el.current && g.width(el.current.clientWidth).height(el.current.clientHeight)
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el.current)
    return () => { ro.disconnect(); g._destructor && g._destructor() }
  }, [])

  useEffect(() => {
    const g = gref.current
    if (!g || !data) return
    const nodes = data.nodes.map((n, i) => ({
      ...n, fx: n.side === 'origin' || n.side === 'both' ? 0 : (n.side === 'up' ? -1 : 1) * n.dist * COL, y: (Math.random() - 0.5) * 200,
    }))
    const links = data.edges.map((e) => ({ ...e, source: e.src, target: e.dst, seed: Math.random() }))
    // curve parallel / reciprocal edges so they do not overlap
    const seen = {}
    links.forEach((l) => {
      const k = [l.src, l.dst].sort().join('|')
      seen[k] = (seen[k] || 0) + 1
      l.curv = seen[k] > 1 ? 0.28 * seen[k] : 0
    })
    g.graphData({ nodes, links })
    // fit symmetrically around the clicked account, so an empty side still reads as "nothing came from here"
    setTimeout(() => {
      const ns = g.graphData().nodes
      if (!ns.length || !el.current) return
      const xs = ns.map((n) => n.x || 0), ys = ns.map((n) => n.y || 0)
      const half = Math.max(60, ...xs.map(Math.abs)) + 60
      const spanY = Math.max(120, Math.max(...ys) - Math.min(...ys)) + 160
      const k = Math.min(el.current.clientWidth / (2 * half), el.current.clientHeight / spanY, 4)
      g.centerAt(0, (Math.max(...ys) + Math.min(...ys)) / 2, 700)
      g.zoom(k, 700)
    }, 700)
  }, [data])

  const up = data ? data.nodes.filter((n) => n.side === 'up' || n.side === 'both') : []
  const down = data ? data.nodes.filter((n) => n.side === 'down' || n.side === 'both') : []
  const Row = ({ n }) => (
    <button className={'node-row' + (n.alerts.length ? ' flag' : '')} onClick={() => n.id !== cur && setStack((s) => [...s, n.id])}>
      {n.k === 'd' ? '◆' : '●'} {n.id} <span style={{ color: 'var(--muted)' }}>· hop {n.dist}</span>
      {n.alerts.length > 0 && <span style={{ color: '#d17183' }}> ⚑ {n.alerts.length}</span>}
    </button>
  )
  return (
    <div className="trace">
      <div className="trace-main">
        <div className="trace-bar">
          <button className="btn sm" onClick={onClose}>✕ Close (Esc)</button>
          <div className="crumbs">
            {stack.map((s, i) => (
              <React.Fragment key={i}>
                {i > 0 && <span>›</span>}
                <button style={{ color: i === stack.length - 1 ? '#7a1f33' : undefined }} onClick={() => setStack(stack.slice(0, i + 1))}>{short(s)}</button>
              </React.Fragment>
            ))}
          </div>
          <span className="spacer" />
          <div className="seg">{['both', 'up', 'down'].map((d) => <button key={d} className={dir === d ? 'on' : ''} onClick={() => setDir(d)}>{d === 'both' ? '⇄ both' : d === 'up' ? '◀ source' : 'destination ▶'}</button>)}</div>
          <div className="seg">{[1, 2, 3, 4].map((d) => <button key={d} className={depth === d ? 'on' : ''} onClick={() => setDepth(d)}>{d} hop{d > 1 ? 's' : ''}</button>)}</div>
          <div className="seg">{[3, 5, 8].map((d) => <button key={d} className={per === d ? 'on' : ''} onClick={() => setPer(d)}>top {d}</button>)}</div>
        </div>
        <div className="trace-wys"><WhatYouSee kind="trace" trace={data ? { flagged: data.reach.flagged, originAlerts: (data.nodes.find((n) => n.id === cur) || { alerts: [] }).alerts.length > 0 } : null} /></div>
        <div className="side-label" style={{ left: 22 }}>◀ where the money came from</div>
        <div className="side-label" style={{ right: 22 }}>where it went ▶</div>
        <div ref={el} style={{ position: 'absolute', inset: 0 }} />
        {data && !loading && dir === 'both' && (data.reach.up === 0 || data.reach.down === 0) && (
          <div className="trace-hint" style={{ top: 150, bottom: 'auto', [data.reach.up === 0 ? 'left' : 'right']: 24, transform: 'none' }}>
            {data.reach.up === 0 ? 'No money came into this account in this period.' : 'This account did not send money on in this period.'}
          </div>
        )}
        {loading && <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', pointerEvents: 'none' }}><div className="spin" /></div>}
        {err && <div className="empty">{err}</div>}
        <div className="trace-hint">click any account to follow the money from there · ◆ trading account ● bank account · dashed = trades · dotted = same owner</div>
      </div>
      <div className="trace-side">
        <h4 style={{ margin: '0 0 6px', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--muted)' }}>Tracing</h4>
        <div style={{ fontFamily: 'var(--mono)', fontSize: 15, color: '#7a1f33', wordBreak: 'break-all' }}>{cur}</div>
        {data && (
          <div className="kv" style={{ margin: '12px 0' }}>
            <div><span>upstream</span><b>{data.reach.up}</b></div>
            <div><span>downstream</span><b>{data.reach.down}</b></div>
            <div style={{ gridColumn: '1 / 3' }}><span>flagged by TwinTrace</span><b style={{ color: data.reach.flagged ? '#d17183' : undefined }}>{data.reach.flagged} accounts</b></div>
          </div>
        )}
        {data && data.nodes.find((n) => n.id === cur) && data.nodes.find((n) => n.id === cur).alerts.map((a) => (
          <button key={a} className="btn sm danger" style={{ margin: '0 6px 8px 0' }} onClick={() => onOpenAlert(a)}>⚑ Open {a}</button>
        ))}
        <h4 style={{ margin: '14px 0 8px', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--muted)' }}>◀ Sources ({up.length})</h4>
        {up.slice(0, 14).map((n) => <Row key={n.id} n={n} />)}
        <h4 style={{ margin: '14px 0 8px', fontSize: 11, letterSpacing: '0.14em', textTransform: 'uppercase', color: 'var(--muted)' }}>Destinations ({down.length}) ▶</h4>
        {down.slice(0, 14).map((n) => <Row key={n.id} n={n} />)}
      </div>
    </div>
  )
}

function draw(n, ctx, gs, origin) {
  const flagged = n.alerts.length > 0
  const isO = n.id === origin
  const col = isO ? '#7a1f33' : flagged ? '#b0303a' : n.k === 'b' ? '#4d6b78' : '#8b6b4e'
  const r = isO ? 8.5 : flagged ? 6.5 : 5
  ctx.save()
  if (isO || flagged) {
    ctx.beginPath()
    ctx.arc(n.x, n.y, r + 6 + (isO ? Math.sin(performance.now() / 260) * 1.6 : 0), 0, 6.2832)
    ctx.fillStyle = hexA(col, 0.18)
    ctx.fill()
    ctx.shadowColor = col
    ctx.shadowBlur = 16
  }
  ctx.beginPath()
  if (n.k === 'd') {
    ctx.moveTo(n.x, n.y - r * 1.3); ctx.lineTo(n.x + r * 1.3, n.y); ctx.lineTo(n.x, n.y + r * 1.3); ctx.lineTo(n.x - r * 1.3, n.y); ctx.closePath()
  } else ctx.arc(n.x, n.y, r, 0, 6.2832)
  ctx.fillStyle = col
  ctx.fill()
  ctx.shadowBlur = 0
  ctx.lineWidth = 1.5
  ctx.strokeStyle = '#e1ddd6'
  ctx.stroke()
  if (isO || flagged || n.dist <= 1 || gs > 1.6) {
    ctx.font = `${isO ? 5.2 : 4.2}px JetBrains Mono, monospace`
    ctx.textAlign = 'center'
    ctx.fillStyle = isO ? '#7a1f33' : 'rgba(79, 109, 122, 0.85)'
    ctx.fillText(short(n.id), n.x, n.y + r + 8)
  }
  ctx.restore()
}
