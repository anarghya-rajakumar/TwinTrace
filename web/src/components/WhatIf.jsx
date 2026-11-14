import React, { useEffect, useRef, useState } from 'react'
import { pct } from '../util'

function AnimNum({ value, fmt }) {
  const [v, setV] = useState(value)
  const from = useRef(value)
  useEffect(() => {
    const a = from.current, b = value, t0 = performance.now()
    let id
    const step = (t) => {
      const k = Math.min(1, (t - t0) / 380)
      const e = 1 - Math.pow(1 - k, 3)
      setV(a + (b - a) * e)
      if (k < 1) id = requestAnimationFrame(step)
      else from.current = b
    }
    id = requestAnimationFrame(step)
    return () => cancelAnimationFrame(id)
  }, [value])
  return <>{fmt(v)}</>
}

const Bar = ({ label, v, color }) => (
  <div className="row">
    <span>{label}</span>
    <div className="tr"><div style={{ width: `${Math.min(100, v * 100)}%`, background: color }} /></div>
    <b style={{ fontFamily: 'var(--mono)', textAlign: 'right' }}>{v.toFixed(2)}</b>
  </div>
)

/** Move the alert bar and watch precision, recall and false alarms respond. The board re-filters at the same time. */
export default function WhatIf({ thr, setThr, defaults, m, methods, loading, floor = 50 }) {
  const off = (v) => (v > 100 ? 'off' : v.toFixed(1))
  const preset = (money, trade) => setThr({ money, trade })
  const rb = methods.rule_baseline, sl = methods.single_layer
  return (
    <div>
      <div className="sect" style={{ marginTop: 0 }}>
        <h4>Alert thresholds (risk score needed to raise an alert)</h4>
        <div className="slider-row">
          <div className="top"><span>● Bank-layer bar</span><b style={{ fontFamily: 'var(--mono)', color: '#22d3ee' }}>{off(thr.money)}</b></div>
          <input type="range" min={floor} max="101" step="0.5" value={thr.money} onChange={(e) => setThr({ ...thr, money: +e.target.value })} />
          <div className="sub">trained default {defaults.money.toFixed(1)}</div>
        </div>
        <div className="slider-row">
          <div className="top"><span>◆ Trade-layer bar</span><b style={{ fontFamily: 'var(--mono)', color: '#a78bfa' }}>{off(thr.trade)}</b></div>
          <input type="range" min={floor} max="101" step="0.1" value={thr.trade} onChange={(e) => setThr({ ...thr, trade: +e.target.value })} />
          <div className="sub">trained default {defaults.trade.toFixed(1)} · 101 turns the layer off</div>
        </div>
        <div className="presets">
          <button className="btn sm" onClick={() => preset(defaults.money, defaults.trade)}>⟲ Trained default</button>
          <button className="btn sm" onClick={() => preset(defaults.money, 101)}>Bank layer only</button>
          <button className="btn sm" onClick={() => preset(floor, floor)}>Paranoid (low bar)</button>
          <button className="btn sm" onClick={() => preset(99.9, 99.99)}>Strict</button>
        </div>
      </div>
      {m && (
        <>
          <div className="metrics" style={{ opacity: loading ? 0.6 : 1 }}>
            <div className="metric"><span>Precision</span><b style={{ color: '#2ee59d' }}><AnimNum value={m.precision} fmt={(v) => v.toFixed(2)} /></b><small>alerts that were real</small></div>
            <div className="metric"><span>Recall</span><b style={{ color: '#22d3ee' }}><AnimNum value={m.recall} fmt={(v) => v.toFixed(2)} /></b><small>{m.found}/{m.rings} rings caught</small></div>
            <div className="metric"><span>F1</span><b><AnimNum value={m.f1} fmt={(v) => v.toFixed(2)} /></b><small>balance of both</small></div>
            <div className="metric"><span>False alarms</span><b style={{ color: m.fpr > 0.01 ? '#ff3b5c' : '#ffb020' }}><AnimNum value={m.fpr * 100} fmt={(v) => v.toFixed(2) + '%'} /></b><small>innocent accts flagged</small></div>
            <div className="metric"><span>Alerts</span><b><AnimNum value={m.alerts} fmt={(v) => Math.round(v)} /></b><small>in test period</small></div>
            <div className="metric"><span>Per 1,000</span><b><AnimNum value={m.per1000} fmt={(v) => v.toFixed(1)} /></b><small>rules: {rb ? rb.per1000.toFixed(0) : '–'}</small></div>
          </div>
          <div className="sect">
            <h4>vs the baselines (same held-out period)</h4>
            <div className="cmp">
              {[['Precision', 'precision'], ['Recall', 'recall'], ['F1', 'f1']].map(([l, k]) => (
                <div key={k} style={{ marginBottom: 10 }}>
                  <div className="sub" style={{ marginBottom: 2 }}>{l}</div>
                  <Bar label="TwinTrace" v={m[k]} color="linear-gradient(90deg,#22d3ee,#8b6fe0)" />
                  {sl && <Bar label="Bank only" v={sl[k]} color="#4f6ba3" />}
                  {rb && <Bar label="Rules" v={rb[k]} color="#ff3b5c" />}
                </div>
              ))}
            </div>
            <div className="truth" style={{ marginTop: 6 }}>
              {rb && m.fpr > 0 && <><b>{(rb.fpr / m.fpr).toFixed(0)}× fewer false alarms</b> than the rule baseline at this setting. </>}
              {rb && m.fpr === 0 && <><b>No innocent accounts flagged</b> at this setting. </>}
              Slide the bar down to catch more rings and watch precision and false alarms pay for it.
            </div>
          </div>
        </>
      )}
    </div>
  )
}
