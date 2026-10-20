import { useState, type ReactNode } from "react";

import { getDelivery, getPayout } from "../api/endpoints";
import { farmerLabel, gradeLabel } from "../api/lookups";
import { deliveryLockReason } from "../util/delivery";
import { ledgerContextSuffix } from "../util/ledger";
import { DELIVERY_KIND_LABEL, deliveryKindTone } from "../util/labels";
import { navigate, useHashRoute } from "../hooks/useHashRoute";
import { useAsync } from "../hooks/useAsync";
import { useLookups } from "../hooks/useLookups";
import { Button } from "./Button";
import { CorrectionForm } from "./CorrectionForm";
import { DeliveryEditForm } from "./DeliveryEditForm";
import { DateOnly, Money, Quantity, Timestamp } from "./format";
import { ErrorBanner } from "./ErrorBanner";
import { Loading } from "./Modal";
import { StatusBadge } from "./StatusBadge";

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="detail-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

/**
 * Reusable presentation of a single delivery, fetched by id. Shared by the
 * delivery list, payout statements and ledger entries (all offer `#/deliveries/{id}`).
 */
export function DeliveryDetail({ deliveryId, onBack }: { deliveryId: number; onBack: () => void }) {
  const route = useHashRoute();
  const context = ledgerContextSuffix(route.params);
  const lookups = useLookups();
  const { data, error, loading, reload } = useAsync(
    (signal) => getDelivery(deliveryId, { signal }),
    [deliveryId],
  );
  const [correcting, setCorrecting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  const delivery = data;
  const isCorrection = delivery ? delivery.kind !== "PROCUREMENT" : false;

  const payoutId = delivery?.payout ?? null;
  const payout = useAsync(
    (signal) =>
      payoutId === null
        ? Promise.resolve(undefined)
        : getPayout(payoutId, { signal }),
    [payoutId],
  );

  const lockReason = delivery
    ? deliveryLockReason(delivery, payout.data?.status)
    : null;
  const checkingSettlement = payoutId !== null && payout.loading;

  return (
    <section className="panel">
      <div className="panel-head">
        <button type="button" className="link-button" onClick={onBack}>
          ← Back
        </button>
        <h2>Delivery #{deliveryId}</h2>
        {delivery ? (
          <StatusBadge tone={deliveryKindTone(delivery.kind)}>
            {DELIVERY_KIND_LABEL[delivery.kind]}
          </StatusBadge>
        ) : null}
      </div>

      {loading ? <Loading label="Loading delivery…" /> : null}
      <ErrorBanner error={error} />
      {notice ? (
        <div className="banner banner-ok" role="status">
          {notice}
        </div>
      ) : null}

      {delivery ? (
        <>
          <dl className="detail-grid">
            <Row label="Farmer" value={farmerLabel(lookups.data?.farmers, delivery.farmer)} />
            <Row label="Grade" value={gradeLabel(lookups.data?.grades, delivery.crop_grade)} />
            <Row label="Delivered on" value={<DateOnly value={delivery.delivered_on} />} />
            <Row label="Accounting date" value={<DateOnly value={delivery.accounting_date} />} />
            {isCorrection ? (
              <>
                <Row
                  label="Original delivery"
                  value={
                    delivery.original_delivery ? (
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => navigate(`#/deliveries/${delivery.original_delivery}${context}`)}
                      >
                        #{delivery.original_delivery}
                      </button>
                    ) : (
                      "—"
                    )
                  }
                />
                <Row
                  label="Correction magnitude"
                  value={<Money value={delivery.correction_magnitude} />}
                />
                <Row label="Reason" value={delivery.reason || "—"} />
                <Row
                  label="Signed amount"
                  value={
                    <strong>
                      <Money value={delivery.amount} />
                    </strong>
                  }
                />
              </>
            ) : (
              <>
                <Row label="Gross weight" value={<Quantity value={delivery.gross_weight_kg} unit="kg" />} />
                <Row label="Moisture" value={`${delivery.moisture_percent ?? "—"}%`} />
                <Row label="Threshold used" value={`${delivery.threshold_used ?? "—"}%`} />
                <Row label="Deduction" value={`${delivery.deduction_percent}% · ${delivery.deduction_kg} kg`} />
                <Row label="Net weight" value={<Quantity value={delivery.net_kg} unit="kg" />} />
                <Row label="Applied price" value={<Money value={delivery.applied_price} suffix=" / kg" />} />
                <Row
                  label="Price entry"
                  value={delivery.price_list_entry ? `#${delivery.price_list_entry}` : "—"}
                />
                <Row
                  label="Amount"
                  value={
                    <strong>
                      <Money value={delivery.amount} />
                    </strong>
                  }
                />
              </>
            )}
            <Row
              label="Payout"
              value={
                delivery.payout ? (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => navigate(`#/payouts/${delivery.payout}${context}`)}
                  >
                    #{delivery.payout}
                  </button>
                ) : (
                  <span className="muted">not settled</span>
                )
              }
            />
            <Row label="Calculation version" value={delivery.calculation_version} />
            <Row label="Recorded at" value={<Timestamp value={delivery.recorded_at} />} />
          </dl>

          {isCorrection ? (
            <p className="muted">
              Correction notes are immutable. Record another note rather than editing.
            </p>
          ) : (
            <>
              {lockReason ? (
                <p className="banner banner-warning" role="status">
                  <strong>Read-only.</strong> {lockReason}
                </p>
              ) : null}
              {payout.error ? (
                <p className="muted">
                  Settlement status could not be confirmed; editing is still refused by
                  the server if the payout is finalised.
                </p>
              ) : null}
              <div className="panel-actions">
                {lockReason ? null : (
                  <Button
                    onClick={() => setEditing(true)}
                    disabled={checkingSettlement || !lookups.data}
                  >
                    {checkingSettlement ? "Checking settlement…" : "Edit delivery"}
                  </Button>
                )}
                <Button variant="ghost" onClick={() => setCorrecting(true)}>
                  Add correction
                </Button>
              </div>
            </>
          )}

          {editing && !lockReason ? (
            <DeliveryEditForm
              delivery={delivery}
              grades={lookups.data?.grades}
              onClose={() => setEditing(false)}
              onSaved={(updated) => {
                setEditing(false);
                setNotice(`Delivery #${updated.id} updated.`);
                reload();
              }}
            />
          ) : null}

          {correcting ? (
            <CorrectionForm
              deliveryId={deliveryId}
              onClose={() => setCorrecting(false)}
              onSaved={() => {
                setCorrecting(false);
                reload();
              }}
            />
          ) : null}
        </>
      ) : null}
    </section>
  );
}
