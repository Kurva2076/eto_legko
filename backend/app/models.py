from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.enums import OfferChangeActionType


class CampaignRecord(Base):
    """Локальный журнал кампаний, созданных через наш «создаватор»."""

    __tablename__ = 'campaign_records'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    geo: Mapped[str] = mapped_column(String(255))
    offer_id: Mapped[int] = mapped_column(Integer)


class OfferChange(Base):
    """Журнал добавления/удаления офферов через редактор."""

    __tablename__ = 'offer_changes'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    offer_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[OfferChangeActionType] = mapped_column(
        Enum(
            OfferChangeActionType,
            values_callable=lambda enum: [item.value for item in enum],
            name='action_type',
        ),
        nullable=False,
    )
