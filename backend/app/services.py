from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import OfferChangeActionType, OfferStatus
from app.errors import ServiceError
from app.keitaro import KeitaroClient, KeitaroError
from app.models import Campaign, CampaignRecord, Offer, OfferChange, Stream, StreamOffer
from app.schemas import CampaignCreate, ShareItem
from app.stream_logic import (
    LANDINGS_SCHEMA,
    TOTAL_SHARE,
    active_offers,
    has_unsynced_changes,
    offer_change_kind,
    offers_payload,
    recalculate_shares,
    total_share,
)
from app.utils import now, to_utc_iso

GOOGLE_URL = 'https://google.com'
CAMPAIGNS_PAGE_SIZE = 100
CAMPAIGNS_MAX_OFFSET = 5000


def _pick(items: list[dict], wanted_id: int, label: str) -> dict:
    """
    Выбирает элемент справочника по ID, а если такого нет — первый элемент списка.

    :param items: Список элементов справочника, полученный из Keitaro.
    :param wanted_id: ID элемента, который нужно найти.
    :param label: Название справочника для текста ошибки (например, «домены»).
    :return: Найденный элемент справочника или первый элемент списка, если нужного ID нет.
    :raises: KeitaroError: Справочник пуст, выбрать нечего.
    """
    for item in items:
        if int(item['id']) == wanted_id:
            return item
    if items:
        return items[0]
    raise KeitaroError(409, f'В Keitaro нет ни одного значения справочника: {label}')


def resolve_defaults(keitaro: KeitaroClient) -> dict:
    """
    Определяет домен, группу и источник трафика, которые ставятся новой кампании.

    :param keitaro: Клиент Keitaro Admin API.
    :return: Словарь с ключами domain, group и source, в каждом из которых лежат id и name.
    """
    domain = _pick(keitaro.domains(), settings.default_domain_id, 'домены')
    group = _pick(keitaro.groups(), settings.default_group_id, 'группы')
    source = _pick(keitaro.sources(), settings.default_source_id, 'источники')
    return {
        'domain': {'id': domain['id'], 'name': domain.get('name')},
        'group': {'id': group['id'], 'name': group.get('name')},
        'source': {'id': source['id'], 'name': source.get('name')},
    }


def _sync_offers_catalog(keitaro: KeitaroClient, database: Session) -> None:
    """
    Обновляет каталог офферов в БД данными из Keitaro (новые добавляются, названия обновляются).
    Изменения только добавляются в сессию (flush), коммит делает вызывающий код.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД.
    """
    existing = {offer.id: offer for offer in database.scalars(select(Offer))}
    for remote_offer in keitaro.offers(time_to_leave=0):
        offer_id = int(remote_offer['id'])
        name = str(remote_offer.get('name', ''))
        offer = existing.get(offer_id)
        if offer is None:
            database.add(Offer(id=offer_id, name=name))
        else:
            offer.name = name
    database.flush()


def search_offers(keitaro: KeitaroClient, database: Session, search: str, limit: int = 20) -> list[dict]:
    """
    Ищет офферы в каталоге нашей БД по подстроке в названии или по точному совпадению ID
    (для автокомплита). Если каталог ещё пуст, он один раз загружается из Keitaro.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД.
    :param search: Поисковая строка. Если она пустая, возвращаются первые офферы каталога.
    :param limit: Максимальное количество офферов в результате.
    :return: Список словарей с полями id и name.
    """
    catalog = database.scalars(select(Offer).order_by(Offer.id)).all()
    if not catalog:
        _sync_offers_catalog(keitaro, database)
        database.commit()
        catalog = database.scalars(select(Offer).order_by(Offer.id)).all()

    search = (search or '').strip().lower()
    result = []
    for offer in catalog:
        if not search or search in offer.name.lower() or search == str(offer.id):
            result.append({'id': offer.id, 'name': offer.name})
            if len(result) >= limit:
                break
    return result


def equal_shares(offer_ids: list[int]) -> list[dict]:
    """
    Равномерно распределяет доли трафика между офферами так, чтобы сумма была ровно 100.
    Остаток от деления раздаётся первым офферам (три оффера дают 34, 33 и 33).

    :param offer_ids: Список ID офферов.
    :return: Список офферов в формате потока Keitaro (offer_id, share, state='active').
        Для пустого списка возвращается пустой список.
    """
    if not offer_ids:
        return []
    base, rem = divmod(100, len(offer_ids))
    return [
        {'offer_id': oid, 'share': base + (1 if i < rem else 0), 'state': 'active'}
        for i, oid in enumerate(offer_ids)
    ]


