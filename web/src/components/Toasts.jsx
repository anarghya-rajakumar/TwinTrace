import React from 'react'

export default function Toasts({ items }) {
  return (
    <div className="toasts">
      {items.map((x) => (
        <div key={x.id} className="toast" style={{ '--c': x.color }}>
          <span style={{ fontSize: 18 }}>{x.icon}</span>
          <span dangerouslySetInnerHTML={{ __html: x.html }} />
        </div>
      ))}
    </div>
  )
}
