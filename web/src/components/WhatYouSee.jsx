import React, { useState } from 'react'
import { COLORS, typ } from '../util'

export const STORY = {
  fan_out: 'One account split a pile of money into many small payments to many different accounts, very quickly.',
  fan_in_structuring: 'Many accounts each sent a small payment to the same account, and every payment was just under the reporting limit (the amount banks must report), so no single payment looked suspicious.',
  fan_in: 'Many accounts sent money to the same single account in a short time.',
  round_trip: 'Money travelled in a circle through several accounts and came back to where it started.',
  mule_chain: 'Money was passed through several accounts within minutes, like a relay race, with almost nothing kept along the way.',
  wash_trading: 'A small group kept buying and selling the same stock to each other to fake trading activity.',
  loss_booking: 'Two accounts traded back and forth at odd prices so that one shows a loss and the other shows a gain.',
  market_layering: 'The same group got money from one source and then traded among themselves, and the money left again afterwards.',
  unclassified_anomaly: 'A group of accounts moved money in an unusual way, but it does not match one of the named patterns.',
}

export const NEXT = {
  fan_out: 'Who received the payments? Do they share an owner or were they opened recently? Where did the original money come from?',
  fan_in_structuring: 'Do the sending accounts know each other or share an owner? What did the receiving account do with the money next?',
  fan_in: 'Who are the senders, and are they linked to each other? Where did the receiving account send the money?',
  round_trip: 'Is there a real reason the money came back (a refund or a loan)? Do the same people control these accounts?',
  mule_chain: 'Find who started the chain and who got the money at the end. Are the middle accounts new, or do they have little other activity?',
  wash_trading: 'Do the accounts share an owner or a funding source? Did the trades move the share price or help anyone?',
  loss_booking: 'Who owns the two accounts? Was the loss used to cut tax or to move value from one account to the other?',
  market_layering: 'Trace the funding source and the account that received the money afterwards. Are the traders linked to the funder?',
  unclassified_anomaly: 'Look at who is at both ends of the biggest transfers, and whether those accounts are linked.',
}

// the model's feature names, in everyday words
const PLAIN = {
  'pass-through detector': 'money was passed on quickly',
  'amount similarity': 'the payments were about the same size',
  'share just under threshold': 'many amounts were just under the reporting limit',
  'total amount': 'a large total amount moved',
  'owner / funding link': 'the accounts share an owner or a funding source',
  'members trade mostly with each other': 'the group mostly trades with each other',
  'max price deviation': 'some trades were at prices far from the market price',
  'off-market price deviation': 'trades were at prices far from the market price',
  'inflow/outflow ratio': 'what went out almost equals what came in',
  'money staying inside the cluster': 'the money stayed inside the group',
  'time clustering': 'everything happened in a short time',
  'dwell time': 'money stayed in each account only briefly',
  'fan-out detector': 'one account paid out to many',
  'fan-in detector': 'many accounts paid into one',
  'structuring detector': 'payments were kept just under the reporting limit',
  'round-trip detector': 'money went in a circle',
  'wash-trading detector': 'the same shares moved around inside a group',
  'loss-booking detector': 'trades at odd prices created a loss and a gain',
  'shared funding source': 'the accounts got money from the same source',
  'cash-out chain': 'the money left the group afterwards',
  'volume staying inside the group': 'most of the trading stayed inside the group',
  'net position vs gross volume': 'lots of trading but almost no real change in holdings',
  'pairs seen before (regularity)': 'these accounts had not paid each other before',
}
export const plain = (l) => PLAIN[l] || l

function Sw({ c, shape = 'circle', dashed }) {
  const base = { display: 'inline-block', width: 11, height: 11, verticalAlign: '-1px', margin: '0 3px 0 1px', background: dashed ? 'transparent' : c, border: dashed ? `1.5px dashed ${c}` : 'none' }
  if (shape === 'diamond') return <span style={{ ...base, transform: 'rotate(45deg) scale(.8)' }} />
  if (shape === 'square') return <span style={{ ...base, borderRadius: 2 }} />
  return <span style={{ ...base, borderRadius: '50%' }} />
}