def _upsert_campaign(
    database: Session,
    remote_campaign: dict,
    existing: dict[int, Campaign] | None = None,
) -> Campaign:
    """
    Создаёт или обновляет кампанию в БД по данным из Keitaro.

    :param database: Сессия БД.
    :param remote_campaign: Данные кампании из Keitaro.
    :param existing: Уже загруженные кампании «Keitaro ID — кампания», чтобы не делать запрос
        на каждую кампанию. Если не передано, кампания ищется запросом в БД.
    :return: Кампания из БД (новая добавляется в сессию, но не коммитится).
    """
    keitaro_id = int(remote_campaign['id'])
    if existing is not None:
        campaign = existing.get(keitaro_id)
    else:
        campaign = database.scalar(select(Campaign).where(Campaign.keitaro_id == keitaro_id))
    if campaign is None:
        campaign = Campaign(keitaro_id=keitaro_id, name='')
        database.add(campaign)
        if existing is not None:
            existing[keitaro_id] = campaign
    campaign.name = str(remote_campaign.get('name') or campaign.name or f'#{keitaro_id}')
    campaign.alias = remote_campaign.get('alias') or campaign.alias
    campaign.state = remote_campaign.get('state') or campaign.state
    return campaign


def list_campaigns(database: Session) -> list[dict]:
    """
    Возвращает список кампаний из нашей БД, новые сверху.

    :param database: Сессия БД.
    :return: Список словарей с полями id (ID в Keitaro), name, state, alias и synced_at.
    """
    campaigns = database.scalars(select(Campaign).order_by(Campaign.keitaro_id.desc()))
    return [
        {
            'id': campaign.keitaro_id,
            'name': campaign.name,
            'state': campaign.state,
            'alias': campaign.alias,
            'synced_at': to_utc_iso(campaign.synced_at),
        }
        for campaign in campaigns
    ]


def sync_campaigns(keitaro: KeitaroClient, database: Session) -> list[dict]:
    """
    Загружает список кампаний из Keitaro в нашу БД (потоки при этом не затрагиваются).

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД.
    :return: Обновлённый список кампаний из БД (см. list_campaigns).
    """
    remote_campaigns: list[dict] = []
    seen_ids: set[int] = set()
    offset = 0
    while offset < CAMPAIGNS_MAX_OFFSET:
        page = keitaro.get('/campaigns', offset=offset, limit=CAMPAIGNS_PAGE_SIZE) or []
        new_items = [item for item in page if int(item['id']) not in seen_ids]
        if not new_items:
            break
        seen_ids.update(int(item['id']) for item in new_items)
        remote_campaigns.extend(new_items)
        if len(page) < CAMPAIGNS_PAGE_SIZE:
            break
        offset += CAMPAIGNS_PAGE_SIZE

    existing = {campaign.keitaro_id: campaign for campaign in database.scalars(select(Campaign))}
    for remote_campaign in remote_campaigns:
        _upsert_campaign(database, remote_campaign, existing)
    database.commit()
    return list_campaigns(database)


