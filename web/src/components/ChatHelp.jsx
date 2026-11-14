import React, { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { NEXT, STORY, plain } from './WhatYouSee.jsx'
import { typ } from '../util'

const f2 = (x) => Number(x).toFixed(2)
const pc = (x, d = 1) => `${(x * 100).toFixed(d)}%`

/** Each entry: the predefined question, keywords for free-text matching, and an answer built from the app's real numbers. */
const KB = [
  { id: 'what', q: 'What is TwinTrace?', keys: ['twintrace', 'overview', 'this project', 'purpose', 'what does this do'], pop: true,
    a: () => ['TwinTrace is a live radar for dirty money. It watches bank transfers and stock trades together and finds groups of accounts that move money the way criminals do.',
      'Banks usually check one transaction at a time, so each piece looks innocent. TwinTrace looks at how accounts are connected, names the type of crime, and shows an investigator how the money moved.'] },
  { id: 'see', q: 'What am I looking at?', keys: ['looking at', 'screen', 'dots', 'globe', 'board', 'colour', 'color', 'legend', 'circle', 'diamond', 'shape'], pop: true,
    a: () => ['Each glowing point on the globe is one flagged ring: a group of accounts that behaved like a known laundering pattern. Colour shows the type of crime, and taller points mean a higher risk score.',
      'In the flat 2D view, circles are bank accounts and diamonds are trading accounts. Lines are money moving, and thicker lines mean more money. Use the 2D | Globe switch to change views.'] },
  { id: 'replay', q: 'How do I use the replay?', keys: ['replay', 'play', 'timeline', 'time', 'days', 'scrub', 'watch'],
    a: () => ['Press the round play button (or Space). The 90 days play out, money moves, and each ring lights up with an alert the moment its pattern completes.',
      'Drag along the bottom timeline to jump to any day. The shaded zones show which days the model trained on, which it was checked on, and which it never saw (the test period).'] },
  { id: 'types', q: 'What do the crime types mean?', keys: ['type', 'typology', 'fan-out', 'fan out', 'structuring', 'round', 'mule', 'wash', 'loss', 'layering', 'crime', 'pattern', 'smurf', 'wash trading', 'loss-booking'], pop: true,
    a: () => ['These are the seven patterns we detect:', ...['fan_out', 'fan_in_structuring', 'round_trip', 'mule_chain', 'wash_trading', 'loss_booking', 'market_layering'].map((k) => `• ${typ(k).long}: ${STORY[k]}`)] },
  { id: 'score', q: 'What does the risk score mean?', keys: ['risk', 'score', 'gauge', '100', 'confidence', 'probability'],
    a: () => ['The risk score runs from 0 to 100. It comes from a trained model that looks at how closely a group of accounts matches a known laundering pattern.',
      'It is a ranking tool, not a verdict. A high score means "look at this first", and a human investigator decides what it means.'] },
  { id: 'accuracy', q: 'How accurate is it?', keys: ['accurate', 'accuracy', 'precision', 'recall', 'f1', 'false', 'results', 'performance', 'good', 'how well', 'benchmark', 'baseline'], pop: true,
    a: (c) => {
      const m = c.board.methods, t = m.twintrace, r = m.rule_baseline
      return [`On the held-out test period (${t.rings} planted rings the model never saw): TwinTrace caught ${t.found} of ${t.rings} (recall ${f2(t.recall)}) and ${pc(t.precision, 0)} of its alerts were real rings (precision ${f2(t.precision)}).`,
        `A simple rule system (flag any large transfer) flags ${pc(r.fpr, 1)} of innocent accounts, against ${pc(t.fpr, 2)} for TwinTrace, and raises about ${r.per1000.toFixed(0)} alerts per 1,000 accounts against ${t.per1000.toFixed(1)}.`,
        'These numbers come from synthetic data we generated, so treat them as a prototype benchmark, not a promise about real banks.'] } },
  { id: 'real', q: 'Is this real data?', keys: ['real', 'data', 'synthetic', 'fake', 'dataset', 'ibm', 'source'], pop: true,
    a: () => ['No. All data is synthetic: about 114,000 generated bank transfers, 43,000 trades and 280 planted laundering rings, modelled on the format of IBM\'s public AML dataset.',
      'That is why we can show ground truth (the "Reveal truth" button). We wrote a loader for the real IBM files but have not run it on them yet. No real people or firms are involved.'] },
  { id: 'trace', q: 'How does click-to-trace work?', keys: ['trace', 'follow', 'upstream', 'downstream', 'hops', 'hop', 'top', 'money trail'],
    a: () => ['Click any account (or "Trace the money" in a case file) to follow its money. Accounts on the left sent money in; accounts on the right received it.',
      '"Hops" is how many steps away you follow (1 hop = direct partners, 2 hops = their partners too). "Top" is how many of the biggest payments to show at each step. Defaults of 2 hops and top 4 keep it readable.'] },
  { id: 'plant', q: 'What does "Plant a ring" do?', keys: ['plant', 'inject', 'new ring', 'live', 'stealth', 'hide', 'size'], pop: true,
    a: () => ['It creates a brand-new laundering ring in the live data and runs it through the same detectors and trained model, so you see whether TwinTrace catches it, and whether the old rule system does.',
      '"Stealth" is how hard the criminals try to hide: higher means pieces stay under the reporting limit and are mixed with normal trades, so rings are harder to catch. It can miss, and the app says so when it does.'] },
  { id: 'whatif', q: 'What does the What-if lab do?', keys: ['what-if', 'what if', 'lab', 'threshold', 'strict', 'slider', 'alert bar', 'tradeoff', 'trade-off'],
    a: (c) => ['It lets you change how strict alerts are. Looser means more rings caught but more false alarms; stricter means fewer false alarms but some rings slip through.',
      `Right now ${c.shown} of ${c.total} candidate alerts are showing (about ${(c.shown / c.accounts * 1000).toFixed(1)} per 1,000 accounts). The benchmark numbers update live as you drag.`] },
  { id: 'bridge', q: 'What is the link between bank and trading?', keys: ['bridge', 'link', 'layer', 'layers', 'owner', 'two layer', 'cross', 'funding', 'both'],
    a: (c) => {
      const m = c.board.methods
      return ['TwinTrace builds two graphs, one for bank transfers and one for stock trades, and joins them through the account owner and shared funding sources. Wash trading and loss-booking are invisible to the bank layer alone.',
        `Honest result: using both layers helped a lot (F1 ${f2(m.single_layer.f1)} bank-only vs ${f2(m.twintrace.f1)} with both). But the owner link itself did not add accuracy over simply running both layers side by side. It adds cross-layer alerts and a better explanation.`]
    } },
  { id: 'why', q: 'Why was an alert flagged?', keys: ['why', 'flagged', 'reason', 'explain this', 'selected', 'this alert', 'driver', 'shap'], pop: true, dynamic: 'alert',
    a: () => [] },
  { id: 'next', q: 'What should an investigator check next?', keys: ['next', 'investigator', 'investigate', 'check', 'follow up', 'what now', 'action'], dynamic: 'next',
    a: () => [] },
  { id: 'false', q: 'Why are there false alarms?', keys: ['false alarm', 'false positive', 'wrong', 'mistake', 'innocent', 'payroll', 'merchant'],
    a: () => ['Some normal behaviour looks like laundering: payroll (one company paying many people), rent (many tenants paying one landlord), shops that pass daily takings to their owner, family transfers in a loop, market makers, and legitimate trading groups.',
      'We deliberately planted such look-alikes to test this. The regularity signal ("have these accounts paid each other before?") removes many, but not all. Use "Reveal truth" to see the false alarms in red.'] },
  { id: 'limits', q: 'What are the limitations?', keys: ['limit', 'limitation', 'weakness', 'problem', 'caveat', 'honest', 'future', 'next steps', 'improve'],
    a: () => ['• Synthetic data, so recall is optimistic compared with the real world.',
      '• We wrote both the generator and the detectors, so they fit each other.',
      '• The test set is small (45 rings), so differences of a few points are noise.',
      '• Some features look a few days ahead, so this is built for investigators, not for blocking transactions in real time.',
      '• Pump-and-dump and front-running are not implemented yet.'] },
  { id: 'explain', q: 'Do you use AI to write the explanations?', keys: ['ai', 'llm', 'gpt', 'chatgpt', 'generate', 'generated', 'language model', 'made up', 'invent', 'hallucinat'],
    a: () => ['No language model writes the summaries. Each one is a template filled only with numbers from that alert\'s own evidence, and a test checks that every number in a summary exists in the evidence.',
      'The risk score comes from an XGBoost model, and the "why flagged" reasons come from SHAP, a standard way to explain model scores. This guide also answers only from the project\'s own facts.'] },
  { id: 'keys', q: 'What are the keyboard shortcuts?', keys: ['keyboard', 'shortcut', 'keys', 'hotkey', 'key'],
    a: () => ['Space: play or pause · I: alert inbox · D: side panel · 1 / 2 / 3: Case file, What-if lab, Plant ring · P: present mode · ? : shortcut list · Esc: close what is open.'] },
  { id: 'present', q: 'How do I present this to judges?', keys: ['present', 'judges', 'demo', 'tour', 'guided', 'projector'],
    a: () => ['Press "Guided demo" for a captioned walk-through of every feature. For a projector, use "⛶ Present" (or P) to hide the panels and keep just the board, timeline and captions. Esc exits.'] },
]

const POPULAR = KB.filter((e) => e.pop)

function answerFor(text) {
  const t = ' ' + text.toLowerCase().replace(/[^a-z0-9\-\s]/g, ' ').replace(/\s+/g, ' ') + ' '
  let best = null, score = 0
  for (const e of KB) {
    if (e.q.toLowerCase().replace(/[^a-z0-9\-\s]/g, ' ').replace(/\s+/g, ' ').trim() === t.trim()) return e
    let s = 0
    for (const k of e.keys) {
      const hit = k.length <= 3 ? new RegExp('\\b' + k + '\\b').test(t) : t.includes(k)   // short keys must be whole words
      if (hit) s += k.length <= 3 ? 5 : k.length                                // whole-word short keys are deliberate; longer ones weigh more
    }
    if (s > score) { score = s; best = e }
  }
  return score >= 4 ? best : null
}

export default function ChatHelp({ board, selectedId, shown, total, accounts }) {
  const [open, setOpen] = useState(false)
  const [msgs, setMsgs] = useState([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef(null)
  useEffect(() => { end.current && end.current.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [msgs, busy, open])
  useEffect(() => {
    if (!open) return
    const k = (e) => { if (e.key === 'Escape') { e.stopImmediatePropagation(); setOpen(false) } }
    window.addEventListener('keydown', k, true)
    return () => window.removeEventListener('keydown', k, true)
  }, [open])

  const ctx = { board, shown, total, accounts }
  const compose = async (entry) => {
    if (entry.dynamic) {
      if (!selectedId) return ['Select an alert first: click one in the Alert inbox, or click a point on the globe. Then ask me again and I will explain it in plain words.']
      try {
        const d = await api.alert(selectedId)
        const a = d.alert
        const why = (a.contributions || []).slice(0, 3).map((x) => plain(x.label))
        if (entry.dynamic === 'next') return [`For ${a.alert_id} (${a.typology_name}):`, NEXT[a.typology] || NEXT.unclassified_anomaly]
        return [`${a.alert_id} is a "${a.typology_name}" alert with a risk score of ${Math.round(a.score)} out of 100.`, STORY[a.typology] || STORY.unclassified_anomaly,
          why.length ? `The model flagged it mainly because ${why.join('; ')}.` : 'It matches a known laundering shape.', a.summary]
      } catch (e) { return ['I could not load that alert just now. Please try again.'] }
    }
    return entry.a(ctx)
  }
  const ask = async (q, entry) => {
    const question = q.trim()
    if (!question || busy) return
    setMsgs((m) => [...m, { who: 'me', lines: [question] }])
    setText('')
    setBusy(true)
    const e = entry || answerFor(question)
    const lines = e ? await compose(e) : ['I can only answer questions about TwinTrace itself: what you see, how it works, how accurate it is, and how to use it. Try one of the questions below.']
    setTimeout(() => { setMsgs((m) => [...m, { who: 'bot', lines, miss: !e }]); setBusy(false) }, 380)
  }
  const chips = (list) => list.map((e) => <button key={e.id} className="chat-chip" onClick={() => ask(e.q, e)}>{e.q}</button>)
  return (
    <>
      <button className={'chat-fab' + (open ? ' on' : '')} onClick={() => setOpen(!open)} aria-label="Open the TwinTrace guide" title="Ask the TwinTrace guide">
        {open ? '✕' : '💬'}
      </button>
      {open && (
        <div className="chat-panel" role="dialog" aria-label="TwinTrace guide">
          <div className="chat-h">
            <div><b>TwinTrace guide</b><small>Answers come from this project&apos;s own facts and live numbers, not an AI model.</small></div>
          </div>
          <div className="chat-body">
            {msgs.length === 0 && (
              <div className="chat-hello">
                <p>Hi! Ask me anything about what you are seeing, or pick a popular question:</p>
                <div className="chat-chips">{chips(POPULAR)}</div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={'chat-msg ' + m.who}>
                {m.lines.map((l, j) => <p key={j}>{l}</p>)}
              </div>
            ))}
            {busy && <div className="chat-msg bot typing"><i /><i /><i /></div>}
            {msgs.length > 0 && !busy && (
              <div className="chat-more">
                <span>More questions</span>
                <div className="chat-chips">{chips(KB.filter((e) => !msgs.some((m) => m.who === 'me' && m.lines[0] === e.q)).slice(0, 6))}</div>
              </div>
            )}
            <div ref={end} />
          </div>
          <form className="chat-in" onSubmit={(e) => { e.preventDefault(); ask(text) }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Ask a question…" autoFocus />
            <button type="submit" disabled={!text.trim() || busy}>Send</button>
          </form>
        </div>
      )}
    </>
  )
}
