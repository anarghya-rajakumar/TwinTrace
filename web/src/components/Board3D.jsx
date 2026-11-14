import React, { useEffect, useImperativeHandle, useRef, forwardRef } from 'react'
import ForceGraph3D from '3d-force-graph'
import * as THREE from 'three'
import { forceX, forceZ } from 'd3-force-3d'
import { COLORS, hexA, typ } from '../util'

// Two stacked layers: bank accounts live on the lower plane, trading accounts on the upper plane,
// and the owner links (bank <-> trading) rise between them.
const Y_BANK = -80
const Y_TRADE = 80

const glowTex = {}
function glow(col) {
  if (!glowTex[col]) {
    const c = document.createElement('canvas')
    c.width = c.height = 64
    const x = c.getContext('2d')
    const g = x.createRadialGradient(32, 32, 0, 32, 32, 32)
    g.addColorStop(0, hexA(col, 0.95))
    g.addColorStop(0.3, hexA(col, 0.45))
    g.addColorStop(1, hexA(col, 0))
    x.fillStyle = g
    x.fillRect(0, 0, 64, 64)
    glowTex[col] = new THREE.CanvasTexture(c)
  }
  return glowTex[col]
}
let ringTexCache
function ringTex() {
  if (!ringTexCache) {
    const c = document.createElement('canvas')
    c.width = c.height = 64
    const x = c.getContext('2d')
    x.strokeStyle = '#fff'
    x.lineWidth = 5
    x.beginPath()
    x.arc(32, 32, 26, 0, 6.2832)
    x.stroke()
    ringTexCache = new THREE.CanvasTexture(c)
  }
  return ringTexCache
}
function labelSprite(text, col) {
  const c = document.createElement('canvas')
  c.width = 512
  c.height = 96
  const x = c.getContext('2d')
  x.font = '600 40px JetBrains Mono, monospace'
  x.fillStyle = col
  x.fillText(text, 8, 56)
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false }))
  s.scale.set(190, 36, 1)
  return s
}

const BOX = new THREE.OctahedronGeometry(1, 0)
const BALL = new THREE.SphereGeometry(1, 10, 8)

