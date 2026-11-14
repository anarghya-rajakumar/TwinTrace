import React, { useEffect, useImperativeHandle, useRef, forwardRef } from 'react'
import Globe from 'globe.gl'
import * as topojson from 'topojson-client'
import land from 'world-atlas/land-110m.json'
import { COLORS, hexA, typ } from '../util'

// Our data has no geography, so every ring gets an illustrative spot near one of these world financial regions.
// The location is a stable hash of the alert id: the same ring always lands in the same place.
const HUBS = [
  [40.7, -74.0], [51.5, -0.1], [50.1, 8.7], [47.4, 8.5], [25.2, 55.3], [19.1, 72.9], [12.97, 77.6], [28.6, 77.2], [13.1, 80.3],
  [1.35, 103.8], [22.3, 114.2], [35.7, 139.7], [31.2, 121.5], [37.6, 127.0], [-33.9, 151.2], [-23.5, -46.6], [-26.2, 28.0],
  [43.7, -79.4], [6.5, 3.4], [-1.3, 36.8], [41.0, 29.0], [19.4, -99.1], [9.0, -79.5], [49.6, 6.1], [52.4, 4.9], [37.8, -122.4],
]
const hash = (str) => {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) }
  return h >>> 0
}
function place(id) {
  const h = hash(id)
  const hub = HUBS[h % HUBS.length]
  const a = ((h >>> 8) % 1000) / 1000, b = ((h >>> 16) % 1000) / 1000
  return { lat: Math.max(-70, Math.min(75, hub[0] + (a - 0.5) * 12)), lng: ((hub[1] + (b - 0.5) * 14 + 540) % 360) - 180 }
}

