from sqlalchemy.orm import Session

from app.config import settings
from app.keitaro import KeitaroClient, KeitaroError
from app.models import CampaignRecord, OfferChange
from app.schemas import CampaignCreate, ShareItem

GOOGLE_URL = 'https://google.com'


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


def search_offers(keitaro: KeitaroClient, search: str, limit: int = 20) -> list[dict]:
    """
    Ищет офферы по подстроке в названии или по точному совпадению ID (для автокомплита).

    :param keitaro: Клиент Keitaro Admin API.
    :param search: Поисковая строка. Если она пустая, возвращаются первые офферы списка.
    :param limit: Максимальное количество офферов в результате.
    :return: Список словарей с полями id и name.
    """
    search = (search or '').strip().lower()
    result = []
    for offer in keitaro.offers():
        name = str(offer.get('name', ''))
        if not search or search in name.lower() or search == str(offer.get('id')):
            result.append({'id': offer['id'], 'name': name})
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


def create_campaign(keitaro: KeitaroClient, database: Session, data: CampaignCreate) -> dict:
    """
    Создаёт кампанию с двумя потоками: первый отправляет выбранные страны на Google,
    второй ведёт на выбранный оффер. Домен, группа и источник берутся из справочников.
    Если потоки создать не удалось, кампания удаляется из Keitaro.

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
                'schema': 'landings',
                'position': 2,
                'offers': equal_shares([data.offer_id]),
            },
        )
    except KeitaroError:
        # не оставляем «полусобранную» кампанию
        try:
            keitaro.delete(f'/campaigns/{campaign_id}')
        except KeitaroError:
            pass
        raise

    database.add(CampaignRecord(keitaro_id=campaign_id, name=data.name, geo=data.geo, offer_id=data.offer_id))
    database.commit()
    return {
        'id': campaign_id,
        'name': data.name,
        'geo': data.geo.split(','),
        'offer': {'id': offer.get('id', data.offer_id), 'name': offer.get('name')},
        **defaults,
        'admin_url': f'{settings.admin_base}/admin/#!/campaign.editor/{campaign_id}',
    }


def _offer_names(keitaro: KeitaroClient) -> dict[int, str]:
    """
    Собирает соответствие ID оффера и его названия.

    :param keitaro: Клиент Keitaro Admin API.
    :return: Словарь, где ключ — ID оффера, значение — его название.
    """
    return {int(o['id']): str(o.get('name', '')) for o in keitaro.offers()}


def _streams(keitaro: KeitaroClient, campaign_id: int) -> list[dict]:
    """
    Получает потоки кампании в порядке их позиций.

    :param keitaro: Клиент Keitaro Admin API.
    :param campaign_id: ID кампании.
    :return: Список потоков кампании. Если потоков нет, возвращается пустой список.
    """
    return keitaro.get(f'/campaigns/{campaign_id}/streams') or []


def _offers_stream(streams: list[dict]) -> dict | None:
    """
    Находит поток с офферами. Сначала ищется поток типа default со схемой landings,
    затем любой поток со схемой landings.

    :param streams: Список потоков кампании.
    :return: Найденный поток или None, если в кампании нет потока с офферами.
    """
    for stream in streams:
        if stream.get('type') == 'default' and stream.get('schema') == 'landings':
            return stream
    for stream in streams:
        if stream.get('schema') == 'landings':
            return stream
    return None


def _stream_offers(stream: dict | None) -> list[dict]:
    """
    Возвращает офферы потока.

    :param stream: Поток кампании или None.
    :return: Копия списка офферов потока. Если потока нет, возвращается пустой список.
    """
    return list(stream.get('offers') or []) if stream else []


def campaign_view(keitaro: KeitaroClient, campaign_id: int) -> dict:
    """
    Собирает данные кампании для редактора: сама кампания, её потоки и офферы с названиями.

    :param keitaro: Клиент Keitaro Admin API.
    :param campaign_id: ID кампании.
    :return: Словарь с полями кампании (id, name, state, alias, admin_url), потоками (streams)
        и ID потока с офферами (offers_stream_id, None, если такого потока нет).
    """
    campaign = keitaro.get(f'/campaigns/{campaign_id}')
    streams = _streams(keitaro, campaign_id)
    names = _offer_names(keitaro)
    offers_stream = _offers_stream(streams)

    out_streams = []
    for stream in streams:
        out_streams.append(
            {
                'id': stream['id'],
                'name': stream.get('name'),
                'type': stream.get('type'),
                'schema': stream.get('schema'),
                'state': stream.get('state'),
                'action_type': stream.get('action_type'),
                'action_payload': stream.get('action_payload'),
                'filters': stream.get('filters') or [],
                'offers': [
                    {
                        'offer_id': int(offer['offer_id']),
                        'name': names.get(int(offer['offer_id']), f'#{offer["offer_id"]}'),
                        'share': offer.get('share', 0),
                        'state': offer.get('state', 'active'),
                    }
                    for offer in (stream.get('offers') or [])
                ],
            }
        )
    return {
        'id': campaign['id'],
        'name': campaign.get('name'),
        'state': campaign.get('state'),
        'alias': campaign.get('alias'),
        'admin_url': f'{settings.admin_base}/admin/#!/campaign.editor/{campaign["id"]}',
        'offers_stream_id': offers_stream['id'] if offers_stream else None,
        'streams': out_streams,
    }


def _save_offers(keitaro: KeitaroClient, campaign_id: int, stream: dict | None, offers: list[dict]) -> None:
    """
    Сохраняет состав офферов потока целиком. Если потока с офферами нет, он создаётся.

    :param keitaro: Клиент Keitaro Admin API.
    :param campaign_id: ID кампании.
    :param stream: Поток с офферами или None, если его нужно создать.
    :param offers: Новый состав офферов потока (offer_id, share, state).
    """
    if stream is None:
        keitaro.post(
            '/streams',
            {
                'campaign_id': campaign_id,
                'name': 'Офферы',
                'type': 'default',
                'schema': 'landings',
                'offers': offers,
            },
        )
    else:
        keitaro.put(f'/streams/{stream["id"]}', {'offers': offers})


def add_offer(keitaro: KeitaroClient, database: Session, campaign_id: int, offer_id: int) -> dict:
    """
    Добавляет оффер в кампанию и распределяет доли между всеми офферами поровну.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД, в которую записывается изменение.
    :param campaign_id: ID кампании.
    :param offer_id: ID добавляемого оффера.
    :return: Обновлённые данные кампании (см. campaign_view).
    :raises: KeitaroError: Оффер не существует или оффер уже есть в кампании.
    """
    keitaro.offer(offer_id)  # проверка существования
    stream = _offers_stream(_streams(keitaro, campaign_id))
    ids = [int(o['offer_id']) for o in _stream_offers(stream)]
    if offer_id in ids:
        raise KeitaroError(409, 'Оффер уже есть в кампании')
    _save_offers(keitaro, campaign_id, stream, equal_shares(ids + [offer_id]))
    database.add(OfferChange(campaign_id=campaign_id, offer_id=offer_id, action='add'))
    database.commit()
    return campaign_view(keitaro, campaign_id)


def remove_offer(keitaro: KeitaroClient, db: Session, campaign_id: int, offer_id: int) -> dict:
    """
    Удаляет оффер из кампании и распределяет доли между оставшимися офферами поровну.

    :param keitaro: Клиент Keitaro Admin API.
    :param db: Сессия БД, в которую записывается изменение.
    :param campaign_id: ID кампании.
    :param offer_id: ID удаляемого оффера.
    :return: Обновлённые данные кампании (см. campaign_view).
    :raises: KeitaroError: Оффера нет в кампании.
    """
    stream = _offers_stream(_streams(keitaro, campaign_id))
    ids = [int(offer['offer_id']) for offer in _stream_offers(stream)]
    if offer_id not in ids:
        raise KeitaroError(404, 'Такого оффера нет в кампании')
    rest = [i for i in ids if i != offer_id]
    _save_offers(keitaro, campaign_id, stream, equal_shares(rest))
    db.add(OfferChange(campaign_id=campaign_id, offer_id=offer_id, action='remove'))
    db.commit()
    return campaign_view(keitaro, campaign_id)


def set_shares(keitaro: KeitaroClient, database: Session, campaign_id: int, items: list[ShareItem]) -> dict:
    """
    Задаёт доли офферов вручную.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД, в которую записывается изменение.
    :param campaign_id: ID кампании.
    :param items: Список пар «оффер — доля» для всех офферов кампании.
    :return: Обновлённые данные кампании (см. campaign_view).
    :raises: KeitaroError: Список офферов не совпадает с текущим составом кампании или сумма долей не равна 100.
    """
    stream = _offers_stream(_streams(keitaro, campaign_id))
    current = {int(offer['offer_id']): offer for offer in _stream_offers(stream)}
    given = {item.offer_id: item.share for item in items}
    if set(given) != set(current):
        raise KeitaroError(422, 'Список офферов не совпадает с текущим составом кампании')
    if current and sum(given.values()) != 100:
        raise KeitaroError(422, f'Сумма долей должна быть 100, сейчас {sum(given.values())}')
    offers = [
        {'offer_id': offer_id, 'share': given[offer_id], 'state': current[offer_id].get('state', 'active')}
        for offer_id in current
    ]
    _save_offers(keitaro, campaign_id, stream, offers)
    database.add(OfferChange(campaign_id=campaign_id, offer_id=0, action='shares'))
    database.commit()
    return campaign_view(keitaro, campaign_id)


def equalize(keitaro: KeitaroClient, database: Session, campaign_id: int) -> dict:
    """
    Распределяет доли между офферами кампании поровну. Если офферов нет, ничего не меняет.

    :param keitaro: Клиент Keitaro Admin API.
    :param database: Сессия БД (в этой функции не используется).
    :param campaign_id: ID кампании.
    :return: Актуальные данные кампании (см. campaign_view).
    """
    stream = _offers_stream(_streams(keitaro, campaign_id))
    ids = [int(offer['offer_id']) for offer in _stream_offers(stream)]
    if stream is not None and ids:
        _save_offers(keitaro, campaign_id, stream, equal_shares(ids))
    database.add(OfferChange(campaign_id=campaign_id, offer_id=0, action='equalize'))
    database.commit()
    return campaign_view(keitaro, campaign_id)
