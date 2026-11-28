from collections.abc import Sequence
from typing import Any

from app.enums import OfferChangeKind, OfferStatus

LANDINGS_SCHEMA = 'landings'
TOTAL_SHARE = 100


def active_offers(offers: Sequence[Any]) -> list[Any]:
    """
    Отбирает офферы, которые сейчас участвуют в потоке (не помечены как REMOVED).

    :param offers: Все офферы потока, включая удалённые.
    :return: Список активных офферов в исходном порядке.
    """
    return [offer for offer in offers if offer.status == OfferStatus.ACTIVE]


def total_share(offers: Sequence[Any]) -> int:
    """
    Считает сумму долей активных офферов.

    :param offers: Все офферы потока, включая удалённые.
    :return: Сумма долей активных офферов.
    """
    return sum(offer.share for offer in active_offers(offers))


def recalculate_shares(offers: Sequence[Any]) -> None:
    """
    Пересчитывает доли активных офферов: закреплённые офферы остаются как есть, а остаток
    до 100% делится поровну между незакреплёнными. Остаток от деления раздаётся первым
    офферам (три незакреплённых оффера без пинов дают 34, 33 и 33). Если незакреплённых
    офферов нет, ничего не меняется.

    :param offers: Все офферы потока, включая удалённые.
    """
    active = active_offers(offers)
    free_offers = [offer for offer in active if not offer.pinned]
    if not free_offers:
        return
    pinned_total = sum(offer.share for offer in active if offer.pinned)
    base, remainder = divmod(max(TOTAL_SHARE - pinned_total, 0), len(free_offers))
    for index, offer in enumerate(free_offers):
        offer.share = base + (1 if index < remainder else 0)


def offers_payload(offers: Sequence[Any]) -> list[dict]:
    """
    Формирует состав офферов потока в формате Keitaro. Удалённые (REMOVED) офферы не включаются:
    именно так они пропадают из потока в Keitaro при отправке изменений.

    :param offers: Все офферы потока, включая удалённые.
    :return: Список словарей с полями offer_id, share и state.
    """
    return [
        {'offer_id': offer.offer_id, 'share': offer.share, 'state': offer.keitaro_state}
        for offer in active_offers(offers)
    ]


def _sorted_by_offer(payload: Sequence[dict]) -> list[dict]:
    """Сортирует состав офферов по ID оффера, чтобы порядок не влиял на сравнение"""
    return sorted(payload, key=lambda item: item['offer_id'])


def has_unsynced_changes(
    offers: Sequence[Any],
    schema: str | None,
    synced_offers: Sequence[dict],
    synced_schema: str | None,
) -> bool:
    """
    Проверяет, отличается ли локальное состояние потока от последнего состояния в Keitaro.

    :param offers: Все офферы потока, включая удалённые.
    :param schema: Текущая схема потока в нашей БД.
    :param synced_offers: Состав офферов потока на момент последней синхронизации с Keitaro.
    :param synced_schema: Схема потока на момент последней синхронизации с Keitaro.
    :return: True, если есть изменения, не отправленные в Keitaro.
    """
    if schema != synced_schema:
        return True
    return _sorted_by_offer(offers_payload(offers)) != _sorted_by_offer(synced_offers)


def offer_change_kind(offer: Any, synced_offers_by_id: dict[int, dict]) -> OfferChangeKind | None:
    """
    Определяет, какое незафиксированное изменение есть у оффера.

    :param offer: Оффер потока в нашей БД.
    :param synced_offers_by_id: Состав офферов в Keitaro на момент последней синхронизации
        в виде словаря «ID оффера — данные оффера».
    :return: Вид изменения или None, если оффер совпадает с состоянием в Keitaro
        (или это удалённый оффер, которого в Keitaro и так нет).
    """
    synced_offer = synced_offers_by_id.get(offer.offer_id)
    if offer.status == OfferStatus.REMOVED:
        return OfferChangeKind.REMOVED if synced_offer is not None else None
    if synced_offer is None:
        return OfferChangeKind.ADDED
    if synced_offer['share'] != offer.share:
        return OfferChangeKind.SHARE
    return None
