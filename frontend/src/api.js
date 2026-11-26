async function req(method, url, body) {
  const r = await fetch('/api' + url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) {
    let msg = r.statusText
    try {
      const d = (await r.json()).detail
      if (Array.isArray(d)) msg = d.map((e) => e.msg || JSON.stringify(e)).join('; ')
      else msg = typeof d === 'string' ? d : JSON.stringify(d)
    } catch {}
    throw new Error(msg)
  }
  return r.status === 204 ? null : r.json()
}

export const api = {
  meta: () => req('GET', '/meta'),
  searchOffers: (q) => req('GET', `/offers?q=${encodeURIComponent(q)}&limit=15`),
  listCampaigns: () => req('GET', '/campaigns?limit=100'),
  createCampaign: (data) => req('POST', '/campaigns', data),
  getCampaign: (id) => req('GET', `/campaigns/${id}`),
  addOffer: (id, offer_id) => req('POST', `/campaigns/${id}/offers`, { offer_id }),
  removeOffer: (id, offer_id) => req('DELETE', `/campaigns/${id}/offers/${offer_id}`),
  setShares: (id, shares) => req('PUT', `/campaigns/${id}/offers/shares`, { shares }),
  equalize: (id) => req('POST', `/campaigns/${id}/offers/equalize`),
}
