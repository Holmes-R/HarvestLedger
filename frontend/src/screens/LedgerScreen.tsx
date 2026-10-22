import { useMemo, useState } from "react";

import { getLedger } from "../api/endpoints";
import { invalidateFarmerMap } from "../api/lookups";
import type { LedgerEvent } from "../api/types";
import {
  LEDGER_EVENT_LABEL,
  PAYOUT_STATUS_LABEL,
  deliveryKindTone,
  payoutStatusTone,
} from "../util/labels";
import {
  LEDGER_PAGE_SIZE,
  LEDGER_SCOPE_NOTE,
  NO_DOUBLE_COUNT_NOTE,
  RECONCILIATION_HINT,
  RECOVERY_POLICY_NOTE,
  earningsIdentityText,
  isLedgerFiltered,
  ledgerAmountMeaning,
  ledgerContextLink,
  ledgerDeliveryPayoutLabel,
  ledgerEmptyMessage,
  ledgerEventTitle,
  ledgerEventTone,
  ledgerPayoutStateNote,
  payoutArithmeticWarnings,
} from "../util/ledger";
import { navigate, replaceHash } from "../hooks/useHashRoute";
import { useAsync } from "../hooks/useAsync";
import { useLookups } from "../hooks/useLookups";
import { PageHeader } from "../components/AppShell";
import { AdvanceForm } from "../components/AdvanceForm";
import { Button } from "../components/Button";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { FarmerForm } from "../components/FarmerForm";
import { DateOnly, Money, Quantity, Timestamp } from "../components/format";
import { Field, Select, TextInput } from "../components/form";
import { Empty, Loading } from "../components/Modal";
import { Pagination } from "../components/Pagination";
import { StatusBadge } from "../components/StatusBadge";

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="stat">
      <span className="muted">{label}</span>
      <strong>
        <Money value={value} />
      </strong>
      {note ? <span className="stat-note">{note}</span> : null}
    </div>
  );
}

function EventDetail({
  event,
  farmerId,
}: {
  event: LedgerEvent;
  farmerId: string;
}) {
  const delivery = event.delivery;

  if (event.event_type === "DELIVERY" && delivery) {
    return (
      <>
        <strong>{ledgerEventTitle(event)}</strong>
        <div className="help">
          Net <Quantity value={delivery.net_kg} unit="kg" /> at{" "}
          <Money value={delivery.applied_price} suffix=" / kg" />
        </div>
      </>
    );
  }

  if (event.event_type === "CORRECTION" && delivery) {
    return (
      <>
        <strong>{ledgerEventTitle(event)}</strong>
        <div className="help">{delivery.reason || "No reason recorded."}</div>
        <div className="help">
          Magnitude <Money value={delivery.correction_magnitude} />
          {delivery.original_delivery !== null ? (
            <>
              {" "}
              - original{" "}
              <button
                type="button"
                className="link-button"
                onClick={() =>
                  navigate(
                    ledgerContextLink(
                      "deliveries",
                      delivery.original_delivery as number,
                      farmerId,
                    ),
                  )
                }
              >
                #{delivery.original_delivery}
              </button>
            </>
          ) : null}
        </div>
      </>
    );
  }

  if (event.event_type === "ADVANCE" && event.advance) {
    return (
      <>
        <strong>{ledgerEventTitle(event)}</strong>
        <div className="help">
          Recorded <Timestamp value={event.advance.created_at} />
        </div>
      </>
    );
  }

  if (event.event_type === "PAYOUT" && event.payout) {
    const payout = event.payout;
    const warnings = payoutArithmeticWarnings(payout);
    return (
      <>
        <strong>{ledgerEventTitle(event)}</strong>{" "}
        <StatusBadge tone={payoutStatusTone(payout.status)}>
          {PAYOUT_STATUS_LABEL[payout.status]}
        </StatusBadge>
        <div className="help">
          Week <DateOnly value={payout.week_start} /> -{" "}
          <DateOnly value={payout.week_end} />
        </div>
        <div className="help">
          Gross <Money value={payout.gross_amount} />;{" "}
          {payout.is_draft ? "recovery not yet applied" : "recovery applied"}{" "}
          <Money value={payout.advance_deduction} />; net{" "}
          <Money value={payout.net_amount} />
        </div>
        <div className="help">{ledgerPayoutStateNote(payout)}</div>
        {warnings.map((warning) => (
          <div className="help" key={warning}>
            Warning: {warning}
          </div>
        ))}
      </>
    );
  }

  return <strong>{ledgerEventTitle(event)}</strong>;
}

