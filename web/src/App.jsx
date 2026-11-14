import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { COLORS, typ } from './util'
import Board from './components/Board.jsx'
import BoardGlobe from './components/BoardGlobe.jsx'
import TopBar from './components/TopBar.jsx'
import Timeline from './components/Timeline.jsx'
import AlertList from './components/AlertList.jsx'
import CaseFile from './components/CaseFile.jsx'
import TraceView from './components/TraceView.jsx'
import WhatIf from './components/WhatIf.jsx'
import PlantPanel from './components/PlantPanel.jsx'
import Toasts from './components/Toasts.jsx'
import WhatYouSee from './components/WhatYouSee.jsx'
import ChatHelp from './components/ChatHelp.jsx'

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
  const [tab, setTab] = useState(() => { try { const t = localStorage.getItem('tt-tab'); return ['case', 'lab', 'plant'].includes(t) ? t : 'case' } catch (e) { return 'case' } })
  const [present, setPresent] = useState(false)
  const [panel, setPanel] = useState(null)   // null | 'alerts' | 'case' | 'lab' | 'plant': one floating panel, closed on load
  const leftOpen = panel === 'alerts'
  const drawerOpen = panel !== null && panel !== 'alerts'
  const setLeftOpen = (v) => setPanel((p) => { const on = typeof v === 'function' ? v(p === 'alerts') : v; return on ? 'alerts' : (p === 'alerts' ? null : p) })
  const setDrawerOpen = (v) => setPanel((p) => { const cur = p !== null && p !== 'alerts'; const on = typeof v === 'function' ? v(cur) : v; return on ? (cur ? p : tab) : (cur ? null : p) })
  const openTab = (t) => { setTab(t); setPanel(t) }
  useEffect(() => { try { localStorage.setItem('tt-tab', tab) } catch (e) { /* ignore */ } }, [tab])
  const [rebooting, setRebooting] = useState(false)
  const [trace, setTrace] = useState(null)
  const [toasts, setToasts] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [mLoading, setMLoading] = useState(false)
  const [typFilter, setTypFilter] = useState(new Set())
  const [tour, setTour] = useState(-1)
  const [injected, setInjected] = useState(0)
  const [intro, setIntro] = useState(null)   // null | 'hero' (auto-playing opening) | 'cta' (offer the tour)
  const introRef = useRef(false)
  const introDone = useRef(false)
  const [view3d, setView3d] = useState(() => { try { return localStorage.getItem('tt-view') !== '2d' } catch (e) { return true } })
  const [orbit, setOrbit] = useState(true)
  const switchView = (v) => {
    try { localStorage.setItem('tt-view', v ? '3d' : '2d') } catch (e) { /* ignore */ }
    setReady(false)
    setView3d(v)
    setBoardKey((k) => k + 1)
  }
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
    if (!playRef.current) { setIntro(null); setPanel((p) => p ?? 'alerts') }   // pressing play opens the alert inbox
    setPlay(!playRef.current)
  }
  const changeSpeed = (v) => { speedRef.current = v; setSpeed(v) }

  // opening: once the globe is ready, replay the 90 days by itself under a headline, then offer the tour
  introRef.current = intro === 'hero'
  useEffect(() => {
    if (!ready || !board || introDone.current) return
    introDone.current = true
    setIntro('hero'); seek(0); changeSpeed(14); stopAt.current = null; setPlay(true)
  }, [ready, board])
  useEffect(() => { if (intro === 'hero' && !playing) setIntro('cta') }, [playing, intro])
  useEffect(() => {
    if (intro !== 'cta') return
    const id = setTimeout(() => setIntro(null), 12000)
    return () => clearTimeout(id)
  }, [intro])

  const keyAct = useRef(null)
  keyAct.current = (e) => {
    if (!board || e.ctrlKey || e.metaKey || e.altKey) return
    const tag = e.target.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA') return
    if (e.code === 'Space') { e.preventDefault(); togglePlay(); return }
    const k = e.key.toLowerCase()
    if (k === 'escape') {
      if (trace) setTrace(null)
      else if (tour >= 0) setTour(-1)
      else if (present) setPresent(false)
      else if (selectedId) clearSel()
    } else if (k === 'i') setLeftOpen((v) => !v)
    else if (k === 'd') setDrawerOpen((v) => !v)
    else if (k === '1') openTab('case')
    else if (k === '2') openTab('lab')
    else if (k === '3') openTab('plant')
    else if (k === 'p') setPresent((v) => !v)
    else if (k === '?' || (k === '/' && e.shiftKey)) {
      pushToast('<b>Shortcuts</b> · Space play · I inbox · D side panel · 1 case file · 2 what-if · 3 plant · P present mode · Esc close', COLORS.cyan, '⌨', 7000)
    }
  }
  useEffect(() => {
    const k = (e) => keyAct.current && keyAct.current(e)
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [])

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
    if (introRef.current) return   // the opening shows ripples only; no toasts
    pushToast(`<b>${typ(a.typ).label}</b> detected · <span style="font-family:var(--mono)">${a.id}</span> · risk ${a.score.toFixed(0)}`, typ(a.typ).color)
  }, [])
  const selectAlert = (a, zoom = true) => {
    if (tRef.current < a.t1) seek(Math.min(board.days, a.t1 + 0.01))
    setSelectedId(a.id)
    setFocusSet(new Set(a.acc))
    openTab('case')
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
      if (i === 5) { setShowTruth(false); openTab('plant') }
      if (i === 6) openTab('lab')
    },
  }
  useEffect(() => { if (tour >= 0) act.current.run(tour) }, [tour])

  // ------------------------------------------------------------------ derived
  const firedCount = useMemo(() => (board ? board.alerts.filter((a) => a.score >= thr[a.grp] && a.t1 <= t).length : 0), [board, thr, t, version])
  if (!board) return <div className="loader"><div><div className="spin" /><p>Loading the network…</p></div></div>

  const sel = selectedId && board.alerts.find((a) => a.id === selectedId)
  return (
    <div className={'app2' + (panel ? ' panel-open' : '') + (present ? ' present' : '') + (intro === 'hero' ? ' intro' : '')}>
      <TopBar metrics={metrics} base={board.methods.rule_baseline} alertsFired={firedCount} showTruth={showTruth} setShowTruth={setShowTruth}
        onTour={() => { setPresent(false); setIntro(null); setPanel('alerts'); setTour(0) }} onPresent={() => setPresent(true)}
        onLogo={() => { setRebooting(true); setTimeout(() => window.location.reload(), 1050) }} />
      <nav className="rail" aria-label="Panels">
        {[['alerts', '⚑', 'Alert inbox (I)', firedCount], ['case', '▣', 'Case file (1)', 0], ['lab', '⚙', 'What-if lab (2)', 0], ['plant', '＋', 'Plant a ring (3)', injected]].map(([k, ic, label, badge]) => (
          <button key={k} className={'rail-btn' + (panel === k ? ' on' : '')} title={label} aria-label={label} aria-pressed={panel === k}
            onClick={() => (panel === k ? setPanel(null) : k === 'alerts' ? setPanel('alerts') : openTab(k))}>
            <span>{ic}</span>{badge > 0 && <i className="rail-badge">{badge}</i>}
          </button>
        ))}
      </nav>
      <div className="board-wrap">
        <WhatYouSee kind="board" globe={view3d} />
        <div className="board-stage">
          {!ready && <div className="loader"><div><div className="spin" /><p>Laying out {board.nodes.length.toLocaleString()} accounts…</p></div></div>}
          {React.createElement(view3d ? BoardGlobe : Board, { key: boardKey + (view3d ? 'g' : 'd2'), ref: boardRef, orbit, onAlertClick: (ai) => selectAlert(board.alerts[ai]), board, version, tRef, t, thr, filters, showTruth, focusSet, playing, onNodeClick, onBackground: clearSel, onFire, onReady: () => setReady(true) })}
          <Toasts items={toasts} />
          {present && <button className="btn sm present-exit" onClick={() => setPresent(false)}>✕ Exit present mode (Esc)</button>}
          <div className="hud-tr">
            <div className="seg" title="Flat network of accounts, or a globe with one point per flagged ring">
              <button className={!view3d ? 'on' : ''} onClick={() => view3d && switchView(false)}>2D</button>
              <button className={view3d ? 'on' : ''} onClick={() => !view3d && switchView(true)}>Globe</button>
            </div>
            {view3d && <button className={'btn sm' + (orbit ? ' on' : '')} onClick={() => setOrbit(!orbit)} title="Slowly rotate the view">⟳ orbit</button>}
            <div className="seg" title="Which layer to show">
              <button className={filters.bank ? 'on' : ''} onClick={() => setFilters({ ...filters, bank: !filters.bank })}>● Bank</button>
              <button className={filters.trade ? 'on' : ''} onClick={() => setFilters({ ...filters, trade: !filters.trade })}>◆ Trades</button>
            </div>
            <button className="btn sm" onClick={() => { clearSel(); boardRef.current.fit() }}>⤢ fit</button>
          </div>
          <div className="legend">
            {view3d ? (
              <>
                <div><i style={{ background: '#d1304b' }} /> one point = one flagged ring (colour = crime type)</div>
                <div>drag to spin · click a point to open it</div>
              </>
            ) : (
              <>
                <div><i style={{ background: '#4f6d7a' }} /> bank account <span style={{ marginLeft: 8 }}>◆</span> trading account</div>
                <div><i style={{ background: '#d1304b' }} /> flagged ring (colour = typology)</div>
              </>
            )}
            {showTruth && <div><i style={{ background: 'transparent', border: '1.5px solid #25bb80' }} /> real ring <i style={{ background: 'transparent', border: '1.5px dashed #d1304b', marginLeft: 8 }} /> false alarm <i style={{ background: 'transparent', border: '1.5px dashed #d1901a', marginLeft: 8 }} /> missed</div>}
            <div>click any account to trace its money</div>
          </div>

          {intro === 'hero' && (
            <div className="hero">
              <div className="hero-eyebrow">TwinTrace · cross-layer crime radar</div>
              <h1>Following dirty money across <em>bank transfers</em> and <em>stock trades</em>.</h1>
              <div className="hero-stats">
                <div><b>{Math.floor(t)}</b><span>of 90 days replayed</span></div>
                <div><b>{firedCount}</b><span>rings caught so far</span></div>
                <div><b>{board.n_accounts.toLocaleString()}</b><span>accounts watched</span></div>
              </div>
              <button className="btn ghost sm" onClick={() => { setPlay(false); seek(board.days) }}>Skip intro</button>
            </div>
          )}
          {intro === 'cta' && (
            <div className="cta">
              <button className="btn primary" onClick={() => { setIntro(null); setPanel('alerts'); setTour(0) }}>▶ Take the 60-second tour</button>
              <button className="btn ghost" onClick={() => setIntro(null)}>Explore on my own</button>
            </div>
          )}

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

          <aside className={'panel-float' + (panel ? ' open' : '')} aria-hidden={!panel}>
            <div className="pf-h">
              <div className="pf-tabs">
                {[['alerts', 'Alerts'], ['case', 'Case file'], ['lab', 'What-if'], ['plant', 'Plant']].map(([k, l]) => (
                  <button key={k} className={panel === k ? 'on' : ''} onClick={() => (k === 'alerts' ? setPanel('alerts') : openTab(k))}>{l}</button>
                ))}
              </div>
              <button className="pf-x" onClick={() => setPanel(null)} title="Close (D)" aria-label="Close panel">✕</button>
            </div>
            {panel === 'alerts' && (
              <div className="pf-body">
                <AlertList board={board} thr={thr} t={t} selectedId={selectedId} onSelect={(a) => selectAlert(a)} typFilter={typFilter} setTypFilter={setTypFilter} playing={playing} />
              </div>
            )}
            {panel && panel !== 'alerts' && (
              <div className="drawer-body" key={panel + (panel === 'case' ? selectedId : '')}>
                {panel === 'case' && (
                  <CaseFile alertId={selectedId} thr={thr} onTrace={(a) => setTrace(a)} onZoom={() => sel && boardRef.current.zoomToAlert(sel.i)}
                    onReplay={(a) => { seek(Math.max(0, a.t_start / 86400 - 1)); changeSpeed(4); stopAt.current = Math.min(board.days, a.t_end / 86400 + 1.5); setPlay(true); sel && boardRef.current.zoomToAlert(sel.i) }}
                    onLower={(a) => lowerFor(grpOf(a.layer), a.score)} />
                )}
                {panel === 'lab' && <WhatIf thr={thr} setThr={setThr} defaults={defaults} m={metrics} methods={board.methods} loading={mLoading} floor={board.min_score}
                  shown={board.alerts.filter((a) => a.score >= thr[a.grp]).length} total={board.alerts.length} accounts={board.n_accounts} />}
                {panel === 'plant' && (
                  <PlantPanel day={t} onPlant={onPlant} onWatch={watch} onOpenAlert={openAlertById} injected={injected} onClear={clearPlanted}
                    onLower={(res) => { lowerFor(res.closest.layer === 'money' ? 'money' : 'trade', res.closest.score); openTab('lab') }} />
                )}
              </div>
            )}
          </aside>
        </div>
      </div>
      <div className="timebar">
        <Timeline board={board} t={t} playing={playing} speed={speed} onToggle={togglePlay} onSpeed={changeSpeed} onSeek={seek} thr={thr} firedCount={firedCount} />
      </div>
      <ChatHelp board={board} selectedId={selectedId} shown={board.alerts.filter((a) => a.score >= thr[a.grp]).length} total={board.alerts.length} accounts={board.n_accounts} />
      {rebooting && (
        <div className="reboot">
          <div>
            <div className="logo-mark"><span>TT</span></div>
            <h2>TWINTRACE</h2>
            <p>re-scanning the network…</p>
            <div className="bar"><i /></div>
          </div>
        </div>
      )}
    </div>
  )
}
