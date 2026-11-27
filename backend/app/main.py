from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import services
from app.db import get_db
from app.keitaro import KeitaroClient, KeitaroError, get_client
from app.models import CampaignRecord
from app.schemas import CampaignCreate, OfferAdd, SharesUpdate

app = FastAPI(title='Adrobot')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.exception_handler(KeitaroError)
async def keitaro_error_handler(_: Request, exception: KeitaroError) -> JSONResponse:
    """
    Перехват ошибки KeitaroError и последующее формирование ошибки.

    :param _: Запрос, вызвавший ошибку.
    :param exception: Ошибка.
    :return: Ответ с информацией о полученной ошибке.
    """
    status = exception.status if exception.status in (400, 404, 409, 422) else 502
    detail = exception.detail
    if isinstance(detail, dict):
        detail = detail.get('error') or detail.get('message') or detail
    return JSONResponse(status_code=status, content={'detail': detail})


@app.get('/api/health')
def health() -> JSONResponse:
    """Проверка доступности сервера"""
    return JSONResponse(status_code=200, content={'ok': True})


@app.get('/api/meta')
def meta(kt: KeitaroClient = Depends(get_client)):
    return services.resolve_defaults(kt)


@app.get('/api/offers')
def offers(q: str = '', limit: int = Query(20, ge=1, le=100), kt: KeitaroClient = Depends(get_client)):
    return services.search_offers(kt, q, limit)


@app.get('/api/campaigns')
def list_campaigns(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    kt: KeitaroClient = Depends(get_client),
):
    items = kt.get('/campaigns', offset=offset, limit=limit) or []
    return [
        {'id': c['id'], 'name': c.get('name'), 'state': c.get('state'), 'alias': c.get('alias')}
        for c in items
    ]


@app.post('/api/campaigns', status_code=201)
def create_campaign(
    data: CampaignCreate, kt: KeitaroClient = Depends(get_client), db: Session = Depends(get_db)
):
    return services.create_campaign(kt, db, data)


@app.get('/api/campaigns/{campaign_id}')
def get_campaign(campaign_id: int, kt: KeitaroClient = Depends(get_client)):
    return services.campaign_view(kt, campaign_id)


@app.post('/api/campaigns/{campaign_id}/offers')
def add_offer(
    campaign_id: int,
    body: OfferAdd,
    kt: KeitaroClient = Depends(get_client),
    db: Session = Depends(get_db),
):
    return services.add_offer(kt, db, campaign_id, body.offer_id)


@app.delete('/api/campaigns/{campaign_id}/offers/{offer_id}')
def remove_offer(
    campaign_id: int,
    offer_id: int,
    kt: KeitaroClient = Depends(get_client),
    db: Session = Depends(get_db),
):
    return services.remove_offer(kt, db, campaign_id, offer_id)


@app.put('/api/campaigns/{campaign_id}/offers/shares')
def update_shares(
    campaign_id: int,
    body: SharesUpdate,
    kt: KeitaroClient = Depends(get_client),
    db: Session = Depends(get_db),
):
    return services.set_shares(kt, db, campaign_id, body.shares)


@app.post('/api/campaigns/{campaign_id}/offers/equalize')
def equalize(
    campaign_id: int, kt: KeitaroClient = Depends(get_client), db: Session = Depends(get_db)
):
    return services.equalize(kt, db, campaign_id)


@app.get('/api/created')
def created(db: Session = Depends(get_db)):
    rows = db.query(CampaignRecord).order_by(CampaignRecord.id.desc()).limit(100).all()
    return [
        {
            'keitaro_id': r.keitaro_id,
            'name': r.name,
            'geo': r.geo,
            'offer_id': r.offer_id,
            'created_at': r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
