# RootLens Inventory Service

The Inventory Service provides a small system that RootLens can eventually
observe and diagnose. It includes liveness and database-readiness endpoints,
request IDs, structured request logging, and basic create/read operations for
persistent inventory items. It can also reserve stock atomically by subtracting
a requested quantity from an item's on-hand quantity.

The PostgreSQL `inventory_items` table stores a UUID identifier, unique SKU,
name, non-negative on-hand quantity, and creation/update timestamps for each
item. Update, delete, restocking, reservation history, and Order Service
behavior are not implemented yet.

Docker Compose runs the single PostgreSQL dependency locally with a persistent
named volume; it does not containerize the Inventory Service.

## Database migrations

A database migration is a versioned, reversible description of a schema
change. This project uses Alembic migrations so schema changes are explicit,
reviewable, and consistently applied in every environment. The application
does not create tables during startup: doing so would hide schema changes in
the runtime path and make deployment ordering and rollback harder to control.

The initial migration creates `inventory_items`, including its primary key,
unique and indexed SKU, and database check constraint that prevents negative
quantities. Its downgrade removes the table.

## Local environment

The commands below assume Python 3.12 and start from the repository root. Copy
the committed development example before starting either PostgreSQL or the app:

```bash
cp .env.example .env
```

The example values are local-development credentials, not production secrets.
If `POSTGRES_PASSWORD` is changed, update the password embedded in
`DATABASE_URL` to match. The application and Alembic read the connection string
from the `DATABASE_URL` environment variable. A real `.env` remains ignored by
Git.

Create and activate a Python 3.12 virtual environment, then install the service
and its development dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "services/inventory[dev]"
```

Export all values from `.env` into the current shell before running Alembic:

```bash
set -a
source .env
set +a
```

## Start PostgreSQL and apply migrations

Start only PostgreSQL in the background:

```bash
docker compose up -d postgres
```

Inspect its running and health status:

```bash
docker compose ps postgres
```

The database is exposed only through `localhost:5432` by default. Compose uses
the root `.env` automatically and stores database files in the named
`postgres_data` volume.

Apply all pending Inventory Service migrations after exporting `.env`:

```bash
alembic -c services/inventory/alembic.ini upgrade head
```

Inspect the database's current migration revision:

```bash
alembic -c services/inventory/alembic.ini current
```

## Run and test the service

Run Ruff and the unit tests without requiring Docker or a live database:

```bash
python -m ruff check services/inventory
python -m pytest services/inventory
```

Run the Inventory Service and load `DATABASE_URL` from the root `.env`:

```bash
uvicorn --app-dir services/inventory/src inventory_service.main:app --reload --env-file .env
```

In another terminal, test liveness and readiness:

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/health/ready
```

`GET /health` is a liveness check: it reports that the application process is
running and does not contact PostgreSQL. `GET /health/ready` is a readiness
check: it returns `200` only when PostgreSQL answers a simple query, and returns
`503` when the database is unavailable.

Create an inventory item:

```bash
curl -i -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"sku":"LAPTOP-001","name":"Demo Laptop","quantity":10}'
```

List all items in ascending SKU order:

```bash
curl -i http://127.0.0.1:8000/items
```

Retrieve one item by its exact SKU:

```bash
curl -i http://127.0.0.1:8000/items/LAPTOP-001
```

Posting a SKU that already exists returns HTTP `409` with:

```json
{
  "detail": "An inventory item with this SKU already exists."
}
```

## Reserve stock

Stock reservation means atomically claiming some of an item's current on-hand
quantity so later requests cannot claim the same units. Reserve three units:

```bash
curl -i -X POST http://127.0.0.1:8000/items/LAPTOP-001/reserve \
  -H 'Content-Type: application/json' \
  -d '{"quantity":3}'
```

`POST /items/{sku}/reserve` returns HTTP `200` with only the reserved SKU, the
quantity reserved, and the quantity remaining:

```json
{
  "sku": "LAPTOP-001",
  "reserved_quantity": 3,
  "remaining_quantity": 7
}
```

The requested quantity must be an integer greater than zero. Zero, negative
numbers, and booleans return HTTP `422`; they cannot represent a meaningful
claim of stock. For example, this request is invalid:

```bash
curl -i -X POST http://127.0.0.1:8000/items/LAPTOP-001/reserve \
  -H 'Content-Type: application/json' \
  -d '{"quantity":0}'
```

A reservation for a missing SKU returns HTTP `404`:

```bash
curl -i -X POST http://127.0.0.1:8000/items/MISSING/reserve \
  -H 'Content-Type: application/json' \
  -d '{"quantity":1}'
```

A request exceeding the available quantity returns HTTP `409` with
`{"detail":"Insufficient inventory available."}`:

```bash
curl -i -X POST http://127.0.0.1:8000/items/LAPTOP-001/reserve \
  -H 'Content-Type: application/json' \
  -d '{"quantity":1000000}'
```

### Why reservation uses a row lock

The repository runs reservation in one database transaction and retrieves the
matching PostgreSQL row with `SELECT ... FOR UPDATE`. PostgreSQL holds that row
lock until the transaction commits or rolls back. If two requests target the
same final unit, the second request waits for the first transaction, then reads
the committed remaining quantity and is rejected. The availability check and
subtraction therefore cannot both succeed against the same starting value.

For a basic two-request demonstration, first create an item with one unit:

```bash
curl -i -X POST http://127.0.0.1:8000/items \
  -H 'Content-Type: application/json' \
  -d '{"sku":"CONCURRENCY-001","name":"Concurrency Demo","quantity":1}'
```

Then launch two reservations together from a shell:

```bash
curl -sS -o /tmp/rootlens-reservation-a.json -w 'A: %{http_code}\n' \
  -X POST http://127.0.0.1:8000/items/CONCURRENCY-001/reserve \
  -H 'Content-Type: application/json' -d '{"quantity":1}' &
curl -sS -o /tmp/rootlens-reservation-b.json -w 'B: %{http_code}\n' \
  -X POST http://127.0.0.1:8000/items/CONCURRENCY-001/reserve \
  -H 'Content-Type: application/json' -d '{"quantity":1}' &
wait
cat /tmp/rootlens-reservation-a.json
cat /tmp/rootlens-reservation-b.json
```

One request returns `200` and the other returns `409`; the item ends with zero
units. This changes only the item's current quantity. There is no reservation
history table and no Order Service yet.

Interactive API documentation is available at <http://127.0.0.1:8000/docs>,
with alternative documentation at <http://127.0.0.1:8000/redoc>.

## Request IDs and application logs

A request ID identifies one HTTP request across the service's logs and response.
Callers can supply an ID in the `X-Request-ID` header. If that header is absent
or blank, the service generates a UUID. The service returns the ID in the
`X-Request-ID` response header and includes it in its structured request log.

```bash
curl -i -H 'X-Request-ID: local-check-123' http://127.0.0.1:8000/items
```

Inventory Service application and request logs are emitted as JSON objects, one
per line. Uvicorn startup and access logs may remain plain text for now.
Readiness failures log only a generic event and never log the connection URL or
raw database exception. Reservation outcome logs include the request ID, SKU,
requested quantity, and either the remaining quantity or a rejection reason.

## Stop PostgreSQL

Stop and remove the container and Compose network while preserving local data:

```bash
docker compose down
```

To also delete the named PostgreSQL volume, use:

```bash
docker compose down -v
```

**Warning:** `docker compose down -v` permanently deletes the local PostgreSQL
volume and all data stored in it. The normal `docker compose down` command keeps
that volume so data survives the next container start.
