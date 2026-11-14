import React, { useEffect, useImperativeHandle, useRef, forwardRef } from 'react'
import ForceGraph from 'force-graph'
import { forceX, forceY } from 'd3-force'
import { COLORS, hexA, short, typ } from '../util'

const SPR = new Map()
/** Pre-rendered radial glow: drawImage is orders of magnitude cheaper than shadowBlur on thousands of nodes. */
function sprite(col) {
  let c = SPR.get(col)
  if (!c) {
    c = document.createElement('canvas')
    c.width = c.height = 64
    const x = c.getContext('2d')
    const g = x.createRadialGradient(32, 32, 0, 32, 32, 32)
    g.addColorStop(0, hexA(col, 0.95))
    g.addColorStop(0.28, hexA(col, 0.5))
    g.addColorStop(1, hexA(col, 0))
    x.fillStyle = g
    x.fillRect(0, 0, 64, 64)
    SPR.set(col, c)
  }
  return c
}
const DIM_BANK = '#33497a'
const DIM_DEMAT = '#4d3f8c'

/** The investigation board: every account as a node, every transfer/trade as a timed edge. Imperative canvas. */
const Board = forwardRef(function Board(props, ref) {
  const { board, version, tRef } = props
  const el = useRef(null)
  const S = useRef({ p: props, nodes: [], links: [], linkMap: new Map(), nNodes: 0, nEv: 0, nOwn: 0, nAlerts: 0, nRings: 0,
    ripples: [], prevT: null, ready: false, graph: null })

  S.current.p = props

  // redraw only when something visible changed (or continuously while the replay plays / a case is focused)
  useEffect(() => {
    const g = S.current.graph
    if (!g) return
    g.autoPauseRedraw(!(props.playing || props.focusSet))
    g.nodeColor(g.nodeColor())   // re-setting an accessor schedules a repaint
  }, [props.t, props.thr, props.filters, props.showTruth, props.focusSet, props.playing, version])

  // ------------------------------------------------------------------ one-time graph creation
  useEffect(() => {
    const s = S.current
    const g = ForceGraph()(el.current)
      .backgroundColor('rgba(0,0,0,0)')
      .nodeId('idx')
      .nodeRelSize(2.4)
      .nodeVal((n) => (n.alerts.length ? 2.2 : 0.7))
      .nodeLabel((n) => {
        const al = n.alerts.map((i) => s.p.board.alerts[i]).filter((a) => a.score >= s.p.thr[a.grp])
        const lines = al.slice(0, 3).map((a) => `<span style="color:${typ(a.typ).color}">● ${a.id} ${typ(a.typ).label}</span>`)
        return `<b>${n.id}</b><br/>${n.k === 'b' ? 'bank account' : 'trading account'}${lines.length ? '<br/>' + lines.join('<br/>') : ''}<br/><span style="color:#6f7f9f">click to trace the money</span>`
      })
      .nodeVisibility((n) => visibleNode(s, n))
      .nodeColor((n) => nodeColor(s, n))
      .nodeCanvasObjectMode((n) => (special(s, n) ? 'replace' : undefined))
      .nodeCanvasObject((n, ctx, gs) => drawNode(s, n, ctx, gs))
      .nodePointerAreaPaint((n, color, ctx) => {
        ctx.fillStyle = color
        ctx.beginPath()
        ctx.arc(n.x, n.y, special(s, n) ? 7 : 4.5, 0, 2 * Math.PI)
        ctx.fill()
      })
      .linkVisibility((l) => linkVisible(s, l))
      .linkColor((l) => linkColor(s, l))
      .linkWidth((l) => (l.ai >= 0 && alertShown(s, l.ai) ? 1.5 : l.kind === 2 ? 0.8 : 0.5))
      .linkLineDash((l) => (l.kind === 1 ? [2.5, 2] : l.kind === 2 ? [1, 2.5] : null))
      .linkDirectionalArrowLength(0)
      .onNodeClick((n) => s.p.onNodeClick && s.p.onNodeClick(n, bestAlert(s, n)))
      .onBackgroundClick(() => s.p.onBackground && s.p.onBackground())
      .onNodeHover((n) => {
        el.current.style.cursor = n ? 'pointer' : 'default'
      })
      .onRenderFramePost((ctx, gs) => post(s, ctx, gs))
      .maxZoom(6)
      .warmupTicks(20)
      .cooldownTicks(220)
      .cooldownTime(5000)
      .onEngineStop(() => {
        if (!s.fitted) {
          s.fitted = true
          g.zoomToFit(700, 30)
        }
      })
      .d3VelocityDecay(0.32)
    g.d3Force('charge').strength(-24).distanceMax(150)
    g.d3Force('link').distance((l) => (l.ai >= 0 ? 9 : 17)).strength((l) => (l.ai >= 0 ? 0.9 : 0.12))
    g.d3Force('x', forceX(0).strength(0.006))
    g.d3Force('y', forceY(0).strength(0.006))
    s.graph = g
    window.__board = s
    const resize = () => el.current && g.width(el.current.clientWidth).height(el.current.clientHeight)
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el.current)
    return () => {
      ro.disconnect()
      g._destructor && g._destructor()
    }
  }, [])

  // ------------------------------------------------------------------ incremental data sync (initial load + planted rings)
  useEffect(() => {
    const s = S.current
    if (!board || !s.graph) return
    // a planted ring spawns as its own little island out at the edge of the layout, not stacked on one point
    const a0 = Math.random() * 6.283
    let R0 = 160
    s.nodes.forEach((n) => { if (n.x !== undefined) R0 = Math.max(R0, Math.hypot(n.x, n.y)) })
    R0 *= 0.82
    for (let i = s.nNodes; i < board.nodes.length; i++) {
      const b = board.nodes[i]
      const late = s.nNodes > 0
      s.nodes.push({ ...b, idx: i, firstT: Infinity, alerts: [], rings: [],
        x: late ? Math.cos(a0) * R0 + (Math.random() - 0.5) * 40 : undefined, y: late ? Math.sin(a0) * R0 + (Math.random() - 0.5) * 40 : undefined })
    }
    s.nNodes = board.nodes.length
    for (let i = s.nEv; i < board.events.length; i++) {
      const [t, si, di, amt, kind, ai, ri] = board.events[i]
      const a = s.nodes[si], b = s.nodes[di]
      if (t < a.firstT) a.firstT = t
      if (t < b.firstT) b.firstT = t
      const key = `${si}|${di}|${kind}`
      let l = s.linkMap.get(key)
      if (!l) {
        l = { source: a, target: b, kind, amt: 0, n: 0, t0: Infinity, ts: [], ai: -1, ri: -1, seed: Math.random() }
        s.linkMap.set(key, l)
        s.links.push(l)
      }
      l.amt += amt
      l.n += 1
      if (t < l.t0) l.t0 = t
      l.ts.push(t)
      if (ai >= 0 && l.ai < 0) l.ai = ai
      if (ri >= 0 && l.ri < 0) l.ri = ri
    }
    s.nEv = board.events.length
    for (let i = s.nOwn; i < board.owners.length; i++) {
      const [bi, di] = board.owners[i]
      const a = s.nodes[bi], b = s.nodes[di]
      const l = { source: a, target: b, kind: 2, amt: 0, n: 0, t0: Math.max(a.firstT, b.firstT), ts: [], ai: -1, ri: -1, seed: 0, owner: true }
      s.links.push(l)
    }
    s.nOwn = board.owners.length
    for (let i = s.nAlerts; i < board.alerts.length; i++) board.alerts[i].acc.forEach((x) => s.nodes[x] && s.nodes[x].alerts.push(i))
    s.nAlerts = board.alerts.length
    for (let i = s.nRings; i < board.rings.length; i++) board.rings[i].acc.forEach((x) => s.nodes[x] && s.nodes[x].rings.push(i))
    s.nRings = board.rings.length
    s.links.forEach((l) => {
      if (l.owner) l.t0 = Math.max(l.source.firstT, l.target.firstT)
      if (!l.sorted) {
        l.ts.sort((a, b) => a - b)
        l.sorted = true
      }
    })
    const first = !s.ready
    s.graph.graphData({ nodes: s.nodes, links: s.links })
    if (first) {
      s.ready = true
      setTimeout(() => {
        s.graph.zoomToFit(0, 30)
        props.onReady && props.onReady()
      }, 120)
    }
  }, [board, version])

  // ------------------------------------------------------------------ imperative API for the app
  useImperativeHandle(ref, () => ({
    zoomToAlert(ai) {
      const s = S.current
      const a = s.p.board.alerts[ai]
      if (!a) return
      const set = new Set(a.acc)
      s.graph.zoomToFit(900, 150, (n) => set.has(n.idx))
    },
    zoomToNode(idx) {
      const s = S.current
      const n = s.nodes[idx]
      if (n && n.x !== undefined) {
        s.graph.centerAt(n.x, n.y, 800)
        s.graph.zoom(7, 800)
      }
    },
    zoomToIdxs(idxs) {
      const set = new Set((idxs || []).filter((x) => x !== undefined))
      if (set.size) S.current.graph.zoomToFit(900, 170, (n) => set.has(n.idx))
    },
    fit() {
      S.current.graph.zoomToFit(800, 60)
    },
    nodeByAccount(id) {
      return S.current.nodes.find((n) => n.id === id)
    },
  }))

  return <div className="board-canvas" ref={el} />
})

