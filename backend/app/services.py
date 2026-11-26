from sqlalchemy.orm import Session

from .config import settings
from .keitaro import KeitaroClient, KeitaroError
from .models import CampaignRecord, OfferChange
from .schemas import CampaignCreate, ShareItem

GOOGLE_URL = "https://google.com"


# ---------- справочники ----------
def _pick(items: list[dict], wanted_id: int, label: str) -> dict:
    for it in items:
        if int(it["id"]) == wanted_id:
            return it
    if items:
        return items[0]
    raise KeitaroError(409, f"В Keitaro нет ни одного значения справочника: {label}")


def resolve_defaults(kt: KeitaroClient) -> dict:
    domain = _pick(kt.domains(), settings.default_domain_id, "домены")
    group = _pick(kt.groups(), settings.default_group_id, "группы")
    source = _pick(kt.sources(), settings.default_source_id, "источники")
    return {
        "domain": {"id": domain["id"], "name": domain.get("name")},
        "group": {"id": group["id"], "name": group.get("name")},
        "source": {"id": source["id"], "name": source.get("name")},
    }


def search_offers(kt: KeitaroClient, q: str, limit: int = 20) -> list[dict]:
    q = (q or "").strip().lower()
    result = []
    for o in kt.offers():
        name = str(o.get("name", ""))
        if not q or q in name.lower() or q == str(o.get("id")):
            result.append({"id": o["id"], "name": name})
            if len(result) >= limit:
                break
    return result


# ---------- доли ----------
def equal_shares(offer_ids: list[int]) -> list[dict]:
    """Равномерное распределение долей, сумма всегда ровно 100."""
    n = len(offer_ids)
    if n == 0:
        return []
    base, rem = divmod(100, n)
    return [
        {"offer_id": oid, "share": base + (1 if i < rem else 0), "state": "active"}
        for i, oid in enumerate(offer_ids)
    ]


# ---------- создание кампании ----------
def create_campaign(kt: KeitaroClient, db: Session, data: CampaignCreate) -> dict:
    offer = kt.offer(data.offer_id)  # 404 от Keitaro, если оффера нет
    defaults = resolve_defaults(kt)

    campaign = kt.post(
        "/campaigns",
        {
            "name": data.name,
            "type": "position",
            "domain_id": defaults["domain"]["id"],
            "group_id": defaults["group"]["id"],
            "traffic_source_id": defaults["source"]["id"],
            "state": "active",
        },
    )
    cid = campaign["id"]
    try:
        kt.post(
            "/streams",
            {
                "campaign_id": cid,
                "name": f"Geo {data.geo}",
                "type": "regular",
                "schema": "redirect",
                "position": 1,
                "action_type": "http",
                "action_payload": GOOGLE_URL,
                "filters": [{"name": "country", "mode": "accept", "payload": data.geo.split(",")}],
            },
        )
        kt.post(
            "/streams",
            {
                "campaign_id": cid,
                "name": "Офферы",
                "type": "default",
                "schema": "landings",
                "position": 2,
                "offers": equal_shares([data.offer_id]),
            },
        )
    except KeitaroError:
        # не оставляем «полусобранную» кампанию
        try:
            kt.delete(f"/campaigns/{cid}")
        except KeitaroError:
            pass
        raise

    db.add(CampaignRecord(keitaro_id=cid, name=data.name, geo=data.geo, offer_id=data.offer_id))
    db.commit()
    return {
        "id": cid,
        "name": data.name,
        "geo": data.geo.split(","),
        "offer": {"id": offer.get("id", data.offer_id), "name": offer.get("name")},
        **defaults,
        "admin_url": f"{settings.admin_base}/admin/#!/campaign.editor/{cid}",
    }


# ---------- редактор ----------
def _offer_names(kt: KeitaroClient) -> dict[int, str]:
    return {int(o["id"]): str(o.get("name", "")) for o in kt.offers()}


def _streams(kt: KeitaroClient, campaign_id: int) -> list[dict]:
    return kt.get(f"/campaigns/{campaign_id}/streams") or []


def _offers_stream(streams: list[dict]) -> dict | None:
    for s in streams:
        if s.get("type") == "default" and s.get("schema") == "landings":
            return s
    for s in streams:
        if s.get("schema") == "landings":
            return s
    return None


def _stream_offers(stream: dict | None) -> list[dict]:
    return list(stream.get("offers") or []) if stream else []


