// Decimal helpers. Values travel as strings end-to-end so precision is never
// lost; these functions only validate and display, never do arithmetic.

export const SCALE = {
  money: 2,
  grossWeight: 3,
  moisture: 2,
  derivedWeight: 5,
  price: 2,
} as const;

const DECIMAL = /^-?\d+(\.\d+)?$/;

export function isDecimal(value: string): boolean {
  return DECIMAL.test(value.trim());
}

export function decimalPlaces(value: string): number {
  const dot = value.indexOf(".");
  return dot === -1 ? 0 : value.length - dot - 1;
}

export interface DecimalRule {
  /** Maximum decimal places allowed by the destination column. */
  places: number;
  /** Value must be strictly greater than zero (advances, magnitudes, weights). */
  positive?: boolean;
  /** Value may be zero or negative (not used by current forms). */
  allowNegative?: boolean;
}

/** Return a human message when `value` breaks the rule, else null. */
export function validateDecimal(value: string, rule: DecimalRule): string | null {
  const trimmed = value.trim();
  if (!trimmed) return "Required.";
  if (!isDecimal(trimmed)) return "Enter a number.";
  if (decimalPlaces(trimmed) > rule.places) {
    return `At most ${rule.places} decimal place${rule.places === 1 ? "" : "s"}.`;
  }
  const negative = trimmed.startsWith("-");
  if (negative && !rule.allowNegative) return "Must be positive.";
  if (rule.positive && /^-?0*\.?0*$/.test(trimmed)) return "Must be greater than zero.";
  return null;
}

const EM_DASH = "\u2014";

/** Indian digit grouping: last three digits, then pairs (`12,34,567`). */
function groupIndian(digits: string): string {
  if (digits.length <= 3) return digits;
  const last3 = digits.slice(-3);
  const leading = digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  return `${leading},${last3}`;
}

/**
 * Group the integer part of a decimal string for display (Indian grouping) and
 * keep the fractional part **verbatim**. This works on strings only, so the
 * exact decimal value — including zeros such as `245.00` — is never parsed to a
 * float and precision is never lost. Unparseable input is returned unchanged
 * rather than silently reformatted.
 */
export function formatAmount(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return EM_DASH;
  const trimmed = value.trim();
  if (!isDecimal(trimmed)) return value;
  const negative = trimmed.startsWith("-");
  const [whole, fraction] = (negative ? trimmed.slice(1) : trimmed).split(".");
  const body = fraction === undefined ? groupIndian(whole) : `${groupIndian(whole)}.${fraction}`;
  return `${negative ? "-" : ""}${body}`;
}

/** Money in rupees, grouped, precision preserved (`₹1,23,456.78`). */
export function formatMoney(value: string | null | undefined): string {
  const amount = formatAmount(value);
  return amount === EM_DASH ? amount : `\u20B9${amount}`;
}