export default Board

// ---------------------------------------------------------------------- helpers (module scope, read the live props)
function visibleNode(s, n) {
  const { tRef, filters } = s.p
  if (n.firstT > tRef.current) return false
  return n.k === 'b' ? filters.bank : filters.trade
}
function alertShown(s, ai) {
  const a = s.p.board.alerts[ai]
  return a && a.score >= s.p.thr[a.grp]
}
function alertFired(s, ai) {
  return alertShown(s, ai) && s.p.board.alerts[ai].t1 <= s.p.tRef.current
}
function bestAlert(s, n) {
  let best = -1, sc = -1
  for (const ai of n.alerts) {
    if (alertFired(s, ai)) {
      const a = s.p.board.alerts[ai]
      if (a.score > sc) { sc = a.score; best = ai }
    }
  }
  return best
}
function missedRing(s, n) {
  if (!s.p.showTruth) return false
  for (const ri of n.rings) {
    const r = s.p.board.rings[ri]
    const caught = r.det.some((ai) => alertShown(s, ai))
    if (!caught && r.t0 <= s.p.tRef.current) return true
  }
  return false
}
function inFocus(s, n) {
  const f = s.p.focusSet
  return !f || f.has(n.idx)
}
function special(s, n) {
  return bestAlert(s, n) >= 0 || missedRing(s, n) || (s.p.focusSet && s.p.focusSet.has(n.idx))
}
function nodeColor(s, n) {
  const dim = !inFocus(s, n)
  const base = n.k === 'b' ? DIM_BANK : DIM_DEMAT
  return dim ? hexA(base, 0.18) : base
}
function linkVisible(s, l) {
  return l.t0 <= s.p.tRef.current && visibleNode(s, l.source) && visibleNode(s, l.target)
}
function linkColor(s, l) {
  const f = s.p.focusSet
  const out = f && !(f.has(l.source.idx) && f.has(l.target.idx))
  const k = out ? 0.1 : 1
  if (l.ai >= 0 && alertShown(s, l.ai)) {
    const a = s.p.board.alerts[l.ai]
    return hexA(typ(a.typ).color, (a.t1 <= s.p.tRef.current ? 0.9 : 0.4) * k)
  }
  if (s.p.showTruth && l.ri >= 0) {
    const r = s.p.board.rings[l.ri]
    if (!r.det.some((ai) => alertShown(s, ai))) return hexA(COLORS.amber, 0.7 * k)
  }
  if (l.kind === 2) return hexA('#9fb0d6', 0.28 * k)
  if (l.kind === 1) return hexA('#8b6fe0', 0.3 * k)
  return hexA('#5a79b5', 0.22 * k)
}
function drawNode(s, n, ctx, gs) {
  const bi = bestAlert(s, n)
  const dim = !inFocus(s, n)
  const miss = missedRing(s, n)
  const sel = s.p.focusSet && s.p.focusSet.has(n.idx)
  ctx.save()
  ctx.globalAlpha = dim ? 0.22 : 1
  let col = n.k === 'b' ? '#6c93e0' : '#a58cf0'
  let r = 2.6
  let a = null
  if (bi >= 0) {
    a = s.p.board.alerts[bi]
    col = typ(a.typ).color
    r = 3 + (a.score / 100) * 2.6
  } else if (miss) {
    col = COLORS.amber
    r = 3.2
  }
  if (sel) r += 1.6
  const demat = n.k === 'd'
  const path = (rad) => {
    ctx.beginPath()
    if (demat) {
      ctx.moveTo(n.x, n.y - rad * 1.25)
      ctx.lineTo(n.x + rad * 1.25, n.y)
      ctx.lineTo(n.x, n.y + rad * 1.25)
      ctx.lineTo(n.x - rad * 1.25, n.y)
      ctx.closePath()
    } else ctx.arc(n.x, n.y, rad, 0, 6.2832)
  }
  if (bi >= 0 || sel) {
    const R = (r + 3) * 2.6
    ctx.drawImage(sprite(col), n.x - R, n.y - R, 2 * R, 2 * R)
  }
  path(r)
  ctx.fillStyle = col
  ctx.fill()
  if (s.p.showTruth && a) {
    path(r + 2.4)
    ctx.lineWidth = 1.1
    if (a.hit) { ctx.strokeStyle = COLORS.green; ctx.setLineDash([]) } else { ctx.strokeStyle = COLORS.red; ctx.setLineDash([2, 1.5]) }
    ctx.stroke()
  } else if (miss && !a) {
    path(r + 2.6)
    ctx.lineWidth = 1
    ctx.strokeStyle = COLORS.amber
    ctx.setLineDash([2, 1.5])
    ctx.stroke()
  }
  if (sel) {
    path(r + 1)
    ctx.lineWidth = 1.2
    ctx.strokeStyle = '#fff'
    ctx.setLineDash([])
    ctx.stroke()
  }
  if (gs > 3.2 && (a || sel)) {
    ctx.font = `${9 / Math.min(gs, 7) + 2.5}px JetBrains Mono, monospace`
    ctx.fillStyle = 'rgba(214,224,245,0.9)'
    ctx.textAlign = 'center'
    ctx.fillText(short(n.id), n.x, n.y + r + 6)
  }
  ctx.restore()
}

