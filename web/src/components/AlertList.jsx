import React, { useMemo, useState } from 'react'
import { fmtDay, inr, typ } from '../util'

export default function AlertList({ board, thr, t, selectedId, onSelect, typFilter, setTypFilter, playing }) {
  const [sort, setSort] = useState('time')
  const [limit, setLimit] = useState(120)
  const shown = useMemo(() => board.alerts.filter((a) => a.score >= thr[a.grp]), [board.alerts.length, thr])
  const fired = shown.filter((a) => a.t1 <= t && (!typFilter.size || typFilter.has(a.typ)))
  const list = [...fired].sort((a, b) => (sort === 'time' ? b.t1 - a.t1 : b.score - a.score))
  const counts = {}
  shown.forEach((a) => {
    counts[a.typ] = (counts[a.typ] || 0) + 1
  })
  const toggle = (k) => {
    const n = new Set(typFilter)
    n.has(k) ? n.delete(k) : n.add(k)
    setTypFilter(n)
  }
  return (
    <>
      <div className="panel-h">
        <h3>
          <span>Alert inbox · {fired.length}</span>
          <span className="seg">
            <button className={sort === 'time' ? 'on' : ''} onClick={() => setSort('time')}>Latest</button>
            <button className={sort === 'score' ? 'on' : ''} onClick={() => setSort('score')}>Risk</button>
          </span>
        </h3>
        <div className="chips">
          {Object.keys(counts).sort((a, b) => counts[b] - counts[a]).map((k) => (
            <button key={k} className={'chip' + (typFilter.has(k) ? ' on' : '')} onClick={() => toggle(k)} title={typ(k).long}>
              <i style={{ background: typ(k).color }} />{typ(k).label} {counts[k]}
            </button>
          ))}
        </div>
      </div>
      <div className="list">
        {list.length === 0 && (
          <div className="empty"><big>◌</big>No alerts yet.<br />Press play and watch them fire.</div>
        )}
        {list.slice(0, limit).map((a) => {
          const c = typ(a.typ).color
          const fresh = playing && t - a.t1 < 0.7
          return (
            <button key={a.id} className={'item' + (selectedId === a.id ? ' sel' : '') + (fresh ? ' fresh' : '')} style={{ '--c': c }} onClick={() => onSelect(a)}>
              <div className="row">
                <span className="t">{typ(a.typ).glyph} {typ(a.typ).label}</span>
                <span className="score" style={{ color: c }}>{a.score.toFixed(0)}</span>
              </div>
              <div className="row" style={{ marginTop: 3 }}>
                <span className="id">{a.id} · {fmtDay(a.t1)}</span>
                <span>{a.live && <span className="tag live">LIVE</span>}</span>
              </div>
              <div className="meta">
                <span>{a.n} accounts</span>
                <span>{inr(a.amt)}</span>
                <span>{a.layer === 'bridge' ? 'bank ↔ trades' : a.layer === 'trade' ? 'trades' : 'bank'}</span>
              </div>
              <div className="bar"><div style={{ width: `${a.score}%` }} /></div>
            </button>
          )
        })}
        {list.length > limit && (
          <button className="btn sm" style={{ margin: '4px auto 12px', display: 'flex' }} onClick={() => setLimit(limit + 120)}>
            Show more ({list.length - limit})
          </button>
        )}
      </div>
    </>
  )
}
