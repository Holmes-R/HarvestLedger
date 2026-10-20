import { useState } from "react";

import { toApiError, type ApiError } from "../api/client";
import { finalisePayout, getPayout, markPayoutPaid } from "../api/endpoints";
import type { Delivery, Payout } from "../api/types";
import {
  DELIVERY_KIND_LABEL,
  PAYOUT_STATUS_LABEL,
  deliveryKindTone,
  payoutStatusTone,
} from "../util/labels";
import {
  DRAFT_ADVANCE_NOTE,
  finaliseConfirmation,
  isNonPositiveMoney,
  isPayoutStateConflict,
  isSupplementary,
  markPaidConfirmation,
  nonPositiveNote,
  payoutActions,
  sameWeekStatements,
} from "../util/payout";
import { Button } from "./Button";
import { ConfirmDialog } from "./ConfirmDialog";
import { DataTable } from "./DataTable";
import { ErrorBanner } from "./ErrorBanner";
import { DateOnly, Money, Quantity, Timestamp } from "./format";
import { Empty } from "./Modal";
import { StatusBadge } from "./StatusBadge";

export interface PayoutStatementProps {
  payout: Payout;
  /** Same farmer/week statements, including this one (used to spot supplements). */
  statementSet: readonly Payout[];
  /** The farmer's stored balance, shown read-only. Refresh it after a write. */
  outstandingAdvance?: string;
  onChanged: () => void;
  onOpenPayout: (id: number) => void;
  onOpenDelivery: (id: number) => void;
  onBack: () => void;
}

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

function FinaliseEffect({
  payout,
  outstandingAdvance,
}: {
  payout: Payout;
  outstandingAdvance?: string;
}) {
  return (
    <dl className="confirm-summary">
      <dt>Farmer</dt>
      <dd>{payout.farmer_name}</dd>
      <dt>Week</dt>
      <dd>
        <DateOnly value={payout.week_start} /> –{" "}
        <DateOnly value={payout.week_end} /> (Monday–Sunday)
      </dd>
      <dt>Gross</dt>
      <dd>
        <Money value={payout.gross_amount} />
      </dd>
      <dt>Draft net</dt>
      <dd>
        <Money value={payout.net_amount} />
      </dd>
      <dt>Outstanding advance</dt>
      <dd>
        <Money value={outstandingAdvance} />{" "}
        <span className="muted">(recorded now)</span>
      </dd>
      <dt>Financial effect</dt>
      <dd>
        The server recovers min(outstanding advance, 30% of gross), floored to
        cents, and freezes the statement. Recovery is applied once and reduces
        the outstanding advance.
      </dd>
    </dl>
  );
}

function LineBreakdown({ delivery }: { delivery: Delivery }) {
  if (delivery.kind === "PROCUREMENT") {
    return (
      <span>
        <Quantity value={delivery.gross_weight_kg} unit="kg" /> @{" "}
        <Money value={delivery.applied_price} suffix="/kg" />
        <br />
        <span className="help">
          moisture <Quantity value={delivery.moisture_percent} unit="%" /> ·
          deduction <Quantity value={delivery.deduction_percent} unit="%" /> (
          <Quantity value={delivery.deduction_kg} unit="kg" />)
        </span>
      </span>
    );
  }
  return (
    <span>
      {delivery.reason}
      <br />
      <span className="help">
        magnitude <Money value={delivery.correction_magnitude} /> · recorded{" "}
        <DateOnly value={delivery.accounting_date} />
      </span>
    </span>
  );
}

/**
 * A read-only payout statement. The API owns every financial value and every
 * transition; this component only presents the stored figures, confirms the
 * intended effect, and reconciles ambiguous failures by re-reading the statement
 * before a human retries. No advance recovery is calculated here.
 */