function lerpPt(l, p) {
  return [l.source.x + (l.target.x - l.source.x) * p, l.source.y + (l.target.y - l.source.y) * p]
}
function activeLink(s, l, t) {
  // recently active (money is moving now) or part of the selected case
  if (s.p.focusSet && s.p.focusSet.has(l.source.idx) && s.p.focusSet.has(l.target.idx) && l.kind !== 2) return true
  if (!s.p.playing) return false
  const ts = l.ts
  if (!ts.length || ts[0] > t) return false
  let lo = 0, hi = ts.length - 1
  while (lo < hi) {
    const m = (lo + hi + 1) >> 1
    if (ts[m] <= t) lo = m
    else hi = m - 1
  }
  return t - ts[lo] < 0.9
}

function post(s, ctx, gs) {
  const t = s.p.tRef.current
  const now = performance.now()
  // moving money: particles on active links
  const links = s.links
  for (let i = 0; i < links.length; i++) {
    const l = links[i]
    if (l.kind === 2 || l.source.x === undefined || !linkVisible(s, l) || !activeLink(s, l, t)) continue
    const alerty = l.ai >= 0 && alertShown(s, l.ai)
    const col = alerty ? typ(s.p.board.alerts[l.ai].typ).color : l.kind === 1 ? '#a78bfa' : '#8fd8ff'
    for (let k = 0; k < 2; k++) {
      const p = ((now / 1000) * 0.55 + l.seed + k * 0.5) % 1
      const [x, y] = lerpPt(l, p)
      const R = (alerty ? 5 : 3.6) / Math.max(1, gs * 0.35)
      ctx.drawImage(sprite(col), x - R, y - R, 2 * R, 2 * R)
    }
  }
  // alerts firing while the replay plays
  const prev = s.prevT
  if (s.p.playing && prev !== null && t > prev && t - prev < 2) {
    const als = s.p.board.alerts
    for (let i = 0; i < als.length; i++) {
      const a = als[i]
      if (a.t1 > prev && a.t1 <= t && a.score >= s.p.thr[a.grp]) {
        let cx = 0, cy = 0, c = 0
        for (const x of a.acc) {
          const n = s.nodes[x]
          if (n && n.x !== undefined) { cx += n.x; cy += n.y; c++ }
        }
        if (c) s.ripples.push({ x: cx / c, y: cy / c, t0: now, col: typ(a.typ).color })
        s.p.onFire && s.p.onFire(a, i)
      }
    }
  }
  s.prevT = t
  // ripples
  s.ripples = s.ripples.filter((r) => now - r.t0 < 1800)
  for (const r of s.ripples) {
    const k = (now - r.t0) / 1800
    ctx.beginPath()
    ctx.arc(r.x, r.y, 6 + k * 70, 0, 6.2832)
    ctx.strokeStyle = hexA(r.col, (1 - k) * 0.85)
    ctx.lineWidth = 2.2 * (1 - k) + 0.4
    ctx.stroke()
    ctx.beginPath()
    ctx.arc(r.x, r.y, 4 + k * 30, 0, 6.2832)
    ctx.fillStyle = hexA(r.col, (1 - k) * 0.25)
    ctx.fill()
  }
}
