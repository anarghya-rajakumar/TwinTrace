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
  const noun = { fan_out: 'receiving accounts', fan_in_structuring: 'sending accounts', round_trip: 'accounts in the loop', mule_chain: 'steps (hops) in the chain', wash_trading: 'trading accounts', loss_booking: 'accounts', market_layering: 'trading accounts' }[kind]
  const startDay = Math.round(Math.max(12, Math.min(84, day)))
  const word = stealth < 0.2 ? 'very obvious' : stealth < 0.4 ? 'barely hidden' : stealth < 0.6 ? 'partly hidden' : stealth < 0.8 ? 'well hidden' : 'very well hidden'
  const harder = stealth < 0.4 ? 'easy to catch' : stealth < 0.6 ? 'a bit harder to catch' : stealth < 0.8 ? 'harder to catch' : 'much harder to catch'
  const sizeText = size ? `${size} ${noun}` : `a random number of ${noun} (usually ${sizeRange[0]}–${sizeRange[1]})`
  const reset = () => { setKind('mule_chain'); setStealth(0.6); setSize(0) }
  const Tip = ({ t }) => <span className="tip" tabIndex={0} data-tip={t}>?</span>
  const val = { fontFamily: 'var(--mono)', color: '#5d6b2f' }
  return (
    <div>
      <div className="sect" style={{ marginTop: 0 }}>
        <h4 title="The kind of crime pattern and how big it is">Ring shape</h4>
        <div className="top" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5, marginTop: 6 }}>
          <span title="Pick the laundering pattern the hidden ring will follow.">What kind of crime should the hidden ring commit?
            <Tip t="Each type is a different way criminals hide money. Changing it changes which detector has to catch it. Any type is safe to try." /></span>
        </div>
        <div className="typ-grid">
          {OPTIONS.map(([k, d]) => (
            <button key={k} className={'typ-btn' + (kind === k ? ' on' : '')} style={{ '--c': typ(k).color }} onClick={() => setKind(k)} title={`${typ(k).long}: ${d}`}>
              <span className="gl">{typ(k).glyph}</span><b>{typ(k).long}</b><small>{d}</small>
            </button>
          ))}
        </div>
        {sizeRange[0] !== sizeRange[1] ? (
          <div className="slider-row">
            <div className="top">
              <span title="How many accounts take part in each hidden ring.">How many accounts are in each hidden ring
                <Tip t={`Move it up for bigger rings (more accounts, usually easier to spot); move it down for small, quiet ones. Safe range: 0 to ${sizeRange[1]}. 0 means random size within the usual ${sizeRange[0]}–${sizeRange[1]}.`} /></span>
              <b style={val}>{size || 'auto'}</b>
            </div>
            <input type="range" min="0" max={sizeRange[1]} step="1" value={size} onChange={(e) => setSize(+e.target.value)} title="How many accounts are in each hidden ring" />
            <div className="caption">{size ? `Size ${size}: each ring has ${size} ${noun}.` : `Size auto: a random number of ${noun}, usually ${sizeRange[0]}–${sizeRange[1]}.`}</div>
          </div>
        ) : (
          <div className="caption" style={{ marginTop: 8 }}>This pattern always uses exactly 2 accounts, so there is no size to adjust.</div>
        )}
      </div>
      <div className="grp">
        <h4 title="When the hidden ring's money starts moving">Timing</h4>
        <div className="top" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12.5 }}>
          <span title="The day the ring starts moving money.">Day the ring starts
            <Tip t="It follows the replay clock. Drag the timeline at the bottom to pick another day. Safe range: day 12 to day 84, so the ring has time to play out." /></span>
          <b style={val}>day {startDay}</b>
        </div>
        <div className="caption">Starts around day {startDay} of 90. Move the replay timeline to change it.</div>
      </div>
      <div className="grp">
        <h4 title="How much the criminals try to avoid the reporting limit and blend into normal traffic">Reporting limit and background noise</h4>
        <div className="slider-row" style={{ margin: '6px 0 0' }}>
          <div className="top">
            <span title="How hard the criminals try to look normal.">How well do the criminals hide?
              <Tip t="Up = pieces stay under the reporting limit (the amount banks must report) and are mixed with normal trades, so rings are harder to catch. Down = sloppy, easy to catch. Safe range: 0 to 1. Around 0.6 is the tested default." /></span>
            <b style={val}>{stealth.toFixed(2)}</b>
          </div>
          <input type="range" min="0" max="1" step="0.05" value={stealth} onChange={(e) => setStealth(+e.target.value)} title="How hard the criminals try to look normal" />
          <div className="caption">Stealth {stealth.toFixed(1)}: rings are {word}, so they are {harder}.</div>
        </div>
      </div>
      <div className="settings-line">
        <b>With these settings:</b> a {typ(kind).long.toLowerCase()} ring with {sizeText}, {word} (stealth {stealth.toFixed(2)}), starting around day {startDay}.
      </div>
      <button className="btn sm" style={{ marginBottom: 4 }} onClick={reset} title="Put every control back to its starting value">⟲ Reset to defaults</button>
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