/** 3D investigation board. Same props and imperative API as the 2D Board, so the app can swap them. */
const Board3D = forwardRef(function Board3D(props, ref) {
  const { board, version, tRef } = props
  const el = useRef(null)
  const S = useRef({ p: props, nodes: [], links: [], linkMap: new Map(), nNodes: 0, nEv: 0, nOwn: 0, nAlerts: 0, nRings: 0, ripples: [], prevT: null,
    ready: false, graph: null, orbit: { angle: 0.6, on: true }, sig: '' })
  S.current.p = props

  useEffect(() => {
    const s = S.current
    const g = ForceGraph3D({ controlType: 'orbit' })(el.current)
      .backgroundColor('#050912')
      .showNavInfo(false)
      .nodeId('idx')
      .nodeLabel((n) => {
        const al = n.alerts.map((i) => s.p.board.alerts[i]).filter((a) => a.score >= s.p.thr[a.grp])
        const lines = al.slice(0, 3).map((a) => `<span style="color:${typ(a.typ).color}">● ${a.id} ${typ(a.typ).label}</span>`)
        return `<div class="graph-tooltip"><b>${n.id}</b><br/>${n.k === 'b' ? 'bank account (lower layer)' : 'trading account (upper layer)'}${lines.length ? '<br/>' + lines.join('<br/>') : ''}<br/><span style="color:#6f7f9f">click to trace the money</span></div>`
      })
      .nodeThreeObject((n) => makeNode(s, n))
      .nodeThreeObjectExtend(false)
      .linkColor((l) => linkColor(s, l))
      .linkWidth(0)
      .linkOpacity(1)
      .onNodeClick((n) => s.p.onNodeClick && s.p.onNodeClick(n, bestAlert(s, n)))
      .onBackgroundClick(() => s.p.onBackground && s.p.onBackground())
      .warmupTicks(15)
      .cooldownTicks(200)
      .cooldownTime(5000)
      .d3VelocityDecay(0.35)
      .onEngineStop(() => {
        if (!s.fitted) {
          s.fitted = true
          frameAll(s)
        }
      })
    g.d3Force('charge').strength(-22).distanceMax(160)
    g.d3Force('link').distance((l) => (l.ai >= 0 ? 9 : 18)).strength((l) => (l.ai >= 0 ? 0.9 : 0.1))
    g.d3Force('x', forceX(0).strength(0.006))
    g.d3Force('z', forceZ(0).strength(0.006))
    s.graph = g
    window.__board3d = s

    // two translucent layer planes with a faint grid, plus labels
    const scene = g.scene()
    const mkPlane = (y, col, label) => {
      const grp = new THREE.Group()
      const plane = new THREE.Mesh(new THREE.PlaneGeometry(900, 900), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.06, side: THREE.DoubleSide, depthWrite: false }))
      plane.rotation.x = -Math.PI / 2
      const grid = new THREE.GridHelper(900, 18, col, col)
      grid.material.transparent = true
      grid.material.opacity = 0.16
      grid.material.depthWrite = false
      const lab = labelSprite(label, col)
      lab.position.set(-380, 0, 440)
      grp.add(plane, grid, lab)
      grp.position.y = y
      scene.add(grp)
      return grp
    }
    s.planes = [mkPlane(Y_BANK, '#4c78c9', 'BANK LAYER · accounts'), mkPlane(Y_TRADE, '#8b6fe0', 'TRADING LAYER · stock accounts')]
    // moving-money particles: one Points object driven every frame
    const MAXP = 1600
    const pg = new THREE.BufferGeometry()
    pg.setAttribute('position', new THREE.BufferAttribute(new Float32Array(MAXP * 3), 3))
    pg.setAttribute('color', new THREE.BufferAttribute(new Float32Array(MAXP * 3), 3))
    pg.setDrawRange(0, 0)
    s.pts = new THREE.Points(pg, new THREE.PointsMaterial({ size: 4.2, vertexColors: true, map: glow('#ffffff'), transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true }))
    s.pts.frustumCulled = false
    s.MAXP = MAXP
    scene.add(s.pts)

    const resize = () => el.current && g.width(el.current.clientWidth).height(el.current.clientHeight)
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el.current)
    const stopOrbit = () => { s.orbit.touch = performance.now() }
    el.current.addEventListener('pointerdown', stopOrbit)
    el.current.addEventListener('wheel', stopOrbit, { passive: true })

    let raf
    const loop = () => {
      raf = requestAnimationFrame(loop)
      frame(s)
    }
    raf = requestAnimationFrame(loop)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      g._destructor && g._destructor()
    }
  }, [])

  // ------------------------------------------------------------------ incremental data sync
  useEffect(() => {
    const s = S.current
    if (!board || !s.graph) return
    const a0 = Math.random() * 6.283
    let R0 = 200
    s.nodes.forEach((n) => { if (n.x !== undefined) R0 = Math.max(R0, Math.hypot(n.x, n.z || 0)) })
    R0 *= 0.8
    for (let i = s.nNodes; i < board.nodes.length; i++) {
      const b = board.nodes[i]
      const late = s.nNodes > 0
      s.nodes.push({ ...b, idx: i, firstT: Infinity, alerts: [], rings: [], fy: b.k === 'b' ? Y_BANK : Y_TRADE,
        x: late ? Math.cos(a0) * R0 + (Math.random() - 0.5) * 40 : (Math.random() - 0.5) * 300,
        z: late ? Math.sin(a0) * R0 + (Math.random() - 0.5) * 40 : (Math.random() - 0.5) * 300, y: b.k === 'b' ? Y_BANK : Y_TRADE })
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
      s.links.push({ source: s.nodes[bi], target: s.nodes[di], kind: 2, amt: 0, n: 0, t0: 0, ts: [], ai: -1, ri: -1, seed: 0, owner: true })
    }
    s.nOwn = board.owners.length
    for (let i = s.nAlerts; i < board.alerts.length; i++) board.alerts[i].acc.forEach((x) => s.nodes[x] && s.nodes[x].alerts.push(i))
    s.nAlerts = board.alerts.length
    for (let i = s.nRings; i < board.rings.length; i++) board.rings[i].acc.forEach((x) => s.nodes[x] && s.nodes[x].rings.push(i))
    s.nRings = board.rings.length
    s.links.forEach((l) => {
      if (l.owner) l.t0 = Math.max(l.source.firstT, l.target.firstT)
      if (!l.sorted) { l.ts.sort((a, b) => a - b); l.sorted = true }
    })
    // nodes created before their alerts/rings were attached need their glow objects; rebuild lazily
    s.nodes.forEach((n) => { if (n.__threeObj && !n.__decorated && (n.alerts.length || n.rings.length)) decorate(n) })
    const first = !s.ready
    s.graph.graphData({ nodes: s.nodes, links: s.links })
    s.nodes.forEach((n) => { if (n.__threeObj && !n.__decorated && (n.alerts.length || n.rings.length)) decorate(n) })
    s.sig = ''
    if (first) {
      s.ready = true
      setTimeout(() => {
        s.graph.cameraPosition({ x: 40, y: 420, z: 720 }, { x: 0, y: 0, z: 0 }, 0)
        props.onReady && props.onReady()
      }, 120)
    }
  }, [board, version])

  // recolour links when thresholds / truth overlay change (debounced: re-digesting thousands of links is not free)
  useEffect(() => {
    const s = S.current
    if (!s.graph || !s.ready) return
    const id = setTimeout(() => { s.graph.linkColor(s.graph.linkColor()); s.sig = '' }, 220)
    return () => clearTimeout(id)
  }, [props.thr, props.showTruth])

  useImperativeHandle(ref, () => ({
    zoomToAlert(ai) {
      const a = S.current.p.board.alerts[ai]
      if (a) focusOn(S.current, a.acc)
    },
    zoomToIdxs(idxs) {
      focusOn(S.current, (idxs || []).filter((x) => x !== undefined))
    },
    zoomToNode(idx) {
      focusOn(S.current, [idx])
    },
    fit() {
      frameAll(S.current)
    },
    nodeByAccount(id) {
      return S.current.nodes.find((n) => n.id === id)
    },
  }))

  return <div className="board-canvas" ref={el} />
})

