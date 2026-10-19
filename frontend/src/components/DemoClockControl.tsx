import { useState } from "react";

import { getDemoClock, setDemoClock } from "../api/client";
import { isApiTimestamp } from "../util/dates";
import { Field, TextInput } from "./form";

/**
 * Demo-only control for the gated reviewer clock (backend `ALLOW_REVIEW_CLOCK`).
 * It only ever sets request headers; the key is held in memory/sessionStorage
 * and is never written into the build. Leave off for normal use.
 */
export function DemoClockControl() {
  const current = getDemoClock();
  const [open, setOpen] = useState(false);
  const [clock, setClock] = useState(current.clock ?? "");
  const [key, setKey] = useState(current.reviewKey ?? "");
  const [notice, setNotice] = useState<string | null>(null);

  function apply() {
    if (clock.trim() && !isApiTimestamp(clock)) {
      setNotice(
        "Timestamp must be timezone-aware ISO-8601, e.g. 2026-12-31T23:00:00+05:30.",
      );
      return;
    }
    setDemoClock(clock || null, key || null);
    window.location.reload();
  }

  function clear() {
    setDemoClock(null, null);
    window.location.reload();
  }

  return (
    <div className="demo-clock">
      <button
        type="button"
        className={current.enabled ? "button button-warn" : "button button-ghost"}
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {current.enabled ? "Clock overridden" : "Demo clock"}
      </button>
      {open ? (
        <div className="demo-clock-panel">
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
          {notice ? <p className="field-error">{notice}</p> : null}
          <div className="demo-clock-actions">
            <button type="button" className="button" onClick={apply}>
              Apply
            </button>
            <button type="button" className="button button-ghost" onClick={clear}>
              Clear
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
