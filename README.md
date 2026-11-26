# Adrobot — создатель и редактор кампаний Keitaro

Тестовое задание: обёртка над Keitaro Admin API.

- **Бэкенд:** FastAPI + SQLAlchemy 2 + Alembic (SQLite по умолчанию), клиент на httpx
- **Фронтенд:** Vue 3 + Vite

## Что умеет

1. **Создание кампании** (название, гео, оффер с автокомплитом). Создаются:
   - кампания с доменом, группой и источником (берутся из API; по умолчанию — id 1813 / 10332 / 836, если их нет — первый элемент справочника);
   - поток 1 (`regular`, `redirect`): страна(ы) из гео → `https://google.com`, фильтр `country` / `accept`;
   - поток 2 (`default`, `landings`): выбранный оффер, доля 100%.
   - Гео можно указать списком через запятую (`MX,AU,RO`). Если создание потоков не удалось, кампания удаляется — «полусобранных» не остаётся.
2. **Редактор кампании**: выбор кампании, просмотр потоков, добавление и удаление офферов, редактирование долей.
   - Состав офферов потока заменяется целиком (`PUT /streams/{id}`), как в API.
   - При добавлении и удалении оффера доли распределяются поровну, сумма всегда ровно 100 (остаток раздаётся первым офферам: 3 оффера → 34/33/33).
   - Доли можно править вручную; сохранение доступно только при сумме 100%.
   - Если в кампании нет потока с офферами, он создаётся при добавлении первого оффера.

## Настройка

Создайте `.env` в корне проекта (см. `.env.example`):

```
KEITARO_API_KEY=<ваш ключ с кнопки «API ключ» в админке стенда>
KEITARO_URL=https://keitaro-for-tests.etolegko.com/admin_api/v1
```

`KEITARO_URL` можно указать и без суффикса `/admin_api/v1` — он будет добавлен автоматически.

Необязательные переменные: `DATABASE_URL` (по умолчанию `sqlite:///backend/adrobot.db`), `DEFAULT_DOMAIN_ID`, `DEFAULT_GROUP_ID`, `DEFAULT_SOURCE_ID`.

## Запуск бэкенда

### Linux

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# миграции
alembic upgrade head

# сервер
uvicorn app.main:app --reload --port 8000
```

### Windows

```bash
cd backend
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# миграции
alembic upgrade head

# сервер
uvicorn app.main:app --reload --port 8000
```

Если PowerShell пишет `running scripts is disabled`, выполните один раз 
```bash
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
или используйте cmd и активируйте окружение командой `.venv\Scripts\activate.bat`.

Swagger: http://127.0.0.1:8000/docs

## Запуск фронтенда

```bash
cd frontend
npm install
npm run dev
```

Откройте http://localhost:5173 (запросы `/api` проксируются на бэкенд `127.0.0.1:8000`).

## API бэкенда

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/meta` | домен, группа, источник по умолчанию |
| GET | `/api/offers?q=` | поиск офферов (по названию или ID) |
| GET | `/api/campaigns` | список кампаний |
| POST | `/api/campaigns` | создать кампанию `{name, geo, offer_id}` |
| GET | `/api/campaigns/{id}` | кампания с потоками и офферами |
| POST | `/api/campaigns/{id}/offers` | добавить оффер `{offer_id}` |
| DELETE | `/api/campaigns/{id}/offers/{offer_id}` | удалить оффер |
| PUT | `/api/campaigns/{id}/offers/shares` | задать доли `{shares:[{offer_id, share}]}` (сумма = 100) |
| POST | `/api/campaigns/{id}/offers/equalize` | распределить доли поровну |
| GET | `/api/created` | локальный журнал созданных кампаний (SQLAlchemy) |

## Структура БД

- `campaign_records` — кампании, созданные через «создаватор»;
- `offer_changes` — журнал добавления/удаления офферов и правки долей.

Запросы к Keitaro видны в разделе «Журнал» тренировочной админки.