def create_campaign(keitaro: KeitaroClient, database: Session, data: CampaignCreate) -> dict:
    """
    Создаёт кампанию с двумя потоками: первый отправляет выбранные страны на Google,
    второй ведёт на выбранный оффер. Домен, группа и источник берутся из справочников.
    Если потоки создать не удалось, кампания удаляется из Keitaro. Созданная кампания
    сохраняется в БД вместе с потоками, чтобы её можно было сразу открыть в редакторе.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД, в которую записывается созданная кампания.
    :param data: Название кампании, гео и ID оффера.
    :return: Словарь с данными созданной кампании: id, name, geo, offer, domain, group,
        source и admin_url (ссылка на кампанию в админке Keitaro).
    :raises: KeitaroError: Оффер не найден, не удалось создать кампанию или один из потоков.
    """
    offer = keitaro.offer(data.offer_id)
    defaults = resolve_defaults(keitaro)

    campaign = keitaro.post(
        '/campaigns',
        {
            'name': data.name,
            'type': 'position',
            'domain_id': defaults['domain']['id'],
            'group_id': defaults['group']['id'],
            'traffic_source_id': defaults['source']['id'],
            'state': 'active',
        },
    )
    campaign_id = campaign['id']
    try:
        keitaro.post(
            '/streams',
            {
                'campaign_id': campaign_id,
                'name': f'Geo {data.geo}',
                'type': 'regular',
                'schema': 'redirect',
                'position': 1,
                'action_type': 'http',
                'action_payload': GOOGLE_URL,
                'filters': [{'name': 'country', 'mode': 'accept', 'payload': data.geo.split(',')}],
            },
        )
        keitaro.post(
            '/streams',
            {
                'campaign_id': campaign_id,
                'name': 'Офферы',
                'type': 'default',
                'schema': LANDINGS_SCHEMA,
                'position': 2,
                'offers': equal_shares([data.offer_id]),
            },
        )
    except KeitaroError:
        try:
            keitaro.delete(f'/campaigns/{campaign_id}')
        except KeitaroError:
            pass
        raise

    database.add(CampaignRecord(keitaro_id=campaign_id, name=data.name, geo=data.geo, offer_id=data.offer_id))
    _upsert_campaign(database, {**campaign, 'name': campaign.get('name') or data.name})
    database.commit()
    try:
        pull_campaign(keitaro, database, campaign_id)
    except KeitaroError:
        database.rollback()
    return {
        'id': campaign_id,
        'name': data.name,
        'geo': data.geo.split(','),
        'offer': {'id': offer.get('id', data.offer_id), 'name': offer.get('name')},
        **defaults,
        'admin_url': f'{settings.admin_base}/admin/#!/campaign.editor/{campaign_id}',
    }


def _get_campaign(database: Session, campaign_id: int) -> Campaign:
    """
    Получает кампанию из БД по её ID в Keitaro.

    :param database: Сессия БД.
    :param campaign_id: ID кампании в Keitaro.
    :return: Кампания из БД.
    :raises: ServiceError: Кампании нет в БД.
    """
    campaign = database.scalar(select(Campaign).where(Campaign.keitaro_id == campaign_id))
    if campaign is None:
        raise ServiceError(404, 'Кампании нет в БД. Нажмите «Обновить список» и выберите кампанию заново')
    return campaign


def _get_stream(database: Session, stream_id: int) -> Stream:
    """
    Получает поток из БД по его ID в Keitaro.

    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :return: Поток из БД.
    :raises: ServiceError: Потока нет в БД.
    """
    stream = database.scalar(select(Stream).where(Stream.keitaro_id == stream_id))
    if stream is None:
        raise ServiceError(404, 'Потока нет в БД. Стяните потоки кампании с Keitaro')
    return stream


def _get_offer_row(stream: Stream, offer_id: int) -> StreamOffer:
    """
    Находит оффер в потоке (в том числе помеченный как REMOVED).

    :param stream: Поток из БД.
    :param offer_id: ID оффера в Keitaro.
    :return: Оффер потока.
    :raises: ServiceError: Оффера нет в потоке.
    """
    for row in stream.offers:
        if row.offer_id == offer_id:
            return row
    raise ServiceError(404, 'Такого оффера нет в потоке')


def _stream_view(stream: Stream) -> dict:
    """
    Собирает данные потока для редактора. Активные офферы идут первыми, удалённые (REMOVED) — в конце.

    :param stream: Поток из БД.
    :return: Словарь с полями потока, его офферами, суммой долей и признаком незафиксированных изменений.
    """
    synced_by_id = {item['offer_id']: item for item in stream.synced_offers or []}
    offers = sorted(stream.offers, key=lambda offer: offer.status == OfferStatus.REMOVED)
    offer_views = []
    for offer in offers:
        change = offer_change_kind(offer, synced_by_id)
        offer_views.append(
            {
                'offer_id': offer.offer_id,
                'name': offer.name,
                'share': offer.share,
                'pinned': offer.pinned,
                'status': offer.status.value,
                'change': change.value if change else None,
            }
        )
    return {
        'id': stream.keitaro_id,
        'name': stream.name,
        'type': stream.type,
        'schema': stream.schema,
        'state': stream.state,
        'position': stream.position,
        'action_type': stream.action_type,
        'action_payload': stream.action_payload,
        'filters': stream.filters or [],
        'has_offers': bool(stream.offers),
        'has_changes': has_unsynced_changes(
            stream.offers, stream.schema, stream.synced_offers or [], stream.synced_schema
        ),
        'total_share': total_share(stream.offers),
        'offers': offer_views,
    }


