import { useRef, useState, type FormEvent } from "react";

import { ApiError, toApiError } from "../api/client";

/** Submit handler with pending/error state for simple forms. */
export function useSubmit<T>(
  action: () => Promise<T>,
  onSuccess: (result: T) => void,
) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const inFlight = useRef(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setError(undefined);
    try {
      const result = await action();
      onSuccess(result);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  }

  return { submitting, error, submit };
}
