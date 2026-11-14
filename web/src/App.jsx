import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { COLORS, typ } from './util'
import Board from './components/Board.jsx'
import TopBar from './components/TopBar.jsx'
import Timeline from './components/Timeline.jsx'
import AlertList from './components/AlertList.jsx'
import CaseFile from './components/CaseFile.jsx'
import TraceView from './components/TraceView.jsx'
import WhatIf from './components/WhatIf.jsx'
import PlantPanel from './components/PlantPanel.jsx'
import Toasts from './components/Toasts.jsx'
import WhatYouSee from './components/WhatYouSee.jsx'

const TOUR = [
  ['Welcome to the board', 'Every dot is an account. Circles are bank accounts, diamonds are trading accounts. The glowing coloured clusters are laundering rings TwinTrace has flagged, hiding among thousands of normal accounts.'],
  ['Replay three months', 'Watch money move across the network. The instant a ring completes its pattern, an alert fires, with a ripple on the board and a new card in the inbox.'],
  ['Open a case file', 'Click any alert. You get a risk score, a plain-English summary built only from the alert’s own evidence, and an interactive money trail you can replay hop by hop.'],
  ['Trace the money', 'Click any account to follow its money upstream and downstream, even across the bank-to-trading link. Keep clicking nodes to keep walking the trail.'],
  ['Is it actually right? Reveal the truth', 'The data is synthetic, so we know the answer. Green rings are real planted rings, red dashed rings are false alarms, and amber marks rings we missed. Nothing is hidden.'],
  ['Plant a fresh ring, live', 'Pick a laundering pattern and a stealth level. A brand-new ring is generated into the data and run through the same detectors, and you see whether TwinTrace and the old rule system catch it.'],
  ['Turn the dials', 'Move the alert bar. Catch more rings and pay with more false alarms, or tighten up and miss some. The board and the benchmark update as you drag.'],
]