def campaign_view(database: Session, campaign_id: int) -> dict:
    """
    Собирает данные кампании для редактора только из БД (в Keitaro запросов нет).
    Сначала идут потоки с офферами, потом потоки без них.

    :param database: Сессия БД.
    :param campaign_id: ID кампании в Keitaro.
    :return: Словарь с полями кампании, временем последней синхронизации (synced_at),
        признаком незафиксированных изменений (has_changes) и списком потоков (streams).
    """
    campaign = _get_campaign(database, campaign_id)
    streams = sorted(
        campaign.streams,
        key=lambda stream: (0 if stream.offers else 1, stream.position, stream.id),
    )
    stream_views = [_stream_view(stream) for stream in streams]
    return {
        'id': campaign.keitaro_id,
        'name': campaign.name,
        'state': campaign.state,
        'alias': campaign.alias,
        'admin_url': f'{settings.admin_base}/admin/#!/campaign.editor/{campaign.keitaro_id}',
        'synced_at': to_utc_iso(campaign.synced_at),
        'has_changes': any(view['has_changes'] for view in stream_views),
        'streams': stream_views,
    }


def _load_stream_details(keitaro: KeitaroClient, remote_stream: dict) -> dict:
    """
    Возвращает поток вместе с офферами и фильтрами. Если в элементе списка потоков кампании
    их нет, поток дозапрашивается отдельным запросом.

    :param keitaro: Клиент Keitaro Admin API.
    :param remote_stream: Поток из списка потоков кампании.
    :return: Поток с полями offers и filters.
    """
    if 'offers' in remote_stream and 'filters' in remote_stream:
        return remote_stream
    return keitaro.get(f'/streams/{remote_stream["id"]}') or remote_stream


def _replace_stream_offers(stream: Stream, remote_offers: list[dict], catalog: dict[int, str]) -> None:
    """
    Приводит офферы потока в БД к состоянию в Keitaro:
     - локальные незафиксированные изменения перезаписываются;
     - удалённые локально (REMOVED) офферы, которых нет в Keitaro, сохраняются в БД, чтобы их можно было восстановить;
     - удалённые офферы через Keitaro помечаются как REMOVED, но не удаляются.

    :param stream: Поток из БД.
    :param remote_offers: Офферы потока из Keitaro.
    :param catalog: Каталог офферов «ID оффера — название».
    """
    remote_by_id = {
        int(remote_offer['offer_id']): {
            'offer_id': int(remote_offer['offer_id']),
            'share': int(remote_offer.get('share') or 0),
            'state': remote_offer.get('state') or 'active',
        }
        for remote_offer in remote_offers
        if remote_offer.get('offer_id') is not None
    }

    for row in stream.offers:
        remote_offer = remote_by_id.get(row.offer_id)
        if remote_offer is not None:
            row.status = OfferStatus.ACTIVE
            row.share = remote_offer['share']
            row.keitaro_state = remote_offer['state']
            row.name = catalog.get(row.offer_id, row.name)
        elif row.status == OfferStatus.ACTIVE:
            row.status = OfferStatus.REMOVED

    existing_ids = {row.offer_id for row in stream.offers}
    for offer_id, remote_offer in remote_by_id.items():
        if offer_id not in existing_ids:
            stream.offers.append(
                StreamOffer(
                    offer_id=offer_id,
                    name=catalog.get(offer_id, f'#{offer_id}'),
                    share=remote_offer['share'],
                    pinned=False,
                    keitaro_state=remote_offer['state'],
                    status=OfferStatus.ACTIVE,
                )
            )
    stream.synced_offers = list(remote_by_id.values())


