# ReadForge

## Database

Start PostgreSQL with pgvector and initialize the schema:

```bash
docker compose up -d postgres
uv run readforge-db
docker compose exec postgres psql -U readforge -d readforge -c "\dt"
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