export function PayoutStatement({
  payout,
  statementSet,
  outstandingAdvance,
  onChanged,
  onOpenPayout,
  onOpenDelivery,
  onBack,
}: PayoutStatementProps) {
  const [saved, setSaved] = useState<{
    anchor: Payout;
    payout: Payout;
  } | null>(null);
  const [action, setAction] = useState<"finalise" | "mark-paid" | null>(null);
  const [confirming, setConfirming] = useState<"finalise" | "mark-paid" | null>(
    null,
  );
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [notice, setNotice] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  // The freshly returned statement is shown immediately. It stays pinned to the
  // prop it was derived from, so a later re-fetch (a new prop object) wins again.
  const view = saved !== null && saved.anchor === payout ? saved.payout : payout;
  const actions = payoutActions(view.status);
  const siblings = sameWeekStatements(view, statementSet);
  const earlier = siblings.filter((candidate) => candidate.id < view.id);
  const later = siblings.filter((candidate) => candidate.id > view.id);
  const supplementary = isSupplementary(view, statementSet);
  const policyNote = nonPositiveNote(view);

  async function reconcile(
    expected: "FINALISED" | "PAID",
  ): Promise<boolean> {
    try {
      const fresh = await getPayout(view.id);
      const applied =
        expected === "FINALISED"
          ? fresh.status === "FINALISED" || fresh.status === "PAID"
          : fresh.status === "PAID";
      if (applied) {
        setSaved({ anchor: saved?.anchor ?? payout, payout: fresh });
        setConfirming(null);
        setError(undefined);
        setNotice(
          `The network error did not prevent the change: the server reports statement #${fresh.id} as ${fresh.status}. Nothing was resent automatically.`,
        );
        onChanged();
        return true;
      }
      setNotice(
        "Re-checked the statement after the network error: it still shows the previous status. Confirm it before retrying; nothing was resent automatically.",
      );
      onChanged();
      return false;
    } catch {
      setNotice(
        "Could not confirm the outcome after the network error. Re-fetch the statement before retrying; nothing was resent automatically.",
      );
      return false;
    }
  }

  async function run(which: "finalise" | "mark-paid") {
    if (action !== null) return;
    setAction(which);
    setError(undefined);
    setNotice(null);
    setChecking(false);
    try {
      const result =
        which === "finalise"
          ? await finalisePayout(view.id)
          : await markPayoutPaid(view.id);
      setSaved({ anchor: saved?.anchor ?? payout, payout: result });
      setConfirming(null);
      setNotice(
        which === "finalise"
          ? `Statement #${result.id} is finalised. The server applied advance recovery once; the affected balance data was refreshed.`
          : `Statement #${result.id} is marked paid. No further advance recovery was applied.`,
      );
      onChanged();
    } catch (cause) {
      const apiError = toApiError(cause);
      if (apiError.outcomeUnknown) {
        setChecking(true);
        const applied = await reconcile(
          which === "finalise" ? "FINALISED" : "PAID",
        );
        setChecking(false);
        if (applied) return;
        // Keep the dialog and the statement context so a deliberate retry is safe.
        setError(apiError);
      } else if (isPayoutStateConflict(apiError)) {
        setError(apiError);
        setConfirming(null);
        setNotice(
          "The statement changed on the server. It was refreshed; check its current status before acting again.",
        );
        onChanged();
      } else {
        // A definitive rejection: keep the statement and dialog intact.
        setError(apiError);
      }
    } finally {
      setAction(null);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <button type="button" className="link-button" onClick={onBack}>
          ← Back
        </button>
        <h2>Statement #{view.id}</h2>
        <StatusBadge tone={payoutStatusTone(view.status)}>
          {PAYOUT_STATUS_LABEL[view.status]}
        </StatusBadge>
      </div>

      {notice ? (
        <div className="banner banner-ok" role="status">
          {notice}
        </div>
      ) : null}
      {error && !confirming ? <ErrorBanner error={error} /> : null}

      {supplementary || later.length > 0 ? (
        <div className="banner banner-warning" role="status">
          <strong>
            {supplementary ? "Supplementary payout." : "Later supplement exists."}
          </strong>{" "}
          {earlier.length > 0 ? (
            <>
              This week already has{" "}
              {earlier.length === 1 ? "an earlier statement" : "earlier statements"}
              :{" "}
              {earlier.map((candidate, index) => (
                <span key={candidate.id}>
                  {index > 0 ? ", " : null}
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onOpenPayout(candidate.id)}
                  >
                    #{candidate.id} ({PAYOUT_STATUS_LABEL[candidate.status]})
                  </button>
                </span>
              ))}
              .{" "}
            </>
          ) : null}
          {later.length > 0 ? (
            <>
              Later statements for this week:{" "}
              {later.map((candidate, index) => (
                <span key={candidate.id}>
                  {index > 0 ? ", " : null}
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => onOpenPayout(candidate.id)}
                  >
                    #{candidate.id} ({PAYOUT_STATUS_LABEL[candidate.status]})
                  </button>
                </span>
              ))}
              .{" "}
            </>
          ) : null}
          {supplementary && view.status === "DRAFT"
            ? "Finalising this supplementary payout applies recovery again against the remaining outstanding advance."
            : null}
        </div>
      ) : null}

      <dl className="detail-grid">
        <dt>Farmer</dt>
        <dd>{view.farmer_name}</dd>
        <dt>Business week</dt>
        <dd>
          <DateOnly value={view.week_start} /> –{" "}
          <DateOnly value={view.week_end} />{" "}
          <span className="muted">(Monday–Sunday)</span>
        </dd>
        <dt>Outstanding advance</dt>
        <dd>
          <Money value={outstandingAdvance} />{" "}
          <span className="muted">(recorded now)</span>
        </dd>
        <dt>Created</dt>
        <dd>
          <Timestamp value={view.created_at} />
        </dd>
        <dt>Finalised</dt>
        <dd>
          <Timestamp value={view.finalised_at} />
        </dd>
        <dt>Paid</dt>
        <dd>
          <Timestamp value={view.paid_at} />
        </dd>
      </dl>

      {view.status === "DRAFT" ? (
        <>
          <div className="stat-grid statement-totals">
            <Stat label="Gross (draft)" value={view.gross_amount} />
            <Stat
              label="Estimated draft recovery"
              value={view.advance_deduction}
              note="Not yet applied"
            />
            <Stat label="Estimated draft net" value={view.net_amount} />
          </div>
          <p className="help">{DRAFT_ADVANCE_NOTE}</p>
        </>
      ) : (
        <div className="stat-grid statement-totals">
          <Stat label="Gross" value={view.gross_amount} />
          <Stat label="Advance recovered" value={view.advance_deduction} />
          <Stat label="Net payable" value={view.net_amount} />
        </div>
      )}

      {policyNote ? <p className="help">{policyNote}</p> : null}

      <h3>Statement lines</h3>
      <p className="help">
        Included deliveries and signed correction notes, exactly as stored on the
        statement. Financial values are read-only.
      </p>
      {view.deliveries.length === 0 ? (
        <Empty>No member lines.</Empty>
      ) : (
        <DataTable label="Statement lines">
          <thead>
            <tr>
              <th>#</th>
              <th>Date</th>
              <th>Kind</th>
              <th>Stored breakdown</th>
              <th className="num">Net kg</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {view.deliveries.map((delivery) => {
              const originalId = delivery.original_delivery;
              return (
                <tr key={delivery.id}>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => onOpenDelivery(delivery.id)}
                    >
                      #{delivery.id}
                    </button>
                    {originalId !== null ? (
                      <div className="help">
                        Original{" "}
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => onOpenDelivery(originalId)}
                        >
                          #{originalId}
                        </button>
                      </div>
                    ) : null}
                  </td>
                  <td>
                    <DateOnly
                      value={delivery.delivered_on ?? delivery.accounting_date}
                    />
                  </td>
                  <td>
                    <StatusBadge tone={deliveryKindTone(delivery.kind)}>
                      {DELIVERY_KIND_LABEL[delivery.kind]}
                    </StatusBadge>
                  </td>
                  <td>
                    <LineBreakdown delivery={delivery} />
                  </td>
                  <td className="num">
                    {delivery.kind === "PROCUREMENT" ? (
                      <Quantity value={delivery.net_kg} unit="kg" />
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td className="num">
                    <Money value={delivery.amount} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </DataTable>
      )}

      {actions.readOnlyReason ? (
        <div className="banner" role="status">
          <strong>Settled — read-only.</strong> {actions.readOnlyReason}
        </div>
      ) : null}

      <div className="panel-actions">
        {actions.canFinalise ? (
          <Button
            onClick={() => setConfirming("finalise")}
            disabled={action !== null}
          >
            Finalise
          </Button>
        ) : null}
        {actions.canMarkPaid ? (
          <Button
            onClick={() => setConfirming("mark-paid")}
            disabled={action !== null}
          >
            Mark paid
          </Button>
        ) : null}
      </div>

      {confirming === "finalise" ? (
        <ConfirmDialog
          title="Finalise this statement?"
          message={finaliseConfirmation(view)}
          confirmLabel="Finalise"
          pending={action === "finalise"}
          pendingLabel="Finalising…"
          onCancel={() => setConfirming(null)}
          onConfirm={() => run("finalise")}
        >
          <FinaliseEffect
            payout={view}
            outstandingAdvance={outstandingAdvance}
          />
          {isNonPositiveMoney(view.gross_amount) ? (
            <p className="help">{nonPositiveNote(view)}</p>
          ) : null}
          {checking ? (
            <p className="help" role="status" aria-live="polite">
              Re-checking the statement after an ambiguous result…
            </p>
          ) : null}
          <ErrorBanner error={error} />
        </ConfirmDialog>
      ) : null}

      {confirming === "mark-paid" ? (
        <ConfirmDialog
          title="Mark this statement paid?"
          message={markPaidConfirmation(view)}
          confirmLabel="Mark paid"
          pending={action === "mark-paid"}
          pendingLabel="Marking paid…"
          onCancel={() => setConfirming(null)}
          onConfirm={() => run("mark-paid")}
        >
          <dl className="confirm-summary">
            <dt>Farmer</dt>
            <dd>{view.farmer_name}</dd>
            <dt>Week</dt>
            <dd>
              <DateOnly value={view.week_start} /> –{" "}
              <DateOnly value={view.week_end} />
            </dd>
            <dt>Advance recovered</dt>
            <dd>
              <Money value={view.advance_deduction} />
            </dd>
            <dt>Net payable</dt>
            <dd>
              <strong>
                <Money value={view.net_amount} />
              </strong>
            </dd>
          </dl>
          <p className="help">
            Marking paid does not recover the advance again; it was recovered
            when the statement was finalised.
          </p>
          {checking ? (
            <p className="help" role="status" aria-live="polite">
              Re-checking the statement after an ambiguous result…
            </p>
          ) : null}
          <ErrorBanner error={error} />
        </ConfirmDialog>
      ) : null}
    </section>
  );
}
