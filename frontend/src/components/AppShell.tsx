import type { ReactNode } from "react";

import { navigate } from "../hooks/useHashRoute";
import { DemoClockControl } from "./DemoClockControl";

const NAV = [
  { section: "deliveries", label: "Delivery entry" },
  { section: "prices", label: "Price history" },
  { section: "payouts", label: "Weekly payouts" },
  { section: "ledger", label: "Farmer ledger" },
] as const;

export function AppShell({ active, children }: { active: string; children: ReactNode }) {
  return (
    <>
      <button
        type="button"
        className="skip-link"
        onClick={() => document.getElementById("main-content")?.focus()}
      >
        Skip to content
      </button>
      <header className="app-header">
        <div className="app-header-inner">
          <a className="brand" href="#/deliveries">
            <span className="brand-mark" aria-hidden="true">
              HL
            </span>
            HarvestLedger
          </a>
          <nav className="app-nav" aria-label="Primary">
            {NAV.map((item) => (
              <button
                key={item.section}
                type="button"
                className={item.section === active ? "nav-link nav-link-active" : "nav-link"}
                aria-current={item.section === active ? "page" : undefined}
                onClick={() => navigate(`#/${item.section}`)}
              >
                {item.label}
              </button>
            ))}
          </nav>
          <DemoClockControl />
        </div>
      </header>
      <main className="app-main" id="main-content" tabIndex={-1}>
        {children}
      </main>
    </>
  );
}

export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle ? <p className="muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-head-actions">{actions}</div> : null}
    </div>
  );
}
