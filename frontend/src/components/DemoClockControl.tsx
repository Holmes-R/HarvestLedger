import { useState } from "react";

import { getDemoClock, setDemoClock } from "../api/client";
import { isApiTimestamp } from "../util/dates";
import { Button } from "./Button";
import { Field, TextInput } from "./form";

/**
 * Demo-only control for the gated reviewer clock (backend `ALLOW_REVIEW_CLOCK`).
 * It only ever sets request headers; the clock and review key are held in
 * memory only and are never written into storage or the build. Leave off for
 * normal use.
 */
export function DemoClockControl() {
  const current = getDemoClock();
  const [open, setOpen] = useState(false);
  const [clock, setClock] = useState(current.clock ?? "");
  const [key, setKey] = useState(current.reviewKey ?? "");
  const [notice, setNotice] = useState<string | null>(null);
  const [applied, setApplied] = useState<string | null>(null);

  function apply() {
    if (clock.trim() && !isApiTimestamp(clock)) {
      setNotice(
        "Timestamp must be timezone-aware ISO-8601, e.g. 2026-12-31T23:00:00+05:30.",
      );
      return;
    }
    setDemoClock(clock || null, key || null);
    setNotice(null);
    setApplied(
      "Clock headers applied for this page session. The review key is kept in memory only.",
    );
  }

  function clear() {
    setDemoClock(null, null);
    setClock("");
    setKey("");
    setNotice(null);
    setApplied("Demo clock cleared.");
  }

  return (
    <div className="demo-clock">
      <Button
        variant={current.enabled ? "warn" : "ghost"}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="demo-clock-panel"
      >
        {current.enabled ? "Clock overridden" : "Demo clock"}
      </Button>
      {open ? (
        <div
          className="demo-clock-panel"
          id="demo-clock-panel"
          role="region"
          aria-label="Demo clock settings"
        >
          <p className="muted">
            Demo-only. Requires the backend to have <code>ALLOW_REVIEW_CLOCK=true</code> and a
            matching key. Affects business-date decisions for requests only.
          </p>
          <Field label="X-Test-Clock (ISO-8601, tz-aware)">
            <TextInput value={clock} onChange={setClock} placeholder="2026-12-31T23:00:00+05:30" />
          </Field>
          <Field label="X-Review-Key (demo secret)">
            <TextInput value={key} onChange={setKey} type="text" placeholder="demo-review-key" />
          </Field>
          {notice ? (
            <p className="field-error" role="alert">
              <span className="err-tag">Error:</span> {notice}
            </p>
          ) : null}
          {applied ? (
            <div className="banner banner-ok" role="status">
              {applied}
            </div>
          ) : null}
          <div className="demo-clock-actions">
            <Button onClick={apply}>Apply</Button>
            <Button variant="ghost" onClick={clear}>
              Clear
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