/** The globe: one glowing point per flagged ring, no lines. Select a ring to see its accounts and money arcs. */
const BoardGlobe = forwardRef(function BoardGlobe(props, ref) {
  const { board } = props
  const el = useRef(null)
  const S = useRef({ p: props, g: null, sig: '', prevT: null, pulses: [], loc: new Map(), ready: false })
  S.current.p = props

  const locOf = (s, id) => {
    let l = s.loc.get(id)
    if (!l) { l = place(id); s.loc.set(id, l) }
    return l
  }

  useEffect(() => {
    const s = S.current
    const landFeat = topojson.feature(land, land.objects.land)
    const whole = (landFeat.features || [landFeat])[0]
    // one feature per landmass: the hex fill copes much better than with a single giant multipolygon
    const countries = whole.geometry.type === 'MultiPolygon'
      ? whole.geometry.coordinates.map((c) => ({ type: 'Feature', geometry: { type: 'Polygon', coordinates: c } }))
      : [whole]
    const g = Globe()(el.current)
      .backgroundColor('#050912')
      .showAtmosphere(true)
      .atmosphereColor('#22d3ee')
      .atmosphereAltitude(0.2)
      .polygonsData(countries)
      .polygonCapColor(() => 'rgba(52,92,170,0.62)')
      .polygonSideColor(() => 'rgba(34,211,238,0.10)')
      .polygonStrokeColor(() => 'rgba(120,190,255,0.55)')
      .polygonAltitude(0.004)
      .pointLat('lat').pointLng('lng').pointAltitude('alt').pointRadius('r').pointColor('color').pointResolution(10)
      .pointLabel((d) => d.label)
      .onPointClick((d) => {
        if (d.kind === 'ring') s.p.onAlertClick && s.p.onAlertClick(d.ai)
        else s.p.onNodeClick && s.p.onNodeClick({ id: d.id }, d.ai)
      })
      .onGlobeClick(() => s.p.onBackground && s.p.onBackground())
      .arcStartLat('a0').arcStartLng('b0').arcEndLat('a1').arcEndLng('b1').arcColor('color').arcStroke('w').arcAltitude(0.045)
      .arcDashLength(0.35).arcDashGap(0.2).arcDashAnimateTime(1500)
      .ringLat('lat').ringLng('lng').ringColor((d) => (tt) => hexA(d.color, 1 - tt)).ringMaxRadius(7).ringPropagationSpeed(5).ringRepeatPeriod(0)
    const mat = g.globeMaterial()
    mat.color.set('#0a1530')
    mat.emissive.set('#06102a')
    mat.emissiveIntensity = 0.7
    g.pointOfView({ lat: 22, lng: 40, altitude: 2.25 }, 0)
    const c = g.controls()
    c.autoRotate = props.orbit !== false
    c.autoRotateSpeed = 0.45
    c.enableDamping = true
    let t
    c.addEventListener('start', () => { c.autoRotate = false; clearTimeout(t) })
    c.addEventListener('end', () => { clearTimeout(t); t = setTimeout(() => { c.autoRotate = s.p.orbit !== false }, 9000) })
    s.g = g
    s.ready = true
    window.__globe = s
    const resize = () => el.current && g.width(el.current.clientWidth).height(el.current.clientHeight)
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el.current)
    setTimeout(() => props.onReady && props.onReady(), 200)
    return () => { clearTimeout(t); ro.disconnect(); g._destructor && g._destructor() }
  }, [])

  useEffect(() => {
    const s = S.current
    if (s.g) s.g.controls().autoRotate = props.orbit !== false
  }, [props.orbit])

  // ------------------------------------------------------------------ what is on the globe right now
  useEffect(() => {
    const s = S.current
    if (!s.g || !board) return
    const p = s.p, t = p.tRef.current
    const f = p.filters
    const layerOk = (a) => (a.layer === 'money' ? f.bank : a.layer === 'trade' ? f.trade : f.bank || f.trade)
    const shown = board.alerts.map((a, i) => ({ a, i })).filter(({ a }) => a.score >= p.thr[a.grp] && a.t1 <= t && layerOk(a))
    const sel = p.focusSet
    const selAi = sel ? board.alerts.findIndex((a) => a.acc.length === sel.size && a.acc.every((x) => sel.has(x))) : -1
    const missed = p.showTruth ? board.rings.filter((r) => r.t0 <= t && !r.det.some((ai) => board.alerts[ai] && board.alerts[ai].score >= p.thr[board.alerts[ai].grp])) : []
    const sig = [shown.length, shown[shown.length - 1] && shown[shown.length - 1].i, p.showTruth, selAi, missed.length, board.alerts.length, f.bank, f.trade].join('|')
    if (sig !== s.sig) {
      s.sig = sig
      const pts = shown.map(({ a, i }) => {
        const l = locOf(s, a.id)
        const base = typ(a.typ).color
        const col = p.showTruth ? (a.hit ? COLORS.green : COLORS.red) : base
        return { kind: 'ring', ai: i, lat: l.lat, lng: l.lng, alt: 0.004 + (a.score / 100) * 0.018 + (selAi === i ? 0.02 : 0), r: 0.28 + (a.score / 100) * 0.3 + (selAi === i ? 0.3 : 0),
          color: sel && selAi !== i ? hexA(col, 0.25) : col,
          label: `<div class="graph-tooltip"><b style="color:${base}">${typ(a.typ).label}</b> · ${a.id}<br/>risk ${a.score.toFixed(0)} · ${a.n} accounts<br/><span style="color:#6f7f9f">click to open the case file</span></div>` }
      })
      missed.forEach((r) => {
        const l = locOf(s, r.id)
        pts.push({ kind: 'missed', ai: -1, lat: l.lat, lng: l.lng, alt: 0.006, r: 0.3, color: COLORS.amber, label: `<div class="graph-tooltip"><b style="color:${COLORS.amber}">missed ring</b> · ${r.id}</div>` })
      })
      const arcs = []
      if (selAi >= 0) {                                   // the selected ring opens up into its accounts and money arcs
        const a = board.alerts[selAi]
        const c = locOf(s, a.id)
        const pos = new Map()
        a.acc.forEach((idx, k) => {
          const ang = (k / a.acc.length) * 6.2832
          const rad = 2.4 + (a.acc.length > 12 ? 1.2 : 0)
          const lat = c.lat + Math.sin(ang) * rad, lng = c.lng + Math.cos(ang) * rad / Math.max(0.35, Math.cos(c.lat * 0.01745))
          pos.set(idx, { lat, lng })
          const n = board.nodes[idx]
          pts.push({ kind: 'acct', id: n.id, ai: selAi, lat, lng, alt: 0.012, r: 0.2, color: n.k === 'd' ? '#a58cf0' : '#7fb0ff',
            label: `<div class="graph-tooltip"><b>${n.id}</b><br/>${n.k === 'd' ? 'trading account' : 'bank account'}<br/><span style="color:#6f7f9f">click to trace the money</span></div>` })
        })
        const agg = new Map()
        board.events.forEach((e) => {
          if (e[5] !== selAi || !pos.has(e[1]) || !pos.has(e[2]) || e[1] === e[2]) return
          const k = `${e[1]}|${e[2]}`
          agg.set(k, (agg.get(k) || 0) + e[3])
        })
        const col = typ(a.typ).color
        const mx = Math.max(1, ...agg.values())
        ;[...agg.entries()].slice(0, 60).forEach(([k, amt]) => {
          const [u, v] = k.split('|').map(Number)
          arcs.push({ a0: pos.get(u).lat, b0: pos.get(u).lng, a1: pos.get(v).lat, b1: pos.get(v).lng, color: [hexA(col, 0.9), hexA(col, 0.25)], w: 0.25 + (amt / mx) * 0.9 })
        })
      }
      s.g.pointsData(pts).arcsData(arcs)
    }
    // alerts that fire while the replay plays: a ripple on the globe
    const prev = s.prevT
    if (p.playing && prev !== null && t > prev && t - prev < 2) {
      board.alerts.forEach((a, i) => {
        if (a.t1 > prev && a.t1 <= t && a.score >= p.thr[a.grp] && layerOk(a)) {
          const l = locOf(s, a.id)
          const rg = { lat: l.lat, lng: l.lng, color: typ(a.typ).color, t0: performance.now() }
          s.pulses.push(rg)
          s.g.ringsData([...s.pulses])
          setTimeout(() => { s.pulses = s.pulses.filter((x) => x !== rg); s.g.ringsData([...s.pulses]) }, 2600)
          p.onFire && p.onFire(a, i)
        }
      })
    }
    s.prevT = t
  }, [props.t, props.thr, props.filters, props.showTruth, props.focusSet, props.playing, props.version])

  useImperativeHandle(ref, () => ({
    zoomToAlert(ai) {
      const s = S.current, a = s.p.board.alerts[ai]
      if (!a) return
      const l = locOf(s, a.id)
      s.g.controls().autoRotate = false
      s.g.pointOfView({ lat: l.lat, lng: l.lng, altitude: 0.42 }, 1100)
    },
    zoomToIdxs(idxs) {
      const s = S.current
      const set = new Set((idxs || []).filter((x) => x !== undefined))
      const ai = s.p.board.alerts.findIndex((a) => a.acc.some((x) => set.has(x)))
      if (ai >= 0) this.zoomToAlert(ai)
    },
    zoomToNode() {},
    fit() {
      S.current.g.pointOfView({ lat: 22, lng: 40, altitude: 2.25 }, 900)
    },
    nodeByAccount() { return undefined },
  }))

  return (
    <div className="board-canvas">
      <div ref={el} style={{ position: 'absolute', inset: 0 }} />
      <div className="globe-note">Illustrative placement: our data has no geography, so each ring sits at a made-up spot on the map.</div>
    </div>
  )
})
export default BoardGlobe
