# RootLens Inventory Service

The Inventory Service will eventually provide inventory capabilities for a
system that RootLens can observe and diagnose. The current version provides
liveness and database-readiness endpoints, request IDs, structured request
logging, and the asynchronous PostgreSQL connection foundation. It does not
create inventory tables, models, migrations, or CRUD operations.

PostgreSQL will eventually persist inventory data. At this milestone, the
service only opens asynchronous connections and runs `SELECT 1` for readiness.
Docker Compose runs that single PostgreSQL dependency locally with a persistent
named volume; it does not containerize the Inventory Service.

## Local environment

The commands below assume Python 3.12 and start from the repository root. Copy
the committed development example before starting either PostgreSQL or the app:

```bash
cp .env.example .env
```

The example values are local-development credentials, not production secrets.
If `POSTGRES_PASSWORD` is changed, update the password embedded in
`DATABASE_URL` to match. The application reads its connection string from the
`DATABASE_URL` environment variable. A real `.env` remains ignored by Git.

Create and activate a Python 3.12 virtual environment, then install the service
and its development dependencies:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "services/inventory[dev]"
```

## Start and inspect PostgreSQL

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

## Run and test the service

Run the unit tests without requiring Docker or a live database:

```bash
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

Interactive API documentation is available at <http://127.0.0.1:8000/docs>,
with alternative documentation at <http://127.0.0.1:8000/redoc>.

## Request IDs and application logs

A request ID identifies one HTTP request across the service's logs and response.
Callers can supply an ID in the `X-Request-ID` header. If that header is absent
or blank, the service generates a UUID. The service returns the ID in the
`X-Request-ID` response header and includes it in its structured request log.

```bash
curl -i -H 'X-Request-ID: local-check-123' http://127.0.0.1:8000/health/ready
```

Inventory Service application and request logs are emitted as JSON objects, one
per line. Uvicorn startup and access logs may remain plain text for now.
Readiness failures log only a generic event and never log the connection URL or
raw database exception.

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