def pull_campaign(keitaro: KeitaroClient, database: Session, campaign_id: int) -> dict:
    """
    Стягивает кампанию, её потоки и офферы из Keitaro в БД. Это единственное место, где редактор
    читает потоки из Keitaro. Локальные незафиксированные изменения потоков перезаписываются.
    Все запросы к Keitaro выполняются до записи в БД, поэтому при ошибке БД не меняется.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД.
    :param campaign_id: ID кампании в Keitaro.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    """
    remote_campaign = keitaro.get(f'/campaigns/{campaign_id}')
    remote_streams = [
        _load_stream_details(keitaro, remote_stream)
        for remote_stream in (keitaro.get(f'/campaigns/{campaign_id}/streams') or [])
    ]
    _sync_offers_catalog(keitaro, database)
    catalog = {offer.id: offer.name for offer in database.scalars(select(Offer))}

    campaign = _upsert_campaign(database, remote_campaign)
    campaign.synced_at = now()

    local_streams = {stream.keitaro_id: stream for stream in campaign.streams}
    remote_ids: set[int] = set()
    for index, remote_stream in enumerate(remote_streams, start=1):
        stream_id = int(remote_stream['id'])
        remote_ids.add(stream_id)
        stream = local_streams.get(stream_id)
        if stream is None:
            stream = Stream(keitaro_id=stream_id, name='')
            campaign.streams.append(stream)
        action_payload = remote_stream.get('action_payload')
        stream.name = str(remote_stream.get('name') or f'#{stream_id}')
        stream.type = remote_stream.get('type')
        stream.schema = remote_stream.get('schema')
        stream.synced_schema = stream.schema
        stream.state = remote_stream.get('state')
        stream.position = int(remote_stream.get('position') or index)
        stream.action_type = remote_stream.get('action_type')
        stream.action_payload = None if action_payload is None else str(action_payload)
        stream.filters = remote_stream.get('filters') or []
        _replace_stream_offers(stream, remote_stream.get('offers') or [], catalog)

    for stream_id, stream in local_streams.items():
        if stream_id not in remote_ids:
            campaign.streams.remove(stream)

    database.commit()
    return campaign_view(database, campaign_id)


def _validate_stream_shares(stream: Stream) -> None:
    """
    Проверяет, что сумма долей активных офферов потока равна 100 (или офферов в потоке нет).

    :param stream: Поток из БД.
    :raises: ServiceError: Сумма долей не равна 100.
    """
    total = total_share(stream.offers)
    if active_offers(stream.offers) and total != TOTAL_SHARE:
        raise ServiceError(
            422,
            f'В потоке «{stream.name}» сумма долей равна {total}%, а должна быть {TOTAL_SHARE}%',
        )


def _push_stream_changes(keitaro: KeitaroClient, database: Session, stream: Stream) -> None:
    """
    Отправляет изменения одного потока в Keitaro и после успеха считает их зафиксированными.
    Состав офферов потока в Keitaro заменяется целиком (удалённые офферы в него не попадают).
    Если у потока нет изменений, ничего не делает.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД.
    :param stream: Поток из БД.
    """
    if not has_unsynced_changes(stream.offers, stream.schema, stream.synced_offers or [], stream.synced_schema):
        return
    _validate_stream_shares(stream)

    offers = offers_payload(stream.offers)
    body: dict = {'offers': offers}
    if stream.schema != stream.synced_schema:
        body['schema'] = stream.schema
    keitaro.put(f'/streams/{stream.keitaro_id}', body)

    stream.synced_schema = stream.schema
    stream.synced_offers = offers
    database.add(
        OfferChange(
            campaign_id=stream.campaign.keitaro_id,
            stream_id=stream.keitaro_id,
            offer_id=0,
            action=OfferChangeActionType.PUSH,
        )
    )
    database.commit()


def push_stream(keitaro: KeitaroClient, database: Session, stream_id: int) -> dict:
    """
    Отправляет в Keitaro локальные изменения одного потока.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    """
    stream = _get_stream(database, stream_id)
    campaign_id = stream.campaign.keitaro_id
    _push_stream_changes(keitaro, database, stream)
    return campaign_view(database, campaign_id)


def push_campaign(keitaro: KeitaroClient, database: Session, campaign_id: int) -> dict:
    """
    Отправляет в Keitaro локальные изменения всех потоков кампании. Сначала проверяются доли во всех
    изменённых потоках, и только потом начинается отправка, поэтому из-за ошибки в долях не отправится ничего.
    Если Keitaro вернёт ошибку посреди отправки, уже отправленные потоки остаются зафиксированными.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД.
    :param campaign_id: ID кампании в Keitaro.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    """
    campaign = _get_campaign(database, campaign_id)
    changed_streams = [
        stream
        for stream in sorted(campaign.streams, key=lambda item: (item.position, item.id))
        if has_unsynced_changes(stream.offers, stream.schema, stream.synced_offers or [], stream.synced_schema)
    ]
    for stream in changed_streams:
        _validate_stream_shares(stream)
    for stream in changed_streams:
        _push_stream_changes(keitaro, database, stream)
    return campaign_view(database, campaign_id)


