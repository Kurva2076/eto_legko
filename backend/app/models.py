from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import OfferChangeActionType, OfferStatus


class CampaignRecord(Base):
    """Локальный журнал кампаний, созданных через наш «создаватор»."""

    __tablename__ = 'campaign_records'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    geo: Mapped[str] = mapped_column(String(255))
    offer_id: Mapped[int] = mapped_column(Integer)


class OfferChange(Base):
    """Журнал действий с офферами через редактор."""

    __tablename__ = 'offer_changes'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(Integer, index=True)
    stream_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    offer_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[OfferChangeActionType] = mapped_column(
        Enum(
            OfferChangeActionType,
            values_callable=lambda enum: [item.value for item in enum],
            name='action_type',
        ),
        nullable=False,
    )


class Offer(Base):
    """Каталог офферов Keitaro (для поиска без обращения к API). ID совпадает с ID оффера в Keitaro."""

    __tablename__ = 'offers'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(512))


class Campaign(Base):
    """Кампания Keitaro, сохранённая в нашей БД. keitaro_id — ID кампании в Keitaro."""

    __tablename__ = 'campaigns'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    alias: Mapped[str | None] = mapped_column(String(255), nullable=True)
    state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    streams: Mapped[list['Stream']] = relationship(
        back_populates='campaign',
        cascade='all, delete-orphan',
        order_by='Stream.position',
    )


class Stream(Base):
    """
    Поток кампании в нашей БД. keitaro_id — ID потока в Keitaro.
    synced_offers и synced_schema — состояние потока в Keitaro на момент последней синхронизации,
    с ними сравнивается локальное состояние, чтобы найти незафиксированные изменения.
    """

    __tablename__ = 'streams'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey('campaigns.id', ondelete='CASCADE'), index=True)
    keitaro_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    schema: Mapped[str | None] = mapped_column(String(32), nullable=True)
    synced_schema: Mapped[str | None] = mapped_column(String(32), nullable=True)
    state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    action_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    filters: Mapped[list] = mapped_column(JSON, default=list)
    synced_offers: Mapped[list] = mapped_column(JSON, default=list)

    campaign: Mapped['Campaign'] = relationship(back_populates='streams')
    offers: Mapped[list['StreamOffer']] = relationship(
        back_populates='stream',
        cascade='all, delete-orphan',
        order_by='StreamOffer.id',
    )


class StreamOffer(Base):
    """
    Оффер в потоке в нашей БД. Удалённый из потока оффер не стирается, а получает статус REMOVED,
    чтобы его можно было восстановить. Закреплённые (pinned) офферы не участвуют в пересчёте долей.
    """

    __tablename__ = 'stream_offers'
    __table_args__ = (UniqueConstraint('stream_id', 'offer_id', name='uq_stream_offers_stream_offer'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[int] = mapped_column(ForeignKey('streams.id', ondelete='CASCADE'), index=True)
    offer_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(512))
    share: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    keitaro_state: Mapped[str] = mapped_column(String(32), default='active')
    status: Mapped[OfferStatus] = mapped_column(
        Enum(
            OfferStatus,
            values_callable=lambda enum: [item.value for item in enum],
            name='offer_status',
            native_enum=False,
            length=16,
        ),
        default=OfferStatus.ACTIVE,
    )

    stream: Mapped['Stream'] = relationship(back_populates='offers')
