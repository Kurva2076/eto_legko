from enum import Enum


class OfferChangeActionType(str, Enum):
    """Действия, который могут быть указаны в журнале добавления/удаления"""
    ADD = 'add'
    REMOVE = 'remove'
    SHARES = 'shares'
    EQUALIZE = 'equalize'
