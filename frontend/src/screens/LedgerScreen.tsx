import { useMemo, useState } from "react";

import { getLedger } from "../api/endpoints";
import type { LedgerEvent } from "../api/types";
import { formatTimestamp } from "../util/dates";
import { LEDGER_EVENT_LABEL } from "../util/labels";
import { navigate } from "../hooks/useHashRoute";
import { useAsync } from "../hooks/useAsync";
import { useLookups } from "../hooks/useLookups";
import { PageHeader } from "../components/AppShell";
import { ErrorBanner } from "../components/ErrorBanner";
import { Field, Select, TextInput } from "../components/form";
import { Empty, Loading } from "../components/Modal";
import { Pagination } from "../components/Pagination";
import { StatusBadge, type BadgeTone } from "../components/StatusBadge";

const PAGE_SIZE = 20;

function eventTone(event: LedgerEvent): BadgeTone {
  if (event.event_type === "ADVANCE") return "warn";
  if (event.event_type === "PAYOUT") return "paid";
  if (event.event_type === "CORRECTION") {
    return event.delivery?.kind === "DEBIT_NOTE" ? "debit" : "credit";
  }
  return "procurement";
}

function eventDescription(event: LedgerEvent): string {
  if (event.event_type === "ADVANCE") return `Advance #${event.id}`;
  if (event.event_type === "PAYOUT") return `Payout #${event.id}`;
  if (event.event_type === "CORRECTION") {
    const kind = event.delivery?.kind === "DEBIT_NOTE" ? "Debit note" : "Credit note";
    return `${kind} #${event.id}`;
  }
  return `Delivery #${event.id}`;
}

export function LedgerScreen() {
  const lookups = useLookups();
  const [farmerId, setFarmerId] = useState("");
  const [page, setPage] = useState(1);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [eventType, setEventType] = useState("");

  const farmerOptions = useMemo(() => {
    const farmers = lookups.data ? [...lookups.data.farmers.values()] : [];
    return farmers
      .map((farmer) => ({ value: String(farmer.id), label: `${farmer.name} · ${farmer.village}` }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [lookups.data]);

  const ledger = useAsync(
    (signal) =>
      farmerId === ""
        ? Promise.resolve(undefined)
        : getLedger(
            Number(farmerId),
            {
              page,
              ordering: "-date",
              from: from || undefined,
              to: to || undefined,
              event_type: eventType || undefined,
            },
            { signal },
          ),
    [farmerId, page, from, to, eventType],
  );

  const summary = ledger.data?.summary;

  function resetTo(fn: () => void) {
    setPage(1);
    fn();
  }

  return (
    <>
      <PageHeader
        title="Farmer ledger"
        subtitle="Advances, deliveries, corrections and payouts with the outstanding balance reconciled against them."
      />

      <section className="panel">
        <div className="form-row">
          <Field label="Farmer" htmlFor="l-farmer">
            <Select
              id="l-farmer"
              value={farmerId}
              onChange={(value) => resetTo(() => setFarmerId(value))}
              placeholder="Select a farmer…"
              options={farmerOptions}
            />
          </Field>
          <Field label="From" htmlFor="l-from">
            <TextInput
              id="l-from"
              type="date"
              value={from}
              onChange={(value) => resetTo(() => setFrom(value))}
            />
          </Field>
          <Field label="To" htmlFor="l-to">
            <TextInput
              id="l-to"
              type="date"
              value={to}
              onChange={(value) => resetTo(() => setTo(value))}
            />
          </Field>
          <Field label="Event type" htmlFor="l-type">
            <Select
              id="l-type"
              value={eventType}
              onChange={(value) => resetTo(() => setEventType(value))}
              placeholder="All events"
              options={[
                { value: "DELIVERY", label: "Deliveries" },
                { value: "CORRECTION", label: "Corrections" },
                { value: "ADVANCE", label: "Advances" },
                { value: "PAYOUT", label: "Payouts" },
              ]}
            />
          </Field>
        </div>
      </section>

      {farmerId === "" ? (
        <section className="panel">
          <Empty>Select a farmer to view their ledger.</Empty>
        </section>
      ) : (
        <>
          <ErrorBanner error={ledger.error} />

          {summary ? (
            <section className="panel">
              <div className="panel-head">
                <h2>{summary.name}</h2>
                <StatusBadge tone={summary.is_reconciled ? "ok" : "warn"}>
                  {summary.is_reconciled ? "Reconciled" : "Mismatch"}
                </StatusBadge>
              </div>
              <div className="stat-grid">
                <div className="stat">
                  <span className="muted">Outstanding advance</span>
                  <strong>₹{summary.outstanding_advance}</strong>
                </div>
                <div className="stat">
                  <span className="muted">Settled earnings</span>
                  <strong>₹{summary.settled_earnings}</strong>
                </div>
                <div className="stat">
                  <span className="muted">Total advances</span>
                  <strong>₹{summary.total_advances}</strong>
                </div>
                <div className="stat">
                  <span className="muted">Total recovered</span>
                  <strong>₹{summary.total_recovered}</strong>
                </div>
                <div className="stat">
                  <span className="muted">Draft projection</span>
                  <strong>₹{summary.draft_projection}</strong>
                </div>
                <div className="stat">
                  <span className="muted">Unassigned earnings</span>
                  <strong>₹{summary.unassigned_earnings}</strong>
                </div>
              </div>
              <p className="muted">
                Reconciliation difference ₹{summary.reconciliation.difference} ·{" "}
                {summary.reconciliation.is_reconciled
                  ? "stored balance matches advances minus recoveries."
                  : "stored balance does not match the recomputed balance."}{" "}
                {summary.earnings_identity_holds
                  ? "Earnings identity holds."
                  : "Earnings identity does not hold."}
              </p>
              {summary.history_from || summary.history_to ? (
                <p className="muted">
                  History window {summary.history_from ?? "—"} → {summary.history_to ?? "—"}.
                </p>
              ) : null}
            </section>
          ) : null}

          <section className="panel">
            <h2>Timeline</h2>
            {ledger.loading ? <Loading /> : null}
            {ledger.data && ledger.data.results.length === 0 ? (
              <Empty>No events in this window.</Empty>
            ) : null}
            {ledger.data && ledger.data.results.length > 0 ? (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Event</th>
                    <th>Detail</th>
                    <th className="num">Amount</th>
                    <th>Recorded</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {ledger.data.results.map((event) => (
                    <tr key={`${event.event_type}-${event.id}`}>
                      <td>{event.date}</td>
                      <td>
                        <StatusBadge tone={eventTone(event)}>
                          {LEDGER_EVENT_LABEL[event.event_type]}
                        </StatusBadge>
                      </td>
                      <td>{eventDescription(event)}</td>
                      <td className="num">₹{event.amount}</td>
                      <td>{formatTimestamp(event.advance?.created_at ?? null)}</td>
                      <td>
                        {event.event_type === "DELIVERY" || event.event_type === "CORRECTION" ? (
                          <button
                            type="button"
                            className="link-button"
                            onClick={() => navigate(`#/deliveries/${event.id}`)}
                          >
                            View
                          </button>
                        ) : event.event_type === "PAYOUT" ? (
                          <button
                            type="button"
                            className="link-button"
                            onClick={() => navigate(`#/payouts/${event.id}`)}
                          >
                            View
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {ledger.data ? (
              <Pagination
                count={ledger.data.count}
                page={page}
                pageSize={PAGE_SIZE}
                onPage={setPage}
              />
            ) : null}
          </section>
        </>
      )}
    </>
  );
}
