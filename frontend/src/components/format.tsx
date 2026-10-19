import { formatAmount, formatMoney } from "../util/decimal";
import { formatDate, formatTimestamp } from "../util/dates";

/** Rupee amount. String-only formatting keeps every decimal digit exactly. */
export function Money({
  value,
  suffix,
  className,
}: {
  value: string | null | undefined;
  suffix?: string;
  className?: string;
}) {
  const text = formatMoney(value);
  const empty = text === "\u2014";
  return (
    <span className={className ? `money ${className}` : "money"}>
      {text}
      {!empty && suffix ? <span className="money-suffix">{suffix}</span> : null}
    </span>
  );
}

/**
 * Date-only value (`YYYY-MM-DD`). Rendered from the literal calendar date, not
 * converted through a timezone, so the displayed day never shifts.
 */
export function DateOnly({
  value,
  className,
}: {
  value: string | null | undefined;
  className?: string;
}) {
  if (!value) return <span className="muted">—</span>;
  return (
    <time className={className} dateTime={value}>
      {formatDate(value)}
    </time>
  );
}

/**
 * Audit timestamp. Always shown in Asia/Kolkata with an explicit `IST` suffix
 * and a full ISO + zone tooltip; the raw string stays in `dateTime`/`title`.
 */
export function Timestamp({
  value,
  className,
}: {
  value: string | null | undefined;
  className?: string;
}) {
  if (!value) return <span className="muted">—</span>;
  return (
    <time className={className} dateTime={value} title={`${value} (Asia/Kolkata)`}>
      {formatTimestamp(value)}
    </time>
  );
}

/** Raw decimal + unit, kept as a string (e.g. weights, percentages). */
export function Quantity({
  value,
  unit,
  className,
}: {
  value: string | null | undefined;
  unit?: string;
  className?: string;
}) {
  if (value === null || value === undefined || value === "") {
    return <span className="muted">—</span>;
  }
  const text = formatAmount(value);
  return (
    <span className={className}>
      {text}
      {unit ? ` ${unit}` : ""}
    </span>
  );
}
