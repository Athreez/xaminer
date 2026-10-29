/**
 * The exam's outbox (PRD ATT-08, ATT-09; architecture § 9.6): every change is written to the
 * device (IndexedDB) before anything is sent, so a reload, crash or power cut loses nothing.
 *
 * One entry per thing (an answer to a question, its review flag, a code draft per language), so a
 * newer change replaces the queued older one. Each change gets the next `revision` for the
 * attempt; the counter is stored too, so it keeps rising across reloads. An entry is removed only
 * if what was sent is still the newest version (an edit made during the upload stays queued).
 */

export type Kind = "answer" | "flag" | "draft";

/** Lower sends first (architecture § 9.6: answers and drafts → heartbeat → code → proctoring). */
export const PRIORITY: Record<Kind, number> = { answer: 0, draft: 0, flag: 0 };

export interface Entry {
  key: string; // e.g. answer:<attemptId>:<examQuestionId>
  attemptId: string;
  kind: Kind;
  target: string; // exam question id (and language for drafts)
  payload: Record<string, unknown>;
  revision: number;
  priority: number;
  queuedAt: number;
  rejected?: string; // set when the server refused it for good (e.g. time up)
}

const DB_NAME = "xaminer-outbox";
const ENTRIES = "entries";
const COUNTERS = "counters";

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function done(tx: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

export function keyOf(kind: Kind, attemptId: string, target: string): string {
  return `${kind}:${attemptId}:${target}`;
}

export class Outbox {
  private readonly db: IDBDatabase;

  private constructor(db: IDBDatabase) {
    this.db = db;
  }

  static async open(factory: IDBFactory = indexedDB, name = DB_NAME): Promise<Outbox> {
    const req = factory.open(name, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      const entries = db.createObjectStore(ENTRIES, { keyPath: "key" });
      entries.createIndex("attemptId", "attemptId");
      db.createObjectStore(COUNTERS);
    };
    return new Outbox(await request(req));
  }

  close(): void {
    this.db.close();
  }

  /**
   * Make the revision counter at least `floor` (on resume: the highest revision the server already
   * has), so new changes always outrank what the server stored.
   */
  async ensureRevisionAbove(attemptId: string, floor: number): Promise<void> {
    const tx = this.db.transaction(COUNTERS, "readwrite");
    const store = tx.objectStore(COUNTERS);
    const current = ((await request(store.get(attemptId))) as number | undefined) ?? 0;
    if (floor > current) store.put(floor, attemptId);
    await done(tx);
  }

  /** Queue a change. Returns its revision. A newer change replaces the queued one. */
  async put(
    attemptId: string,
    kind: Kind,
    target: string,
    payload: Record<string, unknown>,
    now: number = Date.now(),
  ): Promise<Entry> {
    const tx = this.db.transaction([ENTRIES, COUNTERS], "readwrite");
    const counters = tx.objectStore(COUNTERS);
    const revision = (((await request(counters.get(attemptId))) as number | undefined) ?? 0) + 1;
    counters.put(revision, attemptId);
    const entry: Entry = {
      key: keyOf(kind, attemptId, target),
      attemptId,
      kind,
      target,
      payload,
      revision,
      priority: PRIORITY[kind],
      queuedAt: now,
    };
    tx.objectStore(ENTRIES).put(entry);
    await done(tx);
    return entry;
  }

  /** What still has to reach the server, highest priority first, oldest first within it. */
  async pending(attemptId: string): Promise<Entry[]> {
    const tx = this.db.transaction(ENTRIES, "readonly");
    const all = (await request(
      tx.objectStore(ENTRIES).index("attemptId").getAll(attemptId),
    )) as Entry[];
    return all
      .filter((e) => !e.rejected)
      .sort((a, b) => a.priority - b.priority || a.queuedAt - b.queuedAt);
  }

  /** Entries the server refused for good (shown honestly to the student). */
  async rejected(attemptId: string): Promise<Entry[]> {
    const tx = this.db.transaction(ENTRIES, "readonly");
    const all = (await request(
      tx.objectStore(ENTRIES).index("attemptId").getAll(attemptId),
    )) as Entry[];
    return all.filter((e) => e.rejected);
  }

  /** Remove entries the server confirmed, unless they were changed again meanwhile. */
  async confirm(sent: Entry[]): Promise<void> {
    if (sent.length === 0) return;
    const tx = this.db.transaction(ENTRIES, "readwrite");
    const store = tx.objectStore(ENTRIES);
    for (const entry of sent) {
      const current = (await request(store.get(entry.key))) as Entry | undefined;
      if (current && current.revision === entry.revision) store.delete(entry.key);
    }
    await done(tx);
  }

  /** Mark entries as refused for good (e.g. "time up"), unless changed again meanwhile. */
  async reject(sent: Entry[], reason: string): Promise<void> {
    const tx = this.db.transaction(ENTRIES, "readwrite");
    const store = tx.objectStore(ENTRIES);
    for (const entry of sent) {
      const current = (await request(store.get(entry.key))) as Entry | undefined;
      if (current && current.revision === entry.revision)
        store.put({ ...current, rejected: reason });
    }
    await done(tx);
  }

  /** Forget an attempt (after it ended and nothing is left to send). */
  async clear(attemptId: string): Promise<void> {
    const tx = this.db.transaction([ENTRIES, COUNTERS], "readwrite");
    const keys = await request(tx.objectStore(ENTRIES).index("attemptId").getAllKeys(attemptId));
    for (const key of keys) tx.objectStore(ENTRIES).delete(key);
    tx.objectStore(COUNTERS).delete(attemptId);
    await done(tx);
  }
}
