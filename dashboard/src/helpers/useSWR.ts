import { useState, useEffect, useRef, useCallback } from 'react';
import { apiFetch } from './api';

// ═══════════════════════════════════════════════════════════════
// Lightweight SWR (Stale-While-Revalidate) hook
// No external dependencies — wraps apiFetch with caching + dedup
// ═══════════════════════════════════════════════════════════════

interface CacheEntry<T> {
  data: T;
  fetchedAt: number;
}

interface SWROptions<T> {
  fetcher?: (key: string) => Promise<T>;
  staleTime?: number;
  revalidateInterval?: number;
  fallbackData?: T | null;
}

interface SWRResponse<T> {
  data: T | null;
  isLoading: boolean;
  isValidating: boolean;
  error: Error | null;
  mutate: (newData?: T | ((current: T | null) => T), shouldRevalidate?: boolean) => void;
}

const cache = new Map<string, CacheEntry<unknown>>();
const inflight = new Map<string, Promise<unknown>>();

const defaultFetcher = (url: string) => apiFetch(url).then(r => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
});

export function useSWR<T = unknown>(key: string | null, options: SWROptions<T> = {}): SWRResponse<T> {
  const {
    fetcher = defaultFetcher,
    staleTime = 60000,
    revalidateInterval = 0,
    fallbackData = null,
  } = options;

  const cached = key ? cache.get(key) as CacheEntry<T> | undefined : undefined;

  const [data, setData] = useState<T | null>(cached?.data ?? fallbackData);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(!cached?.data && key !== null);
  const [isValidating, setIsValidating] = useState(false);
  const mountedRef = useRef(true);
  const keyRef = useRef(key);

  const revalidate = useCallback(async () => {
    if (!keyRef.current) return;
    const currentKey = keyRef.current;

    // Dedup: reuse in-flight request
    if (inflight.has(currentKey)) {
      try {
        const result = await inflight.get(currentKey) as T;
        if (mountedRef.current && keyRef.current === currentKey) {
          setData(result);
          setError(null);
        }
      } catch (e) {
        if (mountedRef.current && keyRef.current === currentKey) setError(e as Error);
      }
      return;
    }

    setIsValidating(true);
    const promise = fetcher(currentKey);
    inflight.set(currentKey, promise);

    try {
      const result = await promise;
      cache.set(currentKey, { data: result, fetchedAt: Date.now() });
      if (mountedRef.current && keyRef.current === currentKey) {
        setData(result);
        setError(null);
        setIsLoading(false);
      }
    } catch (e) {
      if (mountedRef.current && keyRef.current === currentKey) {
        setError(e as Error);
        setIsLoading(false);
      }
    } finally {
      inflight.delete(currentKey);
      if (mountedRef.current) setIsValidating(false);
    }
  }, [fetcher]);

  // Fetch on mount or key change
  useEffect(() => {
    keyRef.current = key;
    if (!key) {
      setData(fallbackData);
      setIsLoading(false);
      return;
    }

    const entry = cache.get(key) as CacheEntry<T> | undefined;
    if (entry) {
      setData(entry.data);
      setIsLoading(false);
      const isFresh = Date.now() - entry.fetchedAt < staleTime;
      if (!isFresh) revalidate();
    } else {
      setIsLoading(true);
      revalidate();
    }
  }, [key, staleTime, revalidate, fallbackData]);

  // Periodic revalidation
  useEffect(() => {
    if (!revalidateInterval || !key) return;
    const id = setInterval(revalidate, revalidateInterval);
    return () => clearInterval(id);
  }, [key, revalidateInterval, revalidate]);

  // Cleanup
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  // Optimistic mutate: update cache + state immediately, optionally revalidate
  const mutate = useCallback((newData?: T | ((current: T | null) => T), shouldRevalidate: boolean = true) => {
    if (!keyRef.current) return;
    let resolved = newData;
    if (typeof newData === 'function') {
      const current = (cache.get(keyRef.current) as CacheEntry<T> | undefined)?.data ?? null;
      resolved = (newData as (current: T | null) => T)(current);
    }
    if (resolved !== undefined) {
      cache.set(keyRef.current, { data: resolved, fetchedAt: Date.now() });
      setData(resolved as T);
    }
    if (shouldRevalidate) revalidate();
  }, [revalidate]);

  return { data, isLoading, isValidating, error, mutate };
}

export function invalidateCache(key: string): void {
  cache.delete(key);
}

export function clearCache(): void {
  cache.clear();
}
