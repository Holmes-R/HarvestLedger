import type { ReactNode } from "react";

/**
 * Wrapper for the shared data tables. The inner region is keyboard-focusable and
 * scrolls horizontally, so on a phone-width screen every column — including the
 * trailing actions and the financial values — stays reachable instead of being
 * clipped or squashed.
 */
export function DataTable({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="table-wrap" role="region" aria-label={label} tabIndex={0}>
      <table className="data-table">{children}</table>
    </div>
  );
}
