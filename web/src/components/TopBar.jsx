import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { pct } from '../util'

export default function TopBar({ metrics, base, alertsFired, filters, setFilters, showTruth, setShowTruth, onPick, onTour, tab, setTab, injected }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState([])
  const tm = useRef(null)
  useEffect(() => {
    clearTimeout(tm.current)
    if (q.length < 2) {
      setRes([])
      return
    }
    tm.current = setTimeout(() => api.search(q).then(setRes).catch(() => {}), 180)
  }, [q])
  return (
    <div className="top">
      <div className="logo">
        <div className="logo-mark"><span>TT</span></div>
        <div>TwinTrace<small>cross-layer crime radar</small></div>
      </div>
      <div className="kpis">
        <div className="kpi cy"><b>{alertsFired}</b><span>alerts fired</span></div>
        <div className="kpi good"><b>{metrics ? `${metrics.found}/${metrics.rings}` : '–'}</b><span>test rings caught</span></div>
        <div className="kpi good"><b>{metrics ? pct(metrics.fpr, 2) : '–'}</b><span>false-alarm rate</span></div>
        <div className="kpi bad"><b>{base ? pct(base.fpr, 1) : '–'}</b><span>rule baseline</span></div>
      </div>
      <div className="spacer" />
      <div className="search">
        <input placeholder="search alert or account…" value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => setTimeout(() => setRes([]), 150)} />
        {res.length > 0 && (
          <div className="search-pop">
            {res.map((r) => (
              <button key={r.type + r.id} onMouseDown={() => { onPick(r); setQ('') }}>{r.type === 'alert' ? '⚑' : '◉'} {r.label}</button>
            ))}
          </div>
        )}
      </div>
      <button className={'btn' + (showTruth ? ' on' : '')} onClick={() => setShowTruth(!showTruth)} title="Overlay the synthetic ground truth: real rings, false alarms, misses">◎ Reveal truth</button>
      <button className={'btn' + (tab === 'plant' ? ' on' : '')} onClick={() => setTab('plant')}>＋ Plant a ring{injected ? ` (${injected})` : ''}</button>
      <button className={'btn' + (tab === 'lab' ? ' on' : '')} onClick={() => setTab('lab')}>⚙ What-if lab</button>
      <button className="btn primary" onClick={onTour}>▶ Guided demo</button>
    </div>
  )
}