/** "What you are looking at": a plain-language key and story that sits directly above a network graph. */
export default function WhatYouSee({ kind, alert, trace, globe }) {
  const [open, setOpen] = useState(true)
  let legend, story, why, next
  if (kind === 'alert' && alert) {
    const t = alert.typology
    const c = typ(t).color
    const tradey = alert.layer === 'trade' || alert.layer === 'bridge'
    legend = (
      <>
        <Sw c={c} /> Circles are accounts. Lines with moving dashes are money moving, and <b>thicker lines mean more money</b>.{' '}
        <Sw c="#22d3ee" shape="diamond" /> A <b style={{ color: '#22d3ee' }}>cyan diamond</b> is an entry point (money coming in from outside this group).{' '}
        <Sw c="#ff3b5c" shape="square" /> A <b style={{ color: '#ff8aa0' }}>red square</b> is an exit point (money leaving this group).{' '}
        <Sw c="#5b6b8c" dashed /> Grey dashed circles are outside accounts.
        {tradey && <> <Sw c="#a78bfa" /> Purple dashed lines are share trades; dotted lines link a bank account to its owner’s trading account.</>}
      </>
    )
    story = STORY[t] || STORY.unclassified_anomaly
    const reasons = (alert.contributions || []).slice(0, 3).map((x) => plain(x.label))
    why = reasons.length
      ? `The risk score is ${Math.round(alert.score)} out of 100 mainly because ${reasons.join('; ')}.`
      : `The risk score is ${Math.round(alert.score)} out of 100 because the pattern matches a known laundering shape.`
    next = NEXT[t] || NEXT.unclassified_anomaly
  } else if (kind === 'trace') {
    legend = (
      <>
        <Sw c={COLORS.cyan} /> The big <b style={{ color: '#22d3ee' }}>cyan</b> circle is the account you clicked. <Sw c="#5b8bea" /> Blue circles are bank accounts and <Sw c="#a58cf0" shape="diamond" /> violet diamonds are trading accounts. <Sw c="#ff3b5c" /> <b style={{ color: '#ff8aa0' }}>Red</b> accounts were flagged by TwinTrace.
        Lines with moving dots are money moving, and <b>thicker lines mean more money</b> (violet dashed = share trades, dotted = same owner). Accounts on the <b>left</b> sent money in from outside this group; accounts on the <b>right</b> received money leaving it.
      </>
    )
    story = trace && trace.flagged > 0
      ? `This account is linked to ${trace.flagged} flagged account${trace.flagged > 1 ? 's' : ''}, so we are following its money to see where the group gets money from and where it goes.`
      : 'We are following this account’s money, step by step, to see where it came from and where it went.'
    why = trace && trace.originAlerts ? 'It belongs to a flagged ring. Open the alert button on the right to see the reasons.' : 'This account is not part of a flagged ring on its own. It is shown so you can follow the trail.'
    next = 'Look for accounts on the left that feed many others, and on the right that pass money on within minutes. Click any account to keep following.'
  } else if (globe) {
    legend = (
      <>
        <Sw c="#ff3b5c" /> Each glowing point on the globe is <b>one flagged ring</b>, coloured by the type of crime and taller when the risk is higher. Select a ring to see its accounts (circles) and arcs showing money moving (thicker = more money). Where a ring sits on the map is made up, because our data has no locations.
      </>
    )
    story = 'Each point is a group of accounts that moved money in a pattern criminals use to hide it, found among thousands of normal accounts.'
    why = 'A ring is flagged when its pattern is very close to a known laundering shape and scores high on risk (the score is out of 100).'
    next = 'Click a point to open its case file, or press play to watch rings appear over the 90 days.'
  } else {
    legend = (
      <>
        <Sw c="#6c93e0" /> Circles are bank accounts and <Sw c="#a58cf0" shape="diamond" /> diamonds are trading accounts. Faint lines are money moving (thicker = more money; dashed = share trades). <b>Glowing groups</b> are flagged rings, coloured by the type of crime. Use the replay to watch money move over time.
      </>
    )
    story = 'Each glowing group is a set of accounts that moved money in a pattern criminals use to hide it, found among thousands of normal accounts.'
    why = 'A group is flagged when its pattern is very close to a known laundering shape and scores high on risk (the score is out of 100).'
    next = 'Click a glowing group to open its case file, or click any account to trace where its money came from and went.'
  }
  const items = [['What the picture shows', legend], ['The story here', story], ['Why it was flagged', why], ['What an investigator would check next', next]]
  return (
    <div className="wys">
      <button className="wys-h" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span>ⓘ What you are looking at</span>
        <span className="sub">{open ? '▾ hide' : '▸ show'}</span>
      </button>
      {open && (
        <ul>
          {items.map(([h, b]) => (
            <li key={h}><b>{h}.</b> {b}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
