// IST business-date helpers. The backend is authoritative; these only provide
// convenient defaults and labels. Business dates are plain `YYYY-MM-DD` dates in
// Asia/Kolkata (UTC+05:30); audit timestamps are ISO-8601 with an offset.

const IST = "Asia/Kolkata";

const dateOnly = new Intl.DateTimeFormat("en-CA", {
  timeZone: IST,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const readableDate = new Intl.DateTimeFormat("en-GB", {
  timeZone: "UTC",
  day: "2-digit",
  month: "short",
  year: "numeric",
});

const readableTimestamp = new Intl.DateTimeFormat("en-GB", {
  timeZone: IST,
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** Today's IST business date (`YYYY-MM-DD`). */
export function istToday(): string {
  return dateOnly.format(new Date());
}

function toUtc(dateStr: string): Date {
  return new Date(`${dateStr}T00:00:00Z`);
}

/** Monday of the week containing `dateStr` (Monday..Sunday). */
export function mondayOf(dateStr: string): string {
  const date = toUtc(dateStr);
  const offset = (date.getUTCDay() + 6) % 7; // 0 = Monday
  date.setUTCDate(date.getUTCDate() - offset);
  return date.toISOString().slice(0, 10);
}

/** Sunday of the week containing `dateStr`. */
export function sundayOf(dateStr: string): string {
  const monday = toUtc(mondayOf(dateStr));
  monday.setUTCDate(monday.getUTCDate() + 6);
  return monday.toISOString().slice(0, 10);
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  return readableDate.format(toUtc(dateStr));
}

export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return `${readableTimestamp.format(parsed)} IST`;
}

const apiDatePattern = /^\d{4}-\d{2}-\d{2}$/;

/** True when `value` is a bare calendar date the API accepts (`YYYY-MM-DD`). */
export function isApiDate(value: string): boolean {
  return apiDatePattern.test(value);
}

/**
 * Serialise a value to the API's date contract (`YYYY-MM-DD`). A bare date is
 * passed through; an ISO string or `Date` is reduced to its **IST** calendar
 * date (the backend derives business dates in Asia/Kolkata). Throws on input the
 * API could never accept, so a bad date fails fast in the client instead of
 * becoming a `400` mid-request.
 */
export function toApiDate(value: string | Date): string {
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (isApiDate(trimmed)) return trimmed;
    const parsed = new Date(trimmed);
    if (Number.isNaN(parsed.getTime())) throw new Error(`Not a date: ${value}`);
    return dateOnly.format(parsed);
  }
  if (Number.isNaN(value.getTime())) throw new Error("Not a date");
  return dateOnly.format(value);
}

const apiTimestampPattern = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

/** True when `value` is a timezone-aware ISO-8601 instant (the clock contract). */
export function isApiTimestamp(value: string): boolean {
  return apiTimestampPattern.test(value.trim());
}

