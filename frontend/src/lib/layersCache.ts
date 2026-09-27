import type { LayersResponse } from "./types";

// Stale-while-revalidate cache for /layers (B19). In Live mode the last response for the view is
// painted as soon as the map mounts, then the fresh response replaces it. Every storage access is
// wrapped: private mode, a full quota or a blocked IndexedDB must only lose the optimisation, never
// the map itself.

export type Bbox = [number, number, number, number];

export interface CachedLayers {
  bbox: Bbox;
  data: LayersResponse;
  storedAt: number;
}

type CachedEntry = CachedLayers & { key: string };

const DB_NAME = "mapay";
const DB_VERSION = 1;
const STORE = "layers";
const MAX_ENTRIES = 8;
const FALLBACK_PREFIX = "mapay_layers_cache:";

export function layersCacheKey(bbox: Bbox): string {
  return bbox.map((value) => value.toFixed(2)).join(",");
}

function covers(outer: Bbox, inner: Bbox): boolean {
  return outer[0] <= inner[0] && outer[1] <= inner[1] && outer[2] >= inner[2] && outer[3] >= inner[3];
}

function newestCovering(entries: CachedEntry[], bbox: Bbox): CachedLayers | null {
  const covering = entries
    .filter((entry) => Array.isArray(entry.bbox) && covers(entry.bbox, bbox))
    .sort((a, b) => b.storedAt - a.storedAt);
  return covering[0] ?? null;
}

let dbPromise: Promise<IDBDatabase | null> | null = null;

function openDb(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise((resolve) => {
    try {
      if (typeof indexedDB === "undefined") {
        resolve(null);
        return;
      }
      const request = indexedDB.open(DB_NAME, DB_VERSION);
      request.onupgradeneeded = () => {
        const db = request.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: "key" });
        }
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => resolve(null);
      request.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

async function readAllFromDb(): Promise<CachedEntry[] | null> {
  try {
    const db = await openDb();
    if (!db) return null;
    return await new Promise((resolve) => {
      try {
        const request = db.transaction(STORE, "readonly").objectStore(STORE).getAll();
        request.onsuccess = () => resolve((request.result as CachedEntry[] | undefined) ?? []);
        request.onerror = () => resolve([]);
      } catch {
        resolve(null);
      }
    });
  } catch {
    return null;
  }
}

function readFallback(bbox: Bbox): CachedLayers | null {
  try {
    const entries: CachedEntry[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (!key || !key.startsWith(FALLBACK_PREFIX)) continue;
      try {
        const raw = localStorage.getItem(key);
        const parsed = raw ? (JSON.parse(raw) as CachedEntry) : null;
        if (parsed && Array.isArray(parsed.bbox) && parsed.data) entries.push(parsed);
      } catch {
        // skip malformed entries
      }
    }
    const key = layersCacheKey(bbox);
    return entries.find((entry) => layersCacheKey(entry.bbox) === key) ?? newestCovering(entries, bbox);
  } catch {
    return null;
  }
}

export async function getCachedLayers(bbox: Bbox): Promise<CachedLayers | null> {
  try {
    const entries = await readAllFromDb();
    if (entries) {
      const key = layersCacheKey(bbox);
      return entries.find((entry) => entry.key === key) ?? newestCovering(entries, bbox);
    }
    return readFallback(bbox);
  } catch {
    return null;
  }
}

async function pruneDb(db: IDBDatabase): Promise<void> {
  try {
    const entries = await readAllFromDb();
    if (!entries || entries.length <= MAX_ENTRIES) return;
    const oldest = [...entries].sort((a, b) => a.storedAt - b.storedAt).slice(0, entries.length - MAX_ENTRIES);
    await new Promise<void>((resolve) => {
      try {
        const tx = db.transaction(STORE, "readwrite");
        const store = tx.objectStore(STORE);
        oldest.forEach((entry) => store.delete(entry.key));
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve();
        tx.onabort = () => resolve();
      } catch {
        resolve();
      }
    });
  } catch {
    // pruning is best effort
  }
}

export async function putCachedLayers(bbox: Bbox, data: LayersResponse): Promise<void> {
  const entry: CachedEntry = { key: layersCacheKey(bbox), bbox, data, storedAt: Date.now() };
  try {
    const db = await openDb();
    if (db) {
      await new Promise<void>((resolve) => {
        try {
          const tx = db.transaction(STORE, "readwrite");
          tx.objectStore(STORE).put(entry);
          tx.oncomplete = () => resolve();
          tx.onerror = () => resolve();
          tx.onabort = () => resolve();
        } catch {
          resolve();
        }
      });
      await pruneDb(db);
      return;
    }
  } catch {
    // fall through to localStorage
  }
  try {
    localStorage.setItem(FALLBACK_PREFIX + entry.key, JSON.stringify(entry));
  } catch {
    // quota or unavailable: skip the cache
  }
}
