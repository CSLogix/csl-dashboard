import { useState, useEffect, useRef, useCallback } from 'react';
import { apiFetch } from './api';

// ═══════════════════════════════════════════════════════════════
// Lightweight SWR (Stale-While-Revalidate) hook
// No external dependencies — wraps apiFetch with caching + dedup
// ═══════════════════════════════════════════════════════════════

const cache = new Map();     // key → { data, fetchedAt }
const inflight = new Map();  // key → Promise (dedup concurrent requests)

const defaultFetcher = (url) => apiFetch(url).then(r => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
});

/**
 * @param {string|null} key - URL or cache key (null to skip fetching)
 * @param {object} options
 * @param {Function} options.fetcher - Custom fetcher (default: apiFetch → json)
 * @param {number} options.staleTime - Ms before data is considered stale (default: 60000)
 * @param {number} options.revalidateInterval - Ms between auto-revalidation polls (0 = disabled)
 * @param {*} options.fallbackData - Initial data before first fetch
 * @returns {{ data, isLoading, isValidating, error, mutate }}
 */
export function useSWR(key, options = {}) {
  const {
    fetcher = defaultFetcher,
    staleTime = 60000,
    revalidateInterval = 0,
    fallbackData = null,
  } = options;

  const cached = key ? cache.get(key) : null;
  const hasFreshCache = cached && (Date.now() - cached.fetchedAt < staleTime);

  const [data, setData] = useState(cached?.data ?? fallbackData);
  const [error, setError] = useState(null);
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
        const result = await inflight.get(currentKey);
        if (mountedRef.current && keyRef.current === currentKey) {
          setData(result);
          setError(null);
        }
      } catch (e) {
        if (mountedRef.current && keyRef.current === currentKey) setError(e);
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
        setError(e);
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

    const entry = cache.get(key);
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
  const mutate = useCallback((newData, shouldRevalidate = true) => {
    if (!keyRef.current) return;
    if (typeof newData === 'function') {
      const current = cache.get(keyRef.current)?.data;
      newData = newData(current);
    }
    if (newData !== undefined) {
      cache.set(keyRef.current, { data: newData, fetchedAt: Date.now() });
      setData(newData);
    }
    if (shouldRevalidate) revalidate();
  }, [revalidate]);

  return { data, isLoading, isValidating, error, mutate };
}

// Invalidate a specific cache key (useful from outside React)
export function invalidateCache(key) {
  cache.delete(key);
}

// Clear all cached data
export function clearCache() {
  cache.clear();
}
