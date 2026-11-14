import React from 'react'
import { pct } from '../util'

export default function TopBar({ metrics, base, alertsFired, showTruth, setShowTruth, onTour, onLogo, onPresent }) {
  return (
    <div className="top">
      <div className="logo" onClick={onLogo} role="button" tabIndex={0} title="Click to re-scan the network" onKeyDown={(e) => e.key === 'Enter' && onLogo && onLogo()}>
        <div className="logo-mark"><span>TT</span></div>
        <div>TwinTrace<small>cross-layer crime radar</small></div>
      </div>
      <div className="kpis">
        <div className="kpi"><b>{alertsFired}</b><span>alerts fired</span></div>
        <div className="kpi"><b>{metrics ? `${metrics.found}/${metrics.rings}` : '–'}</b><span>test rings caught</span></div>
        <div className="kpi"><b>{metrics ? pct(metrics.fpr, 2) : '–'}</b><span>false alarms · rules {base ? pct(base.fpr, 1) : '–'}</span></div>
      </div>
      <div className="spacer" />
      <button className={'btn ghost' + (showTruth ? ' on' : '')} onClick={() => setShowTruth(!showTruth)} title="Overlay the synthetic ground truth: real rings, false alarms, misses">◎ Reveal truth</button>
      <button className="btn ghost" onClick={onPresent} title="Hide panels for a projector (P)">⛶ Present</button>
      <button className="btn primary" onClick={onTour}>▶ Guided demo</button>
    </div>
  )
}
