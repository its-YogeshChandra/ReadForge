# ReadForge

## Run locally

First-time setup, including migrations:

```bash
make setup
```

Start the API and worker without duplicating running processes:

```bash
make start
make status
```

Useful commands:

```bash
make migrate  # after changing the SQLAlchemy schema
make logs
make stop      # stop the app processes and all containers
make restart   # stop everything, then start it again
make down      # stop and remove containers; named data volumes remain
```

The CLIP service runs at `http://localhost:8082/`. `make start` starts it when
needed, and `make status` checks that its HTTP API is responding.

## Database

Start PostgreSQL and apply pending migrations before starting the application:

```bash
docker compose up -d postgres
uv run readforge-migrate
docker compose exec postgres psql -U readforge -d readforge -c "\dt"
```

Run `uv run readforge-migrate` after pulling or creating schema changes. It is
safe when already current, but it is intentionally separate from API and worker
startup so only one process performs schema changes.

Create the next migration after editing SQLAlchemy models:

```bash
uv run alembic revision --autogenerate -m "describe schema change"
uv run readforge-migrate
```

If port `5432` is already occupied, use the same override for PostgreSQL and
the migration command:

```bash
POSTGRES_PORT=5433 docker compose up -d postgres
DATABASE_URL=postgresql+psycopg://readforge:readforge@localhost:5433/readforge \
  uv run readforge-migrate
```

The development connection string is:

```text
postgresql://readforge:readforge@localhost:5432/readforge
```

SQLAlchemy uses the async equivalent by default:

```text
postgresql+psycopg://readforge:readforge@localhost:5432/readforge
```

Redis remains the transient job queue. PostgreSQL stores users, documents,
durable job state, document OCR JSON, and vector-backed document chunks.
