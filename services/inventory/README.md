# RootLens Inventory Service

The Inventory Service will eventually provide inventory capabilities for a system that RootLens can observe and diagnose. As RootLens evolves, this service will act as a realistic source of telemetry and incident scenarios.

The current version is only the initial service skeleton and provides a health endpoint. It does not yet include inventory models, persistence, or CRUD operations.

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
