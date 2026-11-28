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

  listCampaigns: () => req('GET', '/campaigns'),
  syncCampaigns: () => req('POST', '/campaigns/sync'),
  createCampaign: (data) => req('POST', '/campaigns', data),
  getCampaign: (id) => req('GET', `/campaigns/${id}`),
  pullCampaign: (id) => req('POST', `/campaigns/${id}/pull`),
  pushCampaign: (id) => req('POST', `/campaigns/${id}/push`),

  pushStream: (streamId) => req('POST', `/streams/${streamId}/push`),
  cancelStream: (streamId) => req('POST', `/streams/${streamId}/cancel`),
  addOffer: (streamId, offerId) => req('POST', `/streams/${streamId}/offers`, { offer_id: offerId }),
  removeOffer: (streamId, offerId) => req('DELETE', `/streams/${streamId}/offers/${offerId}`),
  restoreOffer: (streamId, offerId) => req('POST', `/streams/${streamId}/offers/${offerId}/restore`),
  purgeOffer: (streamId, offerId) => req('DELETE', `/streams/${streamId}/offers/${offerId}/purge`),
  pinOffer: (streamId, offerId, pinned) => req('PUT', `/streams/${streamId}/offers/${offerId}/pin`, { pinned }),
  setShares: (streamId, shares) => req('PUT', `/streams/${streamId}/offers/shares`, { shares }),
  equalize: (streamId) => req('POST', `/streams/${streamId}/offers/equalize`),
}
