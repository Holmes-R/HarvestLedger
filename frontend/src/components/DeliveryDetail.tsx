import { useState, type ReactNode } from "react";

import { getDelivery } from "../api/endpoints";
import { farmerLabel, gradeLabel } from "../api/lookups";
import { formatDate, formatTimestamp } from "../util/dates";
import { DELIVERY_KIND_LABEL, deliveryKindTone } from "../util/labels";
import { navigate } from "../hooks/useHashRoute";
import { useAsync } from "../hooks/useAsync";
import { useLookups } from "../hooks/useLookups";
import { CorrectionForm } from "./CorrectionForm";
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
  const lookups = useLookups();
  const { data, error, loading, reload } = useAsync(
    (signal) => getDelivery(deliveryId, { signal }),
    [deliveryId],
  );
  const [correcting, setCorrecting] = useState(false);

  const delivery = data;
  const isCorrection = delivery ? delivery.kind !== "PROCUREMENT" : false;

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

      {delivery ? (
        <>
          <dl className="detail-grid">
            <Row label="Farmer" value={farmerLabel(lookups.data?.farmers, delivery.farmer)} />
            <Row label="Grade" value={gradeLabel(lookups.data?.grades, delivery.crop_grade)} />
            <Row label="Delivered on" value={formatDate(delivery.delivered_on)} />
            <Row label="Accounting date" value={formatDate(delivery.accounting_date)} />
            {isCorrection ? (
              <>
                <Row
                  label="Original delivery"
                  value={
                    delivery.original_delivery ? (
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => navigate(`#/deliveries/${delivery.original_delivery}`)}
                      >
                        #{delivery.original_delivery}
                      </button>
                    ) : (
                      "—"
                    )
                  }
                />
                <Row label="Correction magnitude" value={`₹${delivery.correction_magnitude ?? "—"}`} />
                <Row label="Reason" value={delivery.reason || "—"} />
                <Row
                  label="Signed amount"
                  value={<strong>₹{delivery.amount ?? "—"}</strong>}
                />
              </>
            ) : (
              <>
                <Row label="Gross weight" value={`${delivery.gross_weight_kg ?? "—"} kg`} />
                <Row label="Moisture" value={`${delivery.moisture_percent ?? "—"}%`} />
                <Row label="Threshold used" value={`${delivery.threshold_used ?? "—"}%`} />
                <Row label="Deduction" value={`${delivery.deduction_percent}% · ${delivery.deduction_kg} kg`} />
                <Row label="Net weight" value={`${delivery.net_kg} kg`} />
                <Row label="Applied price" value={`₹${delivery.applied_price ?? "—"} / kg`} />
                <Row
                  label="Price entry"
                  value={delivery.price_list_entry ? `#${delivery.price_list_entry}` : "—"}
                />
                <Row label="Amount" value={<strong>₹{delivery.amount ?? "—"}</strong>} />
              </>
            )}
            <Row
              label="Payout"
              value={
                delivery.payout ? (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => navigate(`#/payouts/${delivery.payout}`)}
                  >
                    #{delivery.payout}
                  </button>
                ) : (
                  <span className="muted">not settled</span>
                )
              }
            />
            <Row label="Calculation version" value={delivery.calculation_version} />
            <Row label="Recorded at" value={formatTimestamp(delivery.recorded_at)} />
          </dl>

          {!isCorrection ? (
            <div className="panel-actions">
              <button type="button" className="button" onClick={() => setCorrecting(true)}>
                Add correction
              </button>
            </div>
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
