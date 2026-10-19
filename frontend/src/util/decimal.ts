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

/** Group the integer part with thousands separators, keeping the string value. */
export function groupMoney(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [whole, fraction] = unsigned.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const body = fraction === undefined ? grouped : `${grouped}.${fraction}`;
  return negative ? `-${body}` : body;
}

/** Money in rupees (display only). */
export function money(value: string | null | undefined): string {
  const grouped = groupMoney(value);
  return grouped === "—" ? grouped : `₹${grouped}`;
}
