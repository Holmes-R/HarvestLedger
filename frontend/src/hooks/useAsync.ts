import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, isAbortError, toApiError } from "../api/client";

export interface AsyncResult<T> {
  data?: T;
  error?: ApiError;
  loading: boolean;
  reload: () => void;
}

interface Settled<T> {
  key: string;
  data?: T;
  error?: ApiError;
}

/**
 * Run an async loader and track loading/error state. The loader receives an
 * `AbortSignal` that is aborted when the deps change or the component unmounts,
 * so in-flight requests are cancelled rather than left to race. Aborted requests
 * are ignored (they never surface as an error). `deps` (primitives) control when
 * the loader re-runs; `reload` re-runs it without changing deps. A result only
 * surfaces once it matches the current request, so stale values never leak.
 */
export function useAsync<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
): AsyncResult<T> {
  const depKey = deps.map((value) => String(value)).join("|");
  const [reloadToken, setReloadToken] = useState(0);
  const requestKey = `${depKey}#${reloadToken}`;
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  const sequence = useRef(0);
  const loaderRef = useRef(loader);

  useEffect(() => {
    loaderRef.current = loader;
  }, [loader, requestKey]);

  useEffect(() => {
    const controller = new AbortController();
    const id = ++sequence.current;
    loaderRef.current(controller.signal).then(
      (data) => {
        if (sequence.current === id) setSettled({ key: requestKey, data });
      },
      (cause: unknown) => {
        if (sequence.current !== id || isAbortError(cause)) return;
        setSettled({ key: requestKey, error: toApiError(cause) });
      },
    );
    return () => controller.abort();
  }, [requestKey]);

  const reload = useCallback(() => setReloadToken((value) => value + 1), []);

  const ready = settled !== null && settled.key === requestKey;
  return {
    data: ready ? settled.data : undefined,
    error: ready ? settled.error : undefined,
    loading: !ready,
    reload,
  };
}
