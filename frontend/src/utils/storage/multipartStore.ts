/**
 * In-memory store for tracking active S3 multipart upload sessions.
 *
 * When a chunked upload begins (chunkIndex === 0), a new session is created
 * holding the R2 UploadId and an ordered list of part ETags. Each subsequent
 * chunk appends its ETag. When the final chunk arrives, the session is used
 * to complete the multipart upload and then cleaned up.
 *
 * ⚠️  This store lives in server process memory. It works correctly for a
 *     single Next.js server instance. For horizontally-scaled deployments,
 *     replace this with Redis or a database-backed store.
 */

/** State for a single in-progress multipart upload. */
export interface MultipartSession {
  /** The S3/R2 multipart UploadId. */
  uploadId: string;
  /** The object key in the R2 bucket. */
  key: string;
  /** Ordered list of uploaded part ETags (index = partNumber - 1). */
  eTags: string[];
  /** Total number of chunks expected for this upload. */
  totalChunks: number;
  /** The whole-file SHA-256 checksum. */
  checksum: string;
  /** Timestamp (ms) when this session was created. */
  createdAt: number;
}

/**
 * Sessions are keyed by `checksum:fileName` to uniquely identify an upload.
 * The same file re-uploaded will generate the same checksum, but combined
 * with the fileName it provides a practical unique key.
 */
const sessions = new Map<string, MultipartSession>();

/** Build the session key from the checksum and fileName. */
export function sessionKey(checksum: string, fileName: string): string {
  return `${checksum}:${fileName}`;
}

/** Create and store a new multipart session. */
export function createSession(
  key: string,
  uploadId: string,
  checksum: string,
  fileName: string,
  totalChunks: number,
): MultipartSession {
  const session: MultipartSession = {
    uploadId,
    key,
    eTags: [],
    totalChunks,
    checksum,
    createdAt: Date.now(),
  };
  sessions.set(sessionKey(checksum, fileName), session);
  return session;
}

/** Retrieve an existing session, or `undefined` if not found. */
export function getSession(
  checksum: string,
  fileName: string,
): MultipartSession | undefined {
  return sessions.get(sessionKey(checksum, fileName));
}

/** Delete a session (used after completion or abort). */
export function deleteSession(checksum: string, fileName: string): void {
  sessions.delete(sessionKey(checksum, fileName));
}

/* ─── Stale session cleanup ─── */

/** Maximum age for a session before it is considered stale (1 hour). */
const SESSION_MAX_AGE_MS = 60 * 60 * 1000;

/**
 * Purge sessions older than {@link SESSION_MAX_AGE_MS}.
 * Called on every incoming request to prevent unbounded memory growth.
 */
export function purgeStale(): void {
  const now = Date.now();
  for (const [k, session] of sessions) {
    if (now - session.createdAt > SESSION_MAX_AGE_MS) {
      sessions.delete(k);
    }
  }
}
