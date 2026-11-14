import React, { useMemo, useRef } from 'react'
import { fmtDay, typ } from '../util'

/** Bottom bar: play/pause, speed, a scrubbable 90-day track with event density, alert ticks and the train/val/test split. */
export default function Timeline({ board, t, playing, speed, onToggle, onSpeed, onSeek, thr, firedCount }) {
  const ref = useRef(null)
  const W = 1000, H = 62
  const days = board.days
  const bins = useMemo(() => {
    const b = new Array(days * 2).fill(0)
    for (const e of board.events) b[Math.min(b.length - 1, Math.floor(e[0] * 2))]++
    const mx = Math.max(...b, 1)
    return b.map((v) => Math.sqrt(v / mx))
  }, [board.events.length, days])
  const ticks = board.alerts.filter((a) => a.score >= thr[a.grp])
  const x = (d) => (d / days) * W
  const seek = (ev) => {
    const r = ref.current.getBoundingClientRect()
    onSeek(Math.max(0, Math.min(days, ((ev.clientX - r.left) / r.width) * days)))
  }
  const down = (ev) => {
    ev.preventDefault()
    seek(ev)
    const move = (e) => seek(e)
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const sp = board.splits
  const zones = [['TUNE · model learns', sp.tune, '#1b3a63'], ['VAL', sp.val, '#3a2d63'], ['TEST · never seen', sp.test, '#13524b']]
  return (
    <div className="tl">
      <div className="tl-ctrl">
        <button className="play" onClick={onToggle} title="Space">{playing ? '❚❚' : '▶'}</button>
        <div className="daylabel">
          <b>Day {Math.floor(t)}</b>
          <span>{fmtDay(t)} 2025 · {firedCount} alerts fired</span>
        </div>
      </div>
      <div className="track" ref={ref} onPointerDown={down}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          {zones.map(([l, [a, b], c]) => (
            <g key={l}>
              <rect x={x(a)} y={0} width={x(b) - x(a)} height={H} fill={c} opacity={0.35} />
              <text x={x(a) + 6} y={11} fill="#8ea2c9" fontSize="9" fontFamily="monospace" opacity={0.9}>{l}</text>
            </g>
          ))}
          {bins.map((v, i) => (
            <rect key={i} x={(i / bins.length) * W} y={H - 4 - v * 30} width={W / bins.length - 1} height={v * 30} fill="#3d5a94" opacity={0.75} />
          ))}
          {ticks.map((a) => (
            <rect key={a.id} x={x(a.t1) - 0.8} y={16} width={1.6} height={8 + (a.score / 100) * 10} fill={typ(a.typ).color} opacity={a.t1 <= t ? 1 : 0.35} />
          ))}
          <line x1={x(t)} x2={x(t)} y1={0} y2={H} stroke="#4fb3a9" strokeWidth="2" />
          <circle cx={x(t)} cy={H - 6} r="6" fill="#4fb3a9" stroke="#101214" strokeWidth="2" />
        </svg>
      </div>
      <div className="speed">
        <div className="seg">
          {[[2, '1×'], [6, '3×'], [16, '8×']].map(([v, l]) => (
            <button key={v} className={speed === v ? 'on' : ''} onClick={() => onSpeed(v)}>{l}</button>
          ))}
        </div>
        <span className="sub">drag to scrub · space to play</span>
      </div>
    </div>
  )
}
