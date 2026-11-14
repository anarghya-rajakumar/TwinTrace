const j = async (r) => {
  if (!r.ok) throw new Error((await r.text()) || r.statusText)
  return r.json()
}
export const api = {
  board: () => fetch('/api/board').then(j),
  alert: (id) => fetch(`/api/alert/${id}`).then(j),
  trace: (account, depth = 3, perNode = 5, direction = 'both') =>
    fetch(`/api/trace?account=${account}&depth=${depth}&per_node=${perNode}&direction=${direction}`).then(j),
  whatif: (money, trade, split = 'test') =>
    fetch(`/api/whatif?money=${money}&trade=${trade}&split=${split}`).then(j),
  search: (q) => fetch(`/api/search?q=${encodeURIComponent(q)}`).then(j),
  plant: (body) =>
    fetch('/api/plant', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(j),
  reset: () => fetch('/api/reset', { method: 'POST' }).then(j),
}
