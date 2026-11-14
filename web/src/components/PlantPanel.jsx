import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { TYP, typ, inr } from '../util'

const OPTIONS = [
  ['fan_out', 'One account sprays money to many'],
  ['fan_in_structuring', 'Many senders, each just under ₹50,000'],
  ['round_trip', 'Money loops back to where it started'],
  ['mule_chain', 'Hop after hop, almost undiminished'],
  ['wash_trading', 'Accounts trade a stock among themselves'],
  ['loss_booking', 'Off-market reversals move losses'],
  ['market_layering', 'Bank → trading accounts → cash-out'],
]
const STEPS = ['Generating transfers and trades…', 'Joining owners and funding links…', 'Building windows and clusters…', 'Scoring with the trained model…', 'Racing the rule baseline…']

export default function PlantPanel({ day, onPlant, onWatch, onOpenAlert, onLower, onClear, injected }) {
  const [kind, setKind] = useState('mule_chain')
  const [stealth, setStealth] = useState(0.6)
  const [size, setSize] = useState(0)
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState(0)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)
  const vref = useRef(null)
  useEffect(() => {
    if (res && vref.current) vref.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [res])
  useEffect(() => {
    if (!busy) return
    const id = setInterval(() => setStep((s) => (s + 1) % STEPS.length), 1100)
    return () => clearInterval(id)
  }, [busy])
  const go = async () => {
    setBusy(true); setErr(null); setRes(null); setStep(0)
    try {
      const r = await onPlant({ typology: kind, stealth, size: size || null, start_day: Math.max(12, Math.min(84, day)) })
      setRes(r)
    } catch (e) {
      setErr(String(e))
    }
    setBusy(false)
  }
  const sizeRange = { fan_out: [8, 25], fan_in_structuring: [8, 25], round_trip: [3, 6], mule_chain: [4, 8], wash_trading: [3, 8], loss_booking: [2, 2], market_layering: [3, 6] }[kind]
  return (
    <div>
      <div className="sect" style={{ marginTop: 0 }}>
        <h4>1 · Choose what to plant</h4>
        <div className="typ-grid">
          {OPTIONS.map(([k, d]) => (
            <button key={k} className={'typ-btn' + (kind === k ? ' on' : '')} style={{ '--c': typ(k).color }} onClick={() => setKind(k)}>
              <span className="gl">{typ(k).glyph}</span><b>{typ(k).long}</b><small>{d}</small>
            </button>
          ))}
        </div>
      </div>
      <div className="sect">
        <h4>2 · How hard does it try to hide?</h4>
        <div className="slider-row" style={{ margin: 0 }}>
          <div className="top"><span>stealth</span><b style={{ fontFamily: 'var(--mono)', color: '#22d3ee' }}>{stealth.toFixed(2)}</b></div>
          <input type="range" min="0" max="1" step="0.05" value={stealth} onChange={(e) => setStealth(+e.target.value)} />
          <div className="sub">0 = sloppy launderer · 1 = keeps every piece under the reporting threshold and dilutes with outside trades</div>
        </div>
        {sizeRange[0] !== sizeRange[1] && (
          <div className="slider-row">
            <div className="top"><span>ring size</span><b style={{ fontFamily: 'var(--mono)', color: '#22d3ee' }}>{size || 'auto'}</b></div>
            <input type="range" min="0" max={sizeRange[1]} step="1" value={size} onChange={(e) => setSize(+e.target.value)} />
            <div className="sub">0 = random in the usual range</div>
          </div>
        )}
      </div>
      <button className="btn primary" style={{ width: '100%', justifyContent: 'center', padding: 12, fontSize: 14, margin: '14px 0 4px' }} disabled={busy} onClick={go}>
        {busy ? 'Planting…' : `＋ Plant it at day ${Math.round(Math.max(12, Math.min(84, day)))}`}
      </button>
      <div className="sub" style={{ textAlign: 'center' }}>A brand-new ring is generated into the live data and run through the same detectors and model. It may well be missed.</div>
      {busy && <div style={{ marginTop: 22 }}><div className="spin" /><div className="steps">{STEPS[step]}</div></div>}
      {err && <div className="truth fa">{err}</div>}
      {res && (
        <div className="sect" ref={vref}>
          <h4>Verdict · {res.ring_id}</h4>
          <div className="verdict">
            <div className={'vcard ' + (res.caught ? 'good' : 'bad')}>
              <h5>TwinTrace</h5>
              <b>{res.caught ? 'CAUGHT' : 'MISSED'}</b>
              <small>{res.closest ? `score ${res.closest.score.toFixed(1)} · bar ${res.closest.threshold.toFixed(1)}` : 'no suspicious cluster formed'}</small>
            </div>
            <div className={'vcard ' + (!res.baseline.caught ? 'bad' : res.baseline.flagged_accounts < res.baseline.ring_accounts / 2 ? 'meh' : 'good')}>
              <h5>Rule baseline</h5>
              <b>{!res.baseline.caught ? 'MISSED' : 'TOUCHED'}</b>
              <small>flagged {res.baseline.flagged_accounts} of {res.baseline.ring_accounts} accounts, among ~1,600 other alerts</small>
            </div>
          </div>
          {res.alert && <div className="summary" style={{ fontSize: 12.5 }}>{res.alert.summary}</div>}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn sm primary" onClick={() => onWatch(res)}>▶ Watch it unfold</button>
            {res.alert && <button className="btn sm" onClick={() => onOpenAlert(res.alert.alert_id)}>Open case file</button>}
            {!res.caught && res.closest && <button className="btn sm" onClick={() => onLower(res)}>Lower the bar to catch it</button>}
          </div>
          {!res.caught && <div className="truth fa" style={{ marginTop: 10 }}><b>Honest miss.</b> {res.closest ? 'A cluster formed, but its score fell below the bar. Lowering the bar would catch it, at the price of more false alarms.' : 'The pattern never formed a cluster the detectors could see. Try lower stealth.'}</div>}
        </div>
      )}
      {injected > 0 && <button className="btn sm danger" style={{ marginTop: 18 }} onClick={onClear}>Remove all planted rings</button>}
    </div>
  )
}
