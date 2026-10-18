// Keep this format aligned with Farmer.phone and its database constraint.
export const indianMobilePattern = String.raw`(?:\+91 ?)?[6-9][0-9]{4} ?[0-9]{5}`;

const exactIndianMobile = new RegExp(`^${indianMobilePattern}(?![\\s\\S])`);

export function isValidIndianMobile(value: string): boolean {
  return exactIndianMobile.test(value);
}