export default Board3D

// ---------------------------------------------------------------------------------------------- node objects
function makeNode(s, n) {
  const grp = new THREE.Group()
  const mat = new THREE.MeshBasicMaterial({ color: n.k === 'b' ? 0x33497a : 0x4d3f8c, transparent: true })
  const core = new THREE.Mesh(n.k === 'b' ? BALL : BOX, mat)
  core.scale.setScalar(n.k === 'b' ? 1.1 : 1.5)
  grp.add(core)
  grp.__core = core
  n.__core = core
  if (n.alerts.length || n.rings.length) decorate(n, grp)
  return grp
}
function decorate(n, grp) {
  grp = grp || n.__threeObj
  if (!grp || n.__decorated) return
  const gl = new THREE.Sprite(new THREE.SpriteMaterial({ map: glow('#ffffff'), color: 0xffffff, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }))
  gl.scale.setScalar(8)
  gl.visible = false
  const ring = new THREE.Sprite(new THREE.SpriteMaterial({ map: ringTex(), color: 0x2ee59d, transparent: true, depthWrite: false }))
  ring.scale.setScalar(9)
  ring.visible = false
  grp.add(gl, ring)
  n.__glow = gl
  n.__ring = ring
  n.__decorated = true
}

// ---------------------------------------------------------------------------------------------- state helpers (shared logic with the 2D board)
function visibleNode(s, n) {
  if (n.firstT > s.p.tRef.current) return false
  return n.k === 'b' ? s.p.filters.bank : s.p.filters.trade
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
    if (!r.det.some((ai) => alertShown(s, ai)) && r.t0 <= s.p.tRef.current) return true
  }
  return false
}
function linkColor(s, l) {
  if (l.ai >= 0 && alertShown(s, l.ai)) return hexA(typ(s.p.board.alerts[l.ai].typ).color, 0.9)
  if (s.p.showTruth && l.ri >= 0) {
    const r = s.p.board.rings[l.ri]
    if (!r.det.some((ai) => alertShown(s, ai))) return hexA(COLORS.amber, 0.75)
  }
  if (l.kind === 2) return hexA('#bcd0ff', l.source.alerts.length || l.target.alerts.length || l.source.rings.length ? 0.55 : 0.05)
  if (l.kind === 1) return hexA('#8b6fe0', 0.35)
  return hexA('#5a79b5', 0.28)
}
function activeLink(s, l, t) {
  const f = s.p.focusSet
  if (f && f.has(l.source.idx) && f.has(l.target.idx) && l.kind !== 2) return true
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

const _c = new THREE.Color()
// camera placed from the real extent of the layout: above and in front, looking at the middle of the two layers
function frameAll(s, ms = 900) {
  let r = 120
  s.nodes.forEach((n) => { if (n.x !== undefined) r = Math.max(r, Math.hypot(n.x, n.z)) })
  s.graph.cameraPosition({ x: r * 0.15, y: r * 0.95, z: r * 1.55 }, { x: 0, y: 0, z: 0 }, ms)
}
function focusOn(s, idxs) {
  const ns = idxs.map((i) => s.nodes[i]).filter((n) => n && n.x !== undefined)
  if (!ns.length) return
  let cx = 0, cy = 0, cz = 0
  ns.forEach((n) => { cx += n.x; cy += n.y; cz += n.z })
  cx /= ns.length; cy /= ns.length; cz /= ns.length
  let r = 30
  ns.forEach((n) => { r = Math.max(r, Math.hypot(n.x - cx, n.y - cy, n.z - cz)) })
  const d = r * 2.6 + 70
  const cam = s.graph.camera().position
  const dir = new THREE.Vector3(cam.x - cx, cam.y - cy, cam.z - cz).normalize()
  if (!isFinite(dir.x)) dir.set(0, 0.5, 1)
  s.graph.cameraPosition({ x: cx + dir.x * d, y: cy + dir.y * d + 20, z: cz + dir.z * d }, { x: cx, y: cy, z: cz }, 1000)
  s.orbit.touch = performance.now()
}

// ---------------------------------------------------------------------------------------------- per-frame update
function frame(s) {
  const p = s.p
  if (!s.ready || !p.board) return
  const t = p.tRef.current
  const now = performance.now()
  // gentle auto-orbit until the user touches the view
  if (p.orbit && (!s.orbit.touch || now - s.orbit.touch > 12000) && s.fitted) {
    const cam = s.graph.camera()
    const ang = 0.0016
    const x = cam.position.x, z = cam.position.z
    cam.position.x = x * Math.cos(ang) - z * Math.sin(ang)
    cam.position.z = x * Math.sin(ang) + z * Math.cos(ang)
    cam.lookAt(0, 0, 0)
  }
  const sig = [Math.round(t * 20), p.thr.money, p.thr.trade, p.filters.bank, p.filters.trade, p.showTruth, p.focusSet ? p.focusSet.size + ':' + [...p.focusSet][0] : 0, s.nodes.length].join('|')
  if (sig !== s.sig) {
    s.sig = sig
    const f = p.focusSet
    for (const n of s.nodes) {
      const obj = n.__threeObj
      if (!obj) continue
      const vis = visibleNode(s, n)
      obj.visible = vis
      if (!vis) continue
      const dim = f && !f.has(n.idx)
      const core = n.__core
      const bi = n.alerts.length ? bestAlert(s, n) : -1
      const miss = n.rings.length ? missedRing(s, n) : false
      let col = n.k === 'b' ? '#33497a' : '#4d3f8c'
      let scale = n.k === 'b' ? 1.1 : 1.5
      let a = null
      if (bi >= 0) {
        a = p.board.alerts[bi]
        col = typ(a.typ).color
        scale = 2.2 + (a.score / 100) * 2.2
      } else if (miss) {
        col = COLORS.amber
        scale = 2.4
      }
      if (f && f.has(n.idx)) scale += 1.3
      core.material.color.set(col)
      core.material.opacity = dim ? 0.18 : 1
      core.scale.setScalar(scale)
      if (n.__glow) {
        const on = (bi >= 0 || miss || (f && f.has(n.idx))) && !dim
        n.__glow.visible = on
        if (on) { n.__glow.material.color.set(col); n.__glow.scale.setScalar(5 + scale * 2.6) }
        n.__ring.visible = !!(p.showTruth && (a || miss) && !dim)
        if (n.__ring.visible) { n.__ring.material.color.set(a ? (a.hit ? COLORS.green : COLORS.red) : COLORS.amber); n.__ring.scale.setScalar(scale * 3.4) }
      }
    }
    for (const l of s.links) {
      const o = l.__lineObj
      if (o) o.visible = l.t0 <= t && visibleNode(s, l.source) && visibleNode(s, l.target) && (!f || l.kind === 2 || (f.has(l.source.idx) && f.has(l.target.idx)) || true)
    }
  }
  // moving money
  const pos = s.pts.geometry.attributes.position, colA = s.pts.geometry.attributes.color
  let k = 0
  const ph = now / 1000
  if (p.playing || p.focusSet) {
    for (let i = 0; i < s.links.length && k < s.MAXP - 2; i++) {
      const l = s.links[i]
      if (l.kind === 2 || l.source.x === undefined || l.t0 > t || !visibleNode(s, l.source) || !visibleNode(s, l.target) || !activeLink(s, l, t)) continue
      const alerty = l.ai >= 0 && alertShown(s, l.ai)
      _c.set(alerty ? typ(p.board.alerts[l.ai].typ).color : l.kind === 1 ? '#a78bfa' : '#8fd8ff')
      for (let j = 0; j < 2; j++) {
        const q = (ph * 0.55 + l.seed + j * 0.5) % 1
        pos.setXYZ(k, l.source.x + (l.target.x - l.source.x) * q, l.source.y + (l.target.y - l.source.y) * q, l.source.z + (l.target.z - l.source.z) * q)
        colA.setXYZ(k, _c.r, _c.g, _c.b)
        k++
      }
    }
  }
  s.pts.geometry.setDrawRange(0, k)
  pos.needsUpdate = true
  colA.needsUpdate = true
  // alerts firing while the replay plays: expanding ring
  const prev = s.prevT
  if (p.playing && prev !== null && t > prev && t - prev < 2) {
    p.board.alerts.forEach((a, i) => {
      if (a.t1 > prev && a.t1 <= t && a.score >= p.thr[a.grp]) {
        let cx = 0, cy = 0, cz = 0, c = 0
        for (const x of a.acc) {
          const n = s.nodes[x]
          if (n && n.x !== undefined) { cx += n.x; cy += n.y; cz += n.z; c++ }
        }
        if (c) {
          const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: ringTex(), color: typ(a.typ).color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }))
          sp.position.set(cx / c, cy / c, cz / c)
          s.graph.scene().add(sp)
          s.ripples.push({ sp, t0: now })
        }
        p.onFire && p.onFire(a, i)
      }
    })
  }
  s.prevT = t
  s.ripples = s.ripples.filter((r) => {
    const q = (now - r.t0) / 1800
    if (q >= 1) { s.graph.scene().remove(r.sp); r.sp.material.dispose(); return false }
    r.sp.scale.setScalar(10 + q * 120)
    r.sp.material.opacity = (1 - q) * 0.9
    return true
  })
}