def _commit_change(
    database: Session,
    stream: Stream,
    offer_id: int,
    action: OfferChangeActionType,
) -> dict:
    """
    Записывает действие в журнал, коммитит изменения и возвращает обновлённую кампанию.

    :param database: Сессия БД.
    :param stream: Изменённый поток.
    :param offer_id: ID оффера, с которым выполнено действие (0, если действие относится ко всему потоку).
    :param action: Выполненное действие.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    """
    campaign_id = stream.campaign.keitaro_id
    database.add(
        OfferChange(campaign_id=campaign_id, stream_id=stream.keitaro_id, offer_id=offer_id, action=action)
    )
    database.commit()
    return campaign_view(database, campaign_id)


def add_offer(database: Session, stream_id: int, offer_id: int) -> dict:
    """
    Добавляет оффер в поток (только в БД) и пересчитывает доли незакреплённых офферов. Если оффер
    уже есть в потоке со статусом REMOVED, он восстанавливается. Если поток не был потоком
    с офферами (схема не landings), он становится таким при добавлении оффера.

    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :param offer_id: ID добавляемого оффера.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    :raises:
        ServiceError: Потока нет в БД, оффер уже есть в потоке или оффера нет в каталоге.
    """
    stream = _get_stream(database, stream_id)
    row = next((item for item in stream.offers if item.offer_id == offer_id), None)
    if row is not None and row.status == OfferStatus.ACTIVE:
        raise ServiceError(409, 'Оффер уже есть в потоке')
    if row is None:
        catalog_offer = database.get(Offer, offer_id)
        if catalog_offer is None:
            raise ServiceError(404, 'Оффера нет в каталоге. Стяните потоки с Keitaro, чтобы обновить каталог')
        row = StreamOffer(offer_id=offer_id, name=catalog_offer.name, share=0, keitaro_state='active')
        stream.offers.append(row)
    row.status = OfferStatus.ACTIVE
    row.pinned = False
    if stream.schema != LANDINGS_SCHEMA:
        stream.schema = LANDINGS_SCHEMA
    recalculate_shares(stream.offers)
    return _commit_change(database, stream, offer_id, OfferChangeActionType.ADD)


def remove_offer(database: Session, stream_id: int, offer_id: int) -> dict:
    """
    Помечает оффер потока как REMOVED (из БД он не стирается), снимает с него закрепление
    и пересчитывает доли незакреплённых офферов.

    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :param offer_id: ID оффера.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    :raises:
        ServiceError: Потока или оффера нет в БД, либо оффер уже помечен как REMOVED.
    """
    stream = _get_stream(database, stream_id)
    row = _get_offer_row(stream, offer_id)
    if row.status == OfferStatus.REMOVED:
        raise ServiceError(409, 'Оффер уже удалён из потока')
    row.status = OfferStatus.REMOVED
    row.pinned = False
    recalculate_shares(stream.offers)
    return _commit_change(database, stream, offer_id, OfferChangeActionType.REMOVE)


def restore_offer(database: Session, stream_id: int, offer_id: int) -> dict:
    """
    Восстанавливает оффер со статусом REMOVED и пересчитывает доли незакреплённых офферов.

    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :param offer_id: ID оффера.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    :raises:
        ServiceError: Потока или оффера нет в БД, либо оффер не помечен как REMOVED.
    """
    stream = _get_stream(database, stream_id)
    row = _get_offer_row(stream, offer_id)
    if row.status != OfferStatus.REMOVED:
        raise ServiceError(409, 'Оффер не был удалён из потока')
    row.status = OfferStatus.ACTIVE
    row.pinned = False
    recalculate_shares(stream.offers)
    return _commit_change(database, stream, offer_id, OfferChangeActionType.RESTORE)


def purge_offer(database: Session, stream_id: int, offer_id: int) -> dict:
    """
    Окончательно удаляет из БД оффер со статусом REMOVED. Если такой оффер ещё присутствует в Keitaro,
    его удаление из потока остаётся незафиксированным изменением (его можно отправить или отменить).

    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :param offer_id: ID оффера.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    :raises:
        ServiceError: Потока или оффера нет в БД, либо оффер не помечен как REMOVED.
    """
    stream = _get_stream(database, stream_id)
    row = _get_offer_row(stream, offer_id)
    if row.status != OfferStatus.REMOVED:
        raise ServiceError(409, 'Полностью удалить можно только оффер со статусом REMOVED')
    stream.offers.remove(row)
    return _commit_change(database, stream, offer_id, OfferChangeActionType.PURGE)


