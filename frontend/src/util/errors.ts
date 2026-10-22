import type { ApiError } from "../api/client";

/** First server-side message for one request field, or null when absent. */
export function fieldError(
  error: ApiError | null | undefined,
  field: string,
): string | null {
  return error?.details[field]?.[0]?.message ?? null;
}
