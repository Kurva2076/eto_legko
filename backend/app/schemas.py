import re

from pydantic import BaseModel, Field, field_validator


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    geo: str = Field(description='Код страны или несколько через запятую: MX,AU,RO')
    offer_id: int

    @field_validator('name')
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('Название не может быть пустым')
        return v

    @field_validator('geo')
    @classmethod
    def _geo(cls, v: str) -> str:
        codes = [c.strip().upper() for c in re.split(r'[,;\s]+', v) if c.strip()]
        if not codes:
            raise ValueError('Укажите хотя бы одно гео')
        for c in codes:
            if not re.fullmatch(r'[A-Z]{2}', c):
                raise ValueError(f'Некорректный код страны: {c} (нужен ISO-2, например AU)')
        return ','.join(dict.fromkeys(codes))


class OfferAdd(BaseModel):
    offer_id: int


class ShareItem(BaseModel):
    offer_id: int
    share: int = Field(ge=0, le=100)


class SharesUpdate(BaseModel):
    shares: list[ShareItem]