def campaign_view(kt: KeitaroClient, campaign_id: int) -> dict:
    campaign = kt.get(f"/campaigns/{campaign_id}")
    streams = _streams(kt, campaign_id)
    names = _offer_names(kt)
    offers_stream = _offers_stream(streams)

    out_streams = []
    for s in streams:
        out_streams.append(
            {
                "id": s["id"],
                "name": s.get("name"),
                "type": s.get("type"),
                "schema": s.get("schema"),
                "state": s.get("state"),
                "action_type": s.get("action_type"),
                "action_payload": s.get("action_payload"),
                "filters": s.get("filters") or [],
                "offers": [
                    {
                        "offer_id": int(o["offer_id"]),
                        "name": names.get(int(o["offer_id"]), f"#{o['offer_id']}"),
                        "share": o.get("share", 0),
                        "state": o.get("state", "active"),
                    }
                    for o in (s.get("offers") or [])
                ],
            }
        )
    return {
        "id": campaign["id"],
        "name": campaign.get("name"),
        "state": campaign.get("state"),
        "alias": campaign.get("alias"),
        "admin_url": f"{settings.admin_base}/admin/#!/campaign.editor/{campaign['id']}",
        "offers_stream_id": offers_stream["id"] if offers_stream else None,
        "streams": out_streams,
    }


def _save_offers(kt: KeitaroClient, campaign_id: int, stream: dict | None, offers: list[dict]) -> None:
    if stream is None:
        kt.post(
            "/streams",
            {
                "campaign_id": campaign_id,
                "name": "Офферы",
                "type": "default",
                "schema": "landings",
                "offers": offers,
            },
        )
    else:
        # PUT заменяет состав офферов целиком
        kt.put(f"/streams/{stream['id']}", {"offers": offers})


def add_offer(kt: KeitaroClient, db: Session, campaign_id: int, offer_id: int) -> dict:
    kt.offer(offer_id)  # проверка существования
    stream = _offers_stream(_streams(kt, campaign_id))
    ids = [int(o["offer_id"]) for o in _stream_offers(stream)]
    if offer_id in ids:
        raise KeitaroError(409, "Оффер уже есть в кампании")
    _save_offers(kt, campaign_id, stream, equal_shares(ids + [offer_id]))
    db.add(OfferChange(campaign_id=campaign_id, offer_id=offer_id, action="add"))
    db.commit()
    return campaign_view(kt, campaign_id)


def remove_offer(kt: KeitaroClient, db: Session, campaign_id: int, offer_id: int) -> dict:
    stream = _offers_stream(_streams(kt, campaign_id))
    ids = [int(o["offer_id"]) for o in _stream_offers(stream)]
    if offer_id not in ids:
        raise KeitaroError(404, "Такого оффера нет в кампании")
    rest = [i for i in ids if i != offer_id]
    _save_offers(kt, campaign_id, stream, equal_shares(rest))
    db.add(OfferChange(campaign_id=campaign_id, offer_id=offer_id, action="remove"))
    db.commit()
    return campaign_view(kt, campaign_id)


def set_shares(kt: KeitaroClient, db: Session, campaign_id: int, items: list[ShareItem]) -> dict:
    stream = _offers_stream(_streams(kt, campaign_id))
    current = {int(o["offer_id"]): o for o in _stream_offers(stream)}
    given = {i.offer_id: i.share for i in items}
    if set(given) != set(current):
        raise KeitaroError(422, "Список офферов не совпадает с текущим составом кампании")
    if current and sum(given.values()) != 100:
        raise KeitaroError(422, f"Сумма долей должна быть 100, сейчас {sum(given.values())}")
    offers = [
        {"offer_id": oid, "share": given[oid], "state": current[oid].get("state", "active")}
        for oid in current
    ]
    _save_offers(kt, campaign_id, stream, offers)
    db.add(OfferChange(campaign_id=campaign_id, offer_id=0, action="shares"))
    db.commit()
    return campaign_view(kt, campaign_id)


def equalize(kt: KeitaroClient, db: Session, campaign_id: int) -> dict:
    stream = _offers_stream(_streams(kt, campaign_id))
    ids = [int(o["offer_id"]) for o in _stream_offers(stream)]
    if stream is not None and ids:
        _save_offers(kt, campaign_id, stream, equal_shares(ids))
    return campaign_view(kt, campaign_id)
