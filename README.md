# morebuttons

Shopify admin app (embedded) — набор инструментов для управления каталогом, заказами и доставкой.

## Features

- **Add Variant** — массовое добавление вариантов продукта (bulk create/update через GraphQL).
- **Order Lookup** — поиск заказа по трек-номеру + CSV-экспорт.
- **Product Tag Pricing** — цены по тегам продукта.
- **Shipping Rates** — delivery profiles, carrier catalog.
- **SKU Weight** — массовое обновление весов SKU.
- **GraphQL stats** — rate limiting, счётчики запросов.

## Stack

- **Backend:** Flask, SQLAlchemy Core, Shopify GraphQL API, Redis, PyJWT, pydantic
- **Frontend:** React 19, TypeScript, Shopify App Bridge, esbuild
- **Deploy:** Docker, Heroku

## Run

```bash
# 1. Postgres
docker compose up -d

# 2. Env
export SHOPIFY_API_KEY=... SHOPIFY_SECRET=... SHOPIFY_API_VERSION=2024-10
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/morebuttons
export FLASK_SECRET_KEY=...

# 3. Backend
flask --app src/backend/main.py run

# 4. Frontend build
npm install && npm run build
```

## Notes

- SQLAlchemy is used in **Core** mode (no ORM) — tables/columns via a typed singleton (`heresy`).
- Shopify rate limiting is handled via a Redis-backed limiter with a stats bar in the UI.