export default function App() {
  const [board, setBoard] = useState(null)
  const [boardKey, setBoardKey] = useState(0)
  const [version, setVersion] = useState(0)
  const [ready, setReady] = useState(false)
  const [t, setT] = useState(90)
  const tRef = useRef(90)
  const [playing, setPlaying] = useState(false)
  const playRef = useRef(false)
  const [speed, setSpeed] = useState(6)
  const speedRef = useRef(6)
  const stopAt = useRef(null)
  const [thr, setThr] = useState({ money: 100, trade: 100 })
  const [defaults, setDefaults] = useState({ money: 100, trade: 100 })
  const [filters, setFilters] = useState({ bank: true, trade: true })
  const [showTruth, setShowTruth] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [focusSet, setFocusSet] = useState(null)
  const [tab, setTab] = useState('case')
  const [leftOpen, setLeftOpen] = useState(true)
  const [trace, setTrace] = useState(null)
  const [toasts, setToasts] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [mLoading, setMLoading] = useState(false)
  const [typFilter, setTypFilter] = useState(new Set())
  const [tour, setTour] = useState(-1)
  const [injected, setInjected] = useState(0)
  const boardRef = useRef(null)

  // ------------------------------------------------------------------ load
  const load = useCallback(() => {
    setReady(false)
    api.board().then((b) => {
      b.nodeIndex = new Map(b.nodes.map((n, i) => [n.id, i]))
      setBoard(b)
      setThr({ ...b.thresholds })
      setDefaults({ ...b.thresholds })
    })
  }, [])
  useEffect(load, [])

  // ------------------------------------------------------------------ replay clock
  useEffect(() => {
    if (!board) return
    let last = performance.now(), id, frame = 0, shown = tRef.current
    const loop = (now) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now
      if (playRef.current) {
        let nt = tRef.current + dt * speedRef.current
        const end = stopAt.current ?? board.days
        if (nt >= end) {
          nt = end
          playRef.current = false
          stopAt.current = null
          setPlaying(false)
        }
        tRef.current = nt
      }
      if (++frame % 3 === 0 && tRef.current !== shown) {
        shown = tRef.current
        setT(shown)
      }
      id = requestAnimationFrame(loop)
    }
    id = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(id)
  }, [board])

  const setPlay = (v) => { playRef.current = v; setPlaying(v) }
  const seek = (v) => { tRef.current = v; setT(v) }
  const togglePlay = () => {
    if (!playRef.current && tRef.current >= board.days - 0.05) seek(0)
    setPlay(!playRef.current)
  }
  const changeSpeed = (v) => { speedRef.current = v; setSpeed(v) }

  useEffect(() => {
    const k = (e) => {
      if (e.target.tagName === 'INPUT') return
      if (e.code === 'Space' && board) { e.preventDefault(); togglePlay() }
    }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [board])

  // ------------------------------------------------------------------ live benchmark for the current thresholds
  useEffect(() => {
    if (!board) return
    setMLoading(true)
    const id = setTimeout(() => {
      api.whatif(thr.money, thr.trade).then((m) => { setMetrics(m); setMLoading(false) }).catch(() => setMLoading(false))
    }, 200)
    return () => clearTimeout(id)
  }, [thr, board, version])

  // ------------------------------------------------------------------ actions
  const pushToast = (html, color, icon = '⚑', ms = 3600) => {
    const id = Math.random()
    setToasts((p) => [...p.slice(-2), { id, html, color, icon }])
    setTimeout(() => setToasts((p) => p.filter((x) => x.id !== id)), ms)
  }
  const onFire = useCallback((a) => {
    pushToast(`<b>${typ(a.typ).label}</b> detected · <span style="font-family:var(--mono)">${a.id}</span> · risk ${a.score.toFixed(0)}`, typ(a.typ).color)
  }, [])
  const selectAlert = (a, zoom = true) => {
    if (tRef.current < a.t1) seek(Math.min(board.days, a.t1 + 0.01))
    setSelectedId(a.id)
    setFocusSet(new Set(a.acc))
    setTab('case')
    if (zoom && boardRef.current) boardRef.current.zoomToAlert(a.i)
  }
  const clearSel = () => { setSelectedId(null); setFocusSet(null) }
  const onNodeClick = (n, ai) => {
    setTrace(n.id)
    if (ai >= 0) selectAlert(board.alerts[ai], false)
  }
  const openAlertById = (id) => {
    const a = board.alerts.find((x) => x.id === id)
    if (a) { setTrace(null); selectAlert(a) }
  }
  const pick = (r) => {
    if (r.type === 'alert') openAlertById(r.id)
    else setTrace(r.id)
  }
  const lowerFor = (grp, score) => setThr((p) => ({ ...p, [grp]: Math.max(board.min_score, Math.floor((score - 0.05) * 10) / 10) }))
  const grpOf = (layer) => (layer === 'money' ? 'money' : 'trade')

  const mergeRing = (res) => {
    const b = board
    const ix = b.nodeIndex
    const idxOf = (id) => {
      if (!ix.has(id)) { ix.set(id, b.nodes.length); b.nodes.push({ id, k: id.startsWith('D') ? 'd' : 'b' }) }
      return ix.get(id)
    }
    const ri = b.rings.length
    let ai = -1
    if (res.alert) {
      const a = res.alert
      ai = b.alerts.length
      b.alerts.push({ id: a.alert_id, i: ai, typ: a.typology, name: a.typology_name, layer: a.layer, grp: grpOf(a.layer), score: +a.score.toFixed(2),
        t0: a.t_start / 86400, t1: a.t_end / 86400, n: a.accounts.length, amt: a.evidence.amount_inr || 0, split: a.split, dflt: !!a.above_default,
        hit: a.truth.matched_rings.length > 0, ring: a.truth.matched_rings.slice(0, 1), acc: a.accounts.map(idxOf), entry: a.entry_nodes.map(idxOf),
        exit: a.exit_nodes.map(idxOf), live: true })
    }
    res.ring.nodes.forEach(idxOf)
    res.ring.events.forEach((e) => b.events.push([e[0], idxOf(e[1]), idxOf(e[2]), e[3], e[4], ai, ri]))
    res.ring.owners.forEach(([x, y]) => b.owners.push([idxOf(x), idxOf(y)]))
    b.rings.push({ id: res.ring_id, i: ri, typ: res.typology, layer: 'money', split: 'live', t0: res.ring.t0, acc: res.ring.accounts.map(idxOf), det: res.caught && ai >= 0 ? [ai] : [] })
    setInjected((n) => n + 1)
    setVersion((v) => v + 1)
    return { ai, nodes: res.ring.accounts.map(idxOf) }
  }
  const onPlant = async (req) => {
    const res = await api.plant(req)
    const info = mergeRing(res)
    res._ai = info.ai
    res._nodes = info.nodes
    watch(res)
    return res
  }
  const watch = (res) => {
    const t0 = Math.max(0, res.ring.t0 - 0.6)
    const aEnd = res.alert ? res.alert.t_end / 86400 : 0
    seek(t0)
    changeSpeed(3)
    stopAt.current = Math.min(board.days, Math.max(res.ring.t1, aEnd) + 1.6)
    setPlay(true)
    setTimeout(() => boardRef.current && boardRef.current.zoomToIdxs(res._nodes || res.ring.accounts.map((x) => board.nodeIndex.get(x))), 1300)
    setTimeout(() => pushToast(res.caught ? `<b>TwinTrace caught it</b> · ${res.ring_id}` : `<b>TwinTrace missed it</b> · ${res.ring_id}`, res.caught ? COLORS.green : COLORS.red, res.caught ? '✓' : '✕', 5000), 2200)
  }
  const clearPlanted = async () => {
    await api.reset()
    setInjected(0)
    setBoardKey((k) => k + 1)
    setVersion(0)
    clearSel()
    load()
  }

  // ------------------------------------------------------------------ guided tour
  const act = useRef({})
  act.current = {
    run(i) {
      if (!board) return
      setPlay(false)
      stopAt.current = null
      if (i === 0) { clearSel(); setTrace(null); setShowTruth(false); seek(board.days); boardRef.current.fit() }
      if (i === 1) { seek(0); changeSpeed(10); stopAt.current = 42; setPlay(true) }
      if (i === 2) {
        seek(board.days)
        const pool = board.alerts.filter((a) => a.hit && a.score >= thr[a.grp] && a.layer === 'money' && a.n >= 4 && a.n <= 12)
        const best = [...pool].sort((x, y) => y.score - x.score)[0] || board.alerts[0]
        selectAlert(best)
      }
      if (i === 3) {
        const a = board.alerts.find((x) => x.id === selectedId) || board.alerts[0]
        const node = board.nodes[(a.entry[0] ?? a.acc[0])]
        setTrace(node.id)
      }
      if (i === 4) { setTrace(null); clearSel(); setShowTruth(true); boardRef.current.fit() }
      if (i === 5) { setShowTruth(false); setTab('plant') }
      if (i === 6) setTab('lab')
    },
  }
  useEffect(() => { if (tour >= 0) act.current.run(tour) }, [tour])

  // ------------------------------------------------------------------ derived
  const firedCount = useMemo(() => (board ? board.alerts.filter((a) => a.score >= thr[a.grp] && a.t1 <= t).length : 0), [board, thr, t, version])
  if (!board) return <div className="loader"><div><div className="spin" /><p>Loading the network…</p></div></div>

  const sel = selectedId && board.alerts.find((a) => a.id === selectedId)
  return (
    <div className={'app' + (leftOpen ? '' : ' no-left')}>
      <TopBar metrics={metrics} base={board.methods.rule_baseline} alertsFired={firedCount} filters={filters} setFilters={setFilters}
        showTruth={showTruth} setShowTruth={setShowTruth} onPick={pick} onTour={() => setTour(0)} tab={tab} setTab={setTab} injected={injected} />
      <div className="left">
        <AlertList board={board} thr={thr} t={t} selectedId={selectedId} onSelect={(a) => selectAlert(a)} typFilter={typFilter} setTypFilter={setTypFilter} playing={playing} />
      </div>
      <div className="board-wrap">
        <WhatYouSee kind="board" />
        <div className="board-stage">
        {!ready && <div className="loader"><div><div className="spin" /><p>Laying out {board.nodes.length.toLocaleString()} accounts…</p></div></div>}
        <Board key={boardKey} ref={boardRef} board={board} version={version} tRef={tRef} t={t} thr={thr} filters={filters} showTruth={showTruth} focusSet={focusSet}
          playing={playing} onNodeClick={onNodeClick} onBackground={clearSel} onFire={onFire} onReady={() => setReady(true)} />
        <Toasts items={toasts} />
        <div className="hud-tr">
          <div className="seg" title="Which layer to show">
            <button className={filters.bank ? 'on' : ''} onClick={() => setFilters({ ...filters, bank: !filters.bank })}>● Bank</button>
            <button className={filters.trade ? 'on' : ''} onClick={() => setFilters({ ...filters, trade: !filters.trade })}>◆ Trades</button>
          </div>
          <button className="btn sm" onClick={() => setLeftOpen(!leftOpen)}>{leftOpen ? '◀ hide inbox' : '▶ inbox'}</button>
          <button className="btn sm" onClick={() => { clearSel(); boardRef.current.fit() }}>⤢ fit</button>
        </div>
        <div className="legend">
          <div><i style={{ background: '#6c93e0' }} /> bank account <span style={{ marginLeft: 8 }}>◆</span> trading account</div>
          <div><i style={{ background: '#ff3b5c', boxShadow: '0 0 8px #ff3b5c' }} /> flagged ring (colour = typology)</div>
          {showTruth && <div><i style={{ background: 'transparent', border: '1.5px solid #2ee59d' }} /> real ring <i style={{ background: 'transparent', border: '1.5px dashed #ff3b5c', marginLeft: 8 }} /> false alarm <i style={{ background: 'transparent', border: '1.5px dashed #ffb020', marginLeft: 8 }} /> missed</div>}
          <div>click any account to trace its money</div>
        </div>
        {trace && <TraceView account={trace} onClose={() => setTrace(null)} onOpenAlert={openAlertById} />}
        {tour >= 0 && (
          <div className="tour">
            <h4>{tour + 1}/{TOUR.length} · {TOUR[tour][0]}</h4>
            <p>{TOUR[tour][1]}</p>
            <div className="nav">
              <div className="dots">{TOUR.map((_, i) => <i key={i} className={i === tour ? 'on' : ''} />)}</div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn sm" onClick={() => setTour(-1)}>Exit</button>
                {tour > 0 && <button className="btn sm" onClick={() => setTour(tour - 1)}>← Back</button>}
                <button className="btn sm primary" onClick={() => (tour + 1 < TOUR.length ? setTour(tour + 1) : setTour(-1))}>{tour + 1 < TOUR.length ? 'Next →' : 'Finish'}</button>
              </div>
            </div>
          </div>
        )}
        </div>
      </div>
      <div className="right">
        <div className="tabs">
          <button className={tab === 'case' ? 'on' : ''} onClick={() => setTab('case')}>⚑ Case file</button>
          <button className={tab === 'lab' ? 'on' : ''} onClick={() => setTab('lab')}>⚙ What-if lab</button>
          <button className={tab === 'plant' ? 'on' : ''} onClick={() => setTab('plant')}>＋ Plant ring</button>
        </div>
        <div className="drawer-body" key={tab}>
          {tab === 'case' && (
            <CaseFile alertId={selectedId} thr={thr} onTrace={(a) => setTrace(a)} onZoom={() => sel && boardRef.current.zoomToAlert(sel.i)}
              onReplay={(a) => { seek(Math.max(0, a.t_start / 86400 - 1)); changeSpeed(4); stopAt.current = Math.min(board.days, a.t_end / 86400 + 1.5); setPlay(true); sel && boardRef.current.zoomToAlert(sel.i) }}
              onLower={(a) => lowerFor(grpOf(a.layer), a.score)} />
          )}
          {tab === 'lab' && <WhatIf thr={thr} setThr={setThr} defaults={defaults} m={metrics} methods={board.methods} loading={mLoading} floor={board.min_score}
            shown={board.alerts.filter((a) => a.score >= thr[a.grp]).length} total={board.alerts.length} accounts={board.n_accounts} />}
          {tab === 'plant' && (
            <PlantPanel day={t} onPlant={onPlant} onWatch={watch} onOpenAlert={openAlertById} injected={injected} onClear={clearPlanted}
              onLower={(res) => { lowerFor(res.closest.layer === 'money' ? 'money' : 'trade', res.closest.score); setTab('lab') }} />
          )}
        </div>
      </div>
      <div className="timebar">
        <Timeline board={board} t={t} playing={playing} speed={speed} onToggle={togglePlay} onSpeed={changeSpeed} onSeek={seek} thr={thr} firedCount={firedCount} />
      </div>
    </div>
  )
}
