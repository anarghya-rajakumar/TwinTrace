import React from 'react'
import { pct } from '../util'

export default function TopBar({ metrics, base, alertsFired, filters, setFilters, showTruth, setShowTruth, onPick, onTour, tab, setTab, injected, onLogo, onPresent }) {
  return (
    <div className="top">
      <div className="logo" onClick={onLogo} role="button" tabIndex={0} title="Click to re-scan the network" onKeyDown={(e) => e.key === 'Enter' && onLogo && onLogo()}>
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
      <button className={'btn' + (showTruth ? ' on' : '')} onClick={() => setShowTruth(!showTruth)} title="Overlay the synthetic ground truth: real rings, false alarms, misses">◎ Reveal truth</button>
      <button className={'btn' + (tab === 'plant' ? ' on' : '')} onClick={() => setTab('plant')}>＋ Plant a ring{injected ? ` (${injected})` : ''}</button>
      <button className={'btn' + (tab === 'lab' ? ' on' : '')} onClick={() => setTab('lab')}>⚙ What-if lab</button>
      <button className="btn" onClick={onPresent} title="Hide panels for a projector (P)">⛶ Present</button>
      <button className="btn primary" onClick={onTour}>▶ Guided demo</button>
    </div>
  )
}
