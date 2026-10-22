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

/**
 * Compare two decimal strings without parsing them to numbers. Returns -1, 0 or
 * 1, or null when either value is not a decimal. Safe for money, weights and
 * percentages at any scale.
 */
export function compareDecimal(left: string, right: string): -1 | 0 | 1 | null {
  const a = normalizedDecimal(left);
  const b = normalizedDecimal(right);
  if (a === null || b === null) return null;
  if (a.negative !== b.negative) return a.negative ? -1 : 1;
  const sign = (value: -1 | 1): -1 | 1 =>
    a.negative ? (value === 1 ? -1 : 1) : value;
  if (a.whole.length !== b.whole.length) {
    return sign(a.whole.length < b.whole.length ? -1 : 1);
  }
  if (a.whole !== b.whole) {
    return sign(a.whole < b.whole ? -1 : 1);
  }
  const length = Math.max(a.fraction.length, b.fraction.length);
  const aFraction = a.fraction.padEnd(length, "0");
  const bFraction = b.fraction.padEnd(length, "0");
  if (aFraction === bFraction) return 0;
  return sign(aFraction < bFraction ? -1 : 1);
}

function normalizedDecimal(
  value: string,
): { negative: boolean; whole: string; fraction: string } | null {
  const trimmed = value.trim();
  if (!isDecimal(trimmed)) return null;
  const [unsignedWhole, fraction = ""] = (
    trimmed.startsWith("-") ? trimmed.slice(1) : trimmed
  ).split(".");
  const whole = unsignedWhole.replace(/^0+(?=\d)/, "") || "0";
  const negative = trimmed.startsWith("-") && (whole !== "0" || /[1-9]/.test(fraction));
  return { negative, whole, fraction };
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
