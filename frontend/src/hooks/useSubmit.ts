import { useState, type FormEvent } from "react";

import { ApiError, toApiError } from "../api/client";

/** Submit handler with pending/error state for simple forms. */
export function useSubmit<T>(
  action: () => Promise<T>,
  onSuccess: (result: T) => void,
) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<ApiError | undefined>(undefined);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(undefined);
    try {
      const result = await action();
      onSuccess(result);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setSubmitting(false);
    }
  }

  return { submitting, error, submit };
}
