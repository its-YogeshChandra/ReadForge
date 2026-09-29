BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- Authentication is intentionally out of scope; documents only need an owner.
CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    username text NOT NULL CHECK (btrim(username) <> ''),
    email text NOT NULL CHECK (btrim(email) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS users_username_unique
    ON users (lower(username));
CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique
    ON users (lower(email));

CREATE TABLE IF NOT EXISTS documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    object_key text NOT NULL UNIQUE CHECK (btrim(object_key) <> ''),
    content_type text,
    size_bytes bigint CHECK (size_bytes >= 0),
    page_count integer CHECK (page_count > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Redis owns the short-lived queue payload and presigned URL. PostgreSQL keeps
-- the durable job state, using the same UUID returned by the upload endpoint.
CREATE TABLE IF NOT EXISTS jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    idempotency_key text NOT NULL
        CHECK (octet_length(btrim(idempotency_key)) BETWEEN 1 AND 20),
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    completed_at timestamptz,
    UNIQUE (document_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS jobs_pending_idx
    ON jobs (status, created_at)
    WHERE status IN ('queued', 'processing');

-- This matches OcrResponse.file_data: {"text": ..., "lines": [...]}.
CREATE TABLE IF NOT EXISTS document_pages (
    document_id uuid NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    page_number integer NOT NULL CHECK (page_number > 0),
    ocr_result jsonb NOT NULL
        CHECK (
            jsonb_typeof(ocr_result) = 'object'
            AND ocr_result ? 'text'
            AND ocr_result ? 'lines'
            AND jsonb_typeof(ocr_result -> 'text') = 'string'
            AND jsonb_typeof(ocr_result -> 'lines') = 'array'
        ),
    PRIMARY KEY (document_id, page_number)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id uuid NOT NULL,
    page_number integer NOT NULL,
    chunk_index integer NOT NULL CHECK (chunk_index >= 0),
    content text NOT NULL CHECK (btrim(content) <> ''),
    embedding_model text NOT NULL CHECK (btrim(embedding_model) <> ''),
    embedding vector NOT NULL,
    FOREIGN KEY (document_id, page_number)
        REFERENCES document_pages (document_id, page_number) ON DELETE CASCADE,
    UNIQUE (document_id, page_number, chunk_index)
);

CREATE INDEX IF NOT EXISTS document_chunks_page_idx
    ON document_chunks (document_id, page_number);

-- The embedding size is not known until the self-hosted model is finalized.
-- Keep vector unconstrained for now; add vector(N) plus an HNSW index then.

COMMIT;
