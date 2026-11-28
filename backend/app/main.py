from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import services
from app.db import get_db
from app.errors import ServiceError
from app.keitaro import KeitaroClient, KeitaroError, get_client
from app.models import CampaignRecord
from app.schemas import CampaignCreate, OfferAdd, PinUpdate, SharesUpdate

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


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exception: ServiceError) -> JSONResponse:
    """
    Перехват ошибки ServiceError и последующее формирование ошибки.

    :param _: Запрос, вызвавший ошибку.
    :param exception: Ошибка.
    :return: Ответ с информацией о полученной ошибке.
    """
    return JSONResponse(status_code=exception.status, content={'detail': exception.detail})


@app.get('/api/health')
def health() -> JSONResponse:
    """Проверка доступности сервера"""
    return JSONResponse(status_code=200, content={'ok': True})


@app.get('/api/meta')
def meta(keitaro_client: KeitaroClient = Depends(get_client)):
    return services.resolve_defaults(keitaro_client)


@app.get('/api/offers')
def offers(
    search: str = '',
    limit: int = Query(20, ge=1, le=100),
    keitaro_client: KeitaroClient = Depends(get_client),
    database: Session = Depends(get_db),
):
    """Поиск офферов по каталогу в БД (каталог один раз загружается из Keitaro, если он пуст)"""
    return services.search_offers(keitaro_client, database, search, limit)


@app.get('/api/campaigns')
def list_campaigns(database: Session = Depends(get_db)):
    """Список кампаний из нашей БД"""
    return services.list_campaigns(database)


@app.post('/api/campaigns/sync')
def sync_campaigns(keitaro_client: KeitaroClient = Depends(get_client), database: Session = Depends(get_db)):
    """Загрузка списка кампаний из Keitaro в БД"""
    return services.sync_campaigns(keitaro_client, database)


@app.post('/api/campaigns', status_code=201)
def create_campaign(
    data: CampaignCreate,
    keitaro_client: KeitaroClient = Depends(get_client),
    database: Session = Depends(get_db),
):
    return services.create_campaign(keitaro_client, database, data)


@app.get('/api/campaigns/{campaign_id}')
def get_campaign(campaign_id: int, database: Session = Depends(get_db)):
    """Кампания с потоками и офферами, только из БД"""
    return services.campaign_view(database, campaign_id)


@app.post('/api/campaigns/{campaign_id}/pull')
def pull_campaign(
    campaign_id: int,
    keitaro_client: KeitaroClient = Depends(get_client),
    database: Session = Depends(get_db),
):
    """Стянуть кампанию, потоки и офферы из Keitaro в БД"""
    return services.pull_campaign(keitaro_client, database, campaign_id)


@app.post('/api/campaigns/{campaign_id}/push')
def push_campaign(
    campaign_id: int,
    keitaro_client: KeitaroClient = Depends(get_client),
    database: Session = Depends(get_db),
):
    """Отправить в Keitaro изменения всех потоков кампании"""
    return services.push_campaign(keitaro_client, database, campaign_id)


@app.post('/api/streams/{stream_id}/push')
def push_stream(
    stream_id: int,
    keitaro_client: KeitaroClient = Depends(get_client),
    database: Session = Depends(get_db),
):
    """Отправить в Keitaro изменения одного потока"""
    return services.push_stream(keitaro_client, database, stream_id)


@app.post('/api/streams/{stream_id}/cancel')
def cancel_stream_changes(stream_id: int, database: Session = Depends(get_db)):
    """Отменить незафиксированные изменения потока"""
    return services.cancel_stream_changes(database, stream_id)


@app.post('/api/streams/{stream_id}/offers')
def add_offer(stream_id: int, body: OfferAdd, database: Session = Depends(get_db)):
    """Добавить оффер в поток (только в БД)"""
    return services.add_offer(database, stream_id, body.offer_id)


@app.put('/api/streams/{stream_id}/offers/shares')
def update_shares(stream_id: int, body: SharesUpdate, database: Session = Depends(get_db)):
    """Задать доли офферов потока (только в БД)"""
    return services.set_shares(database, stream_id, body.shares)


@app.post('/api/streams/{stream_id}/offers/equalize')
def equalize(stream_id: int, database: Session = Depends(get_db)):
    """Распределить доли незакреплённых офферов поровну (только в БД)"""
    return services.equalize(database, stream_id)


@app.delete('/api/streams/{stream_id}/offers/{offer_id}')
def remove_offer(stream_id: int, offer_id: int, database: Session = Depends(get_db)):
    """Пометить оффер как REMOVED (только в БД)"""
    return services.remove_offer(database, stream_id, offer_id)


@app.post('/api/streams/{stream_id}/offers/{offer_id}/restore')
def restore_offer(stream_id: int, offer_id: int, database: Session = Depends(get_db)):
    """Восстановить оффер со статусом REMOVED (только в БД)"""
    return services.restore_offer(database, stream_id, offer_id)


@app.delete('/api/streams/{stream_id}/offers/{offer_id}/purge')
def purge_offer(stream_id: int, offer_id: int, database: Session = Depends(get_db)):
    """Полностью удалить оффер со статусом REMOVED из БД"""
    return services.purge_offer(database, stream_id, offer_id)


@app.put('/api/streams/{stream_id}/offers/{offer_id}/pin')
def pin_offer(stream_id: int, offer_id: int, body: PinUpdate, database: Session = Depends(get_db)):
    """Закрепить или открепить долю оффера"""
    return services.set_pinned(database, stream_id, offer_id, body.pinned)


@app.get('/api/created')
def created(database: Session = Depends(get_db)):
    rows = database.query(CampaignRecord).order_by(CampaignRecord.id.desc()).limit(100).all()
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
