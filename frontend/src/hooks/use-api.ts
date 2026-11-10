"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api";

export interface Resource<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
  setData: (d: T | null) => void;
}

/**
 * Small fetch hook. `fetcher` is re-run whenever `key` changes.
 * If `pollMs` returns a number, the resource silently re-fetches at that interval
 * (return null to stop polling).
 */
export function useResource<T>(
  key: string | null,
  fetcher: () => Promise<T>,
  pollMs?: (data: T | null) => number | null,
): Resource<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(key !== null);
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  const pollRef = useRef(pollMs);
  const keyRef = useRef(key);
  useEffect(() => {
    fetcherRef.current = fetcher;
    pollRef.current = pollMs;
  });

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const keyChanged = keyRef.current !== key;
    keyRef.current = key;

    const run = async (initial: boolean) => {
      if (initial) {
        setLoading(true);
        if (keyChanged) setData(null);
      }
      try {
        const d = await fetcherRef.current();
        if (cancelled) return;
        setData(d);
        setError(null);
        setLoading(false);
        const next = pollRef.current?.(d);
        if (next != null) timer = setTimeout(() => run(false), next);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
        setLoading(false);
        // keep polling through transient errors
        const next = pollRef.current?.(null);
        if (next != null && !(e instanceof ApiError && e.status >= 400 && e.status < 500))
          timer = setTimeout(() => run(false), next);
      }
    };
    run(true);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [key, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

/** Run an async action with pending/error state. */
export function useAction<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const fnRef = useRef(fn);
  useEffect(() => {
    fnRef.current = fn;
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const run = useCallback(
    async (...args: A): Promise<R | undefined> => {
      setPending(true);
      setError(null);
      try {
        return await fnRef.current(...args);
      } catch (e) {
        setError(e instanceof ApiError ? e : new ApiError(0, String(e)));
        return undefined;
      } finally {
        setPending(false);
      }
    },
    [],
  );
  return { run, pending, error, clearError: () => setError(null) };
}
