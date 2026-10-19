import { useEffect, useRef, useState } from "react";

import { ApiError, isAbortError, toApiError } from "../api/client";
import { previewDelivery } from "../api/endpoints";
import type { DeliveryPreview, DeliveryWrite } from "../api/types";

interface Settled {
  key: string;
  preview?: DeliveryPreview;
  error?: ApiError;
}

export interface DeliveryPreviewState {
  preview?: DeliveryPreview;
  error?: ApiError;
  loading: boolean;
}

/**
 * Debounced, cancel-safe preview loader.
 *
 * - `body` is `null` unless the inputs are valid, so nothing is requested for an
 *   incomplete or invalid form.
 * - Every distinct body has a key. A preview is only returned when it matches the
 *   current key, so changing an input invalidates the old preview *immediately*
 *   (not when the next response arrives).
 * - Each run gets its own `AbortController`; the previous run is aborted and its
 *   late settlement is ignored, so a slow older response can never overwrite the
 *   latest one.
 * - There is no automatic retry: a failed preview stays failed until the inputs
 *   change (the version key changes).
 */
export function useDeliveryPreview(
  body: DeliveryWrite | null,
  { delay = 400 }: { delay?: number } = {},
): DeliveryPreviewState {
  const key = body ? JSON.stringify(body) : "";
  const bodyRef = useRef(body);
  useEffect(() => {
    bodyRef.current = body;
  }, [body]);

  const [settled, setSettled] = useState<Settled | null>(null);

  useEffect(() => {
    const requestBody = bodyRef.current;
    if (!requestBody) {
      setSettled(null);
      return;
    }

    let cancelled = false;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      previewDelivery(requestBody, { signal: controller.signal }).then(
        (preview) => {
          if (cancelled) return;
          setSettled({ key, preview });
        },
        (cause: unknown) => {
          if (cancelled || isAbortError(cause)) return;
          setSettled({ key, error: toApiError(cause) });
        },
      );
    }, delay);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [key, delay]);

  const current = settled && settled.key === key ? settled : null;
  return {
    preview: body ? current?.preview : undefined,
    error: body ? current?.error : undefined,
    loading: Boolean(body) && current === null,
  };
}