function EventState({
  event,
  farmerId,
}: {
  event: LedgerEvent;
  farmerId: string;
}) {
  if (event.event_type === "PAYOUT" && event.payout) {
    const payout = event.payout;
    return (
      <>
        <span>
          {payout.is_draft
            ? "Draft projection"
            : payout.status === "FINALISED"
              ? "Finalised, awaiting payment"
              : "Paid and settled"}
        </span>
        {payout.finalised_at ? (
          <div className="help">
            Finalised <Timestamp value={payout.finalised_at} />
          </div>
        ) : null}
        {payout.paid_at ? (
          <div className="help">
            Paid <Timestamp value={payout.paid_at} />
          </div>
        ) : null}
      </>
    );
  }

  if (event.event_type === "ADVANCE") {
    return <span className="muted">Given to farmer</span>;
  }

  if (event.delivery) {
    const payoutId = event.delivery.payout;
    const label = ledgerDeliveryPayoutLabel(event.delivery);
    if (payoutId === null) return <span className="muted">{label}</span>;
    return (
      <button
        type="button"
        className="link-button"
        onClick={() =>
          navigate(ledgerContextLink("payouts", payoutId, farmerId))
        }
      >
        {label}
      </button>
    );
  }

  return null;
}

export function LedgerScreen({
  initialFarmerId = "",
}: {
  initialFarmerId?: string;
}) {
  const lookups = useLookups();
  const [farmerId, setFarmerId] = useState(initialFarmerId);
  const [page, setPage] = useState(1);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [eventType, setEventType] = useState("");
  const [editingFarmer, setEditingFarmer] = useState(false);
  const [postingAdvance, setPostingAdvance] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const farmerOptions = useMemo(() => {
    const farmers = lookups.data ? [...lookups.data.farmers.values()] : [];
    return farmers
      .map((farmer) => ({
        value: String(farmer.id),
        label: `${farmer.name} - ${farmer.village}`,
      }))
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
  const selectedFarmer = farmerId
    ? lookups.data?.farmers.get(Number(farmerId))
    : undefined;
  const hasFilters = isLedgerFiltered(from, to, eventType);

  function resetTo(update: () => void) {
    setPage(1);
    update();
  }

  function selectFarmer(value: string) {
    resetTo(() => setFarmerId(value));
    setNotice(null);
    replaceHash(value ? `#/ledger?farmer=${value}` : "#/ledger");
  }

  function clearFilters() {
    resetTo(() => {
      setFrom("");
      setTo("");
      setEventType("");
    });
  }

  return (
    <>
      <PageHeader
        title="Farmer ledger"
        subtitle="Advances, deliveries, corrections and payouts with the authoritative outstanding balance and reconciliation."
        actions={
          farmerId ? (
            <>
              {selectedFarmer ? (
                <>
                  <Button variant="ghost" onClick={() => setEditingFarmer(true)}>
                    Edit farmer
                  </Button>
                  <Button variant="ghost" onClick={() => setPostingAdvance(true)}>
                    Post advance
                  </Button>
                </>
              ) : null}
              <Button
                variant="ghost"
                onClick={ledger.reload}
                pending={ledger.loading}
                pendingLabel="Refreshing ledger"
              >
                Refresh ledger
              </Button>
            </>
          ) : undefined
        }
      />

      <section className="panel">
        <div className="form-row">
          <Field label="Farmer" htmlFor="l-farmer">
            <Select
              id="l-farmer"
              value={farmerId}
              onChange={selectFarmer}
              placeholder="Select a farmer"
              options={farmerOptions}
              disabled={!lookups.data}
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

      {lookups.error ? <ErrorBanner error={lookups.error} /> : null}
      {notice ? (
        <div className="banner banner-ok" role="status">
          {notice}
        </div>
      ) : null}

      {farmerId === "" ? (
        <section className="panel">
          <Empty>Select a farmer to view their ledger.</Empty>
        </section>
      ) : (
        <>
          <ErrorBanner error={ledger.error} />

          {ledger.loading && !ledger.data ? (
            <Loading label="Loading ledger" />
          ) : null}

          {summary ? (
            <section className="panel">
              <div className="panel-head">
                <h2>{summary.name}</h2>
                <StatusBadge tone={summary.is_reconciled ? "ok" : "warn"}>
                  {summary.is_reconciled ? "Reconciled" : "Mismatch"}
                </StatusBadge>
                <span className="muted">Farmer #{summary.farmer_id}</span>
              </div>

              <dl className="detail-grid">
                <dt>Phone</dt>
                <dd>{summary.phone}</dd>
                <dt>Village</dt>
                <dd>
                  {selectedFarmer?.village ?? (
                    <span className="muted">Not loaded</span>
                  )}
                </dd>
                <dt>Bank reference</dt>
                <dd>{selectedFarmer?.bank_reference || "Not recorded"}</dd>
                <dt>Outstanding advance</dt>
                <dd>
                  <strong>
                    <Money value={summary.outstanding_advance} />
                  </strong>{" "}
                  <span className="muted">stored balance</span>
                </dd>
              </dl>

              <div className="stat-grid statement-totals">
                <Stat label="Total advances" value={summary.total_advances} />
                <Stat
                  label="Total recovered"
                  value={summary.total_recovered}
                  note="Finalised or paid payouts only"
                />
                <Stat
                  label="Settled earnings"
                  value={summary.settled_earnings}
                  note="Finalised or paid payouts"
                />
                <Stat
                  label="Draft projection"
                  value={summary.draft_projection}
                  note="Not yet applied"
                />
                <Stat
                  label="Unassigned earnings"
                  value={summary.unassigned_earnings}
                  note="Not in a payout yet"
                />
                <Stat
                  label="Total recorded"
                  value={summary.total_recorded_amount}
                  note="Every delivery and note, counted once"
                />
              </div>

              <p className="help">{LEDGER_SCOPE_NOTE}</p>

              <h3>Advance reconciliation</h3>
              <dl className="detail-grid">
                <dt>Expected outstanding</dt>
                <dd>
                  <Money value={summary.reconciliation.expected_outstanding} />
                </dd>
                <dt>Stored outstanding</dt>
                <dd>
                  <Money value={summary.reconciliation.stored_outstanding} />
                </dd>
                <dt>Difference</dt>
                <dd>
                  <Money value={summary.reconciliation.difference} />
                </dd>
              </dl>
              <p className="help">{RECONCILIATION_HINT}</p>

              <p className="help">{NO_DOUBLE_COUNT_NOTE}</p>
              <p className="help">{RECOVERY_POLICY_NOTE}</p>
              <p className="help">
                <strong>Earnings identity:</strong>{" "}
                {earningsIdentityText(summary)}{" "}
                <StatusBadge tone={summary.earnings_identity_holds ? "ok" : "warn"}>
                  {summary.earnings_identity_holds
                    ? "Holds"
                    : "Does not hold"}
                </StatusBadge>
              </p>
            </section>
          ) : null}

          <section className="panel">
            <div className="panel-head">
              <h2>Timeline</h2>
              {ledger.data ? (
                <span className="muted">
                  {ledger.data.count} event
                  {ledger.data.count === 1 ? "" : "s"}
                </span>
              ) : null}
            </div>
            <p className="help">
              Events are newest first and bounded to {LEDGER_PAGE_SIZE} per page.
              The account summary above always covers the full history, so a page
              never changes the balance.
            </p>
            {summary?.history_from || summary?.history_to ? (
              <p className="help">
                Showing events from {summary.history_from ?? "the beginning"} to{" "}
                {summary.history_to ?? "now"}.
              </p>
            ) : null}

            {ledger.data && ledger.data.results.length === 0 ? (
              <>
                <Empty>{ledgerEmptyMessage(hasFilters)}</Empty>
                {hasFilters ? (
                  <Button variant="ghost" onClick={clearFilters}>
                    Clear filters
                  </Button>
                ) : null}
              </>
            ) : null}

            {ledger.data && ledger.data.results.length > 0 ? (
              <DataTable label="Ledger timeline">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Event</th>
                    <th>Detail</th>
                    <th className="num">Amount</th>
                    <th>State</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {ledger.data.results.map((event) => (
                    <tr key={`${event.event_type}-${event.id}`}>
                      <td>
                        <DateOnly value={event.date} />
                      </td>
                      <td>
                        <StatusBadge tone={ledgerEventTone(event)}>
                          {LEDGER_EVENT_LABEL[event.event_type]}
                        </StatusBadge>
                        {event.delivery &&
                        event.delivery.kind !== "PROCUREMENT" ? (
                          <>
                            <br />
                            <StatusBadge
                              tone={deliveryKindTone(event.delivery.kind)}
                            >
                              {event.delivery.kind === "DEBIT_NOTE"
                                ? "Debit note"
                                : "Credit note"}
                            </StatusBadge>
                          </>
                        ) : null}
                      </td>
                      <td>
                        <EventDetail event={event} farmerId={farmerId} />
                      </td>
                      <td className="num">
                        <Money value={event.amount} />
                        <div className="help">
                          {ledgerAmountMeaning(event)}
                        </div>
                      </td>
                      <td>
                        <EventState event={event} farmerId={farmerId} />
                      </td>
                      <td>
                        {event.event_type === "DELIVERY" ||
                        event.event_type === "CORRECTION" ? (
                          <button
                            type="button"
                            className="link-button"
                            onClick={() =>
                              navigate(
                                ledgerContextLink(
                                  "deliveries",
                                  event.id,
                                  farmerId,
                                ),
                              )
                            }
                          >
                            Open delivery
                          </button>
                        ) : event.event_type === "PAYOUT" ? (
                          <button
                            type="button"
                            className="link-button"
                            onClick={() =>
                              navigate(
                                ledgerContextLink("payouts", event.id, farmerId),
                              )
                            }
                          >
                            Open payout
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            ) : null}

            {ledger.data ? (
              <Pagination
                count={ledger.data.count}
                page={page}
                pageSize={LEDGER_PAGE_SIZE}
                onPage={setPage}
              />
            ) : null}
          </section>
        </>
      )}

      {editingFarmer && selectedFarmer ? (
        <FarmerForm
          farmer={selectedFarmer}
          onClose={() => setEditingFarmer(false)}
          onSaved={(updated) => {
            setEditingFarmer(false);
            setNotice(`Farmer #${updated.id} updated. The ledger has been refreshed.`);
            invalidateFarmerMap();
            lookups.reload();
            ledger.reload();
          }}
        />
      ) : null}

      {postingAdvance && selectedFarmer && lookups.data ? (
        <AdvanceForm
          farmers={[...lookups.data.farmers.values()]}
          defaultFarmerId={selectedFarmer.id}
          onClose={() => setPostingAdvance(false)}
          onSaved={(advance) => {
            setPostingAdvance(false);
            setNotice(
              `Advance #${advance.id} posted. The authoritative balance has been refreshed.`,
            );
            invalidateFarmerMap();
            lookups.reload();
            ledger.reload();
          }}
        />
      ) : null}
    </>
  );
}