def set_pinned(database: Session, stream_id: int, offer_id: int, pinned: bool) -> dict:
    """
    Закрепляет или открепляет текущую долю оффера. Закреплённые офферы не участвуют в пересчёте долей
    при добавлении, удалении и восстановлении офферов.

    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :param offer_id: ID оффера.
    :param pinned: True — закрепить долю, False — открепить.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    :raises:
        ServiceError: Потока или оффера нет в БД, либо оффер помечен как REMOVED.
    """
    stream = _get_stream(database, stream_id)
    row = _get_offer_row(stream, offer_id)
    if row.status != OfferStatus.ACTIVE:
        raise ServiceError(409, 'Нельзя закрепить долю удалённого оффера')
    row.pinned = pinned
    action = OfferChangeActionType.PIN if pinned else OfferChangeActionType.UNPIN
    return _commit_change(database, stream, offer_id, action)


def set_shares(database: Session, stream_id: int, items: list[ShareItem]) -> dict:
    """
    Задаёт доли офферов потока вручную (только в БД).

    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :param items: Список пар «оффер — доля» для всех активных офферов потока.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    :raises:
        ServiceError: Потока нет в БД, список офферов не совпадает с активными офферами потока
            или сумма долей не равна 100.
    """
    stream = _get_stream(database, stream_id)
    current = {row.offer_id: row for row in active_offers(stream.offers)}
    given = {item.offer_id: item.share for item in items}
    if set(given) != set(current):
        raise ServiceError(422, 'Список офферов не совпадает с текущим составом потока')
    if current and sum(given.values()) != TOTAL_SHARE:
        raise ServiceError(422, f'Сумма долей должна быть {TOTAL_SHARE}, сейчас {sum(given.values())}')
    for offer_id, row in current.items():
        row.share = given[offer_id]
    return _commit_change(database, stream, 0, OfferChangeActionType.SHARES)


def equalize(database: Session, stream_id: int) -> dict:
    """
    Распределяет доли между незакреплёнными офферами потока поровну (только в БД).
    Закреплённые офферы сохраняют свою долю. Если незакреплённых офферов нет, доли не меняются.

    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    """
    stream = _get_stream(database, stream_id)
    recalculate_shares(stream.offers)
    return _commit_change(database, stream, 0, OfferChangeActionType.EQUALIZE)


def cancel_stream_changes(database: Session, stream_id: int) -> dict:
    """
    Отменяет локальные незафиксированные изменения потока и возвращает его к состоянию
    на момент последней синхронизации с Keitaro: возвращает доли, восстанавливает офферы,
    убирает добавленные и возвращает схему потока. Офферы со статусом REMOVED, которых не было
    в Keitaro, остаются в БД. Закрепления долей сохраняются.

    :param database: Сессия БД.
    :param stream_id: ID потока в Keitaro.
    :return: Актуальные данные кампании из БД (см. campaign_view).
    """
    stream = _get_stream(database, stream_id)
    synced_by_id = {item['offer_id']: item for item in stream.synced_offers or []}
    catalog = {offer.id: offer.name for offer in database.scalars(select(Offer))}

    for row in list(stream.offers):
        synced_offer = synced_by_id.get(row.offer_id)
        if synced_offer is not None:
            row.status = OfferStatus.ACTIVE
            row.share = synced_offer['share']
            row.keitaro_state = synced_offer['state']
        elif row.status == OfferStatus.ACTIVE:
            stream.offers.remove(row)

    existing_ids = {row.offer_id for row in stream.offers}
    for offer_id, synced_offer in synced_by_id.items():
        if offer_id not in existing_ids:
            stream.offers.append(
                StreamOffer(
                    offer_id=offer_id,
                    name=catalog.get(offer_id, f'#{offer_id}'),
                    share=synced_offer['share'],
                    pinned=False,
                    keitaro_state=synced_offer['state'],
                    status=OfferStatus.ACTIVE,
                )
            )
    stream.schema = stream.synced_schema
    return _commit_change(database, stream, 0, OfferChangeActionType.CANCEL)
