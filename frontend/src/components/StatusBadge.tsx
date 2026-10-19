import type { ReactNode } from "react";

export type BadgeTone =
  | "neutral"
  | "procurement"
  | "credit"
  | "debit"
  | "draft"
  | "finalised"
  | "paid"
  | "ok"
  | "warn";

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: BadgeTone }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
