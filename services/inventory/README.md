# RootLens Inventory Service

The Inventory Service will eventually provide inventory capabilities for a system that RootLens can observe and diagnose. As RootLens evolves, this service will act as a realistic source of telemetry and incident scenarios.

The current version provides a health endpoint, request IDs, and structured request
logging. It does not yet include inventory models, persistence, or CRUD operations.

## Local setup

From `services/inventory`, create and activate a Python 3.12 virtual environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Install the package and its development dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Run the tests

```bash
pytest
```

## Run the service locally

```bash
uvicorn inventory_service.main:app --reload
```

With the service running, open these URLs in a browser:

- Health endpoint: <http://127.0.0.1:8000/health>
- Interactive API documentation: <http://127.0.0.1:8000/docs>
- Alternative API documentation: <http://127.0.0.1:8000/redoc>

## Request IDs and application logs

A request ID identifies one HTTP request across the service's logs and response.
It makes it easier to find the log event associated with a specific caller or
response. Callers can supply an ID in the `X-Request-ID` header. If that header is
absent or blank, the service generates a UUID instead.

In both cases, the service returns the ID in the `X-Request-ID` response header
and includes the same value in its structured request log. Test a generated ID:

```bash
curl -i http://127.0.0.1:8000/health
```

Test a caller-supplied ID:

```bash
curl -i -H 'X-Request-ID: local-check-123' http://127.0.0.1:8000/health
```

Inventory Service application and request logs are emitted as JSON objects, one
per line. Uvicorn startup and access logs may remain plain text for now.
