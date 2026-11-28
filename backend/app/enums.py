from enum import Enum


class OfferChangeActionType(str, Enum):
    """Действия, которые могут быть указаны в журнале изменений офферов"""
    ADD = 'add'
    REMOVE = 'remove'
    RESTORE = 'restore'
    PURGE = 'purge'
    PIN = 'pin'
    UNPIN = 'unpin'
    SHARES = 'shares'
    EQUALIZE = 'equalize'
    PUSH = 'push'
    CANCEL = 'cancel'


class OfferStatus(str, Enum):
    """Статус оффера в потоке в нашей БД"""
    ACTIVE = 'active'
    REMOVED = 'removed'


class OfferChangeKind(str, Enum):
    """Вид незафиксированного (не отправленного в Keitaro) изменения оффера"""
    ADDED = 'added'
    SHARE = 'share'
    REMOVED = 'removed'
