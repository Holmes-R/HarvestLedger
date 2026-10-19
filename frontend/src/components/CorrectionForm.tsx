import { useState } from "react";

import { createCorrection, createDeliveryCorrection } from "../api/endpoints";
import type { Correction, CorrectionWrite, GradeNoteKind } from "../api/types";
import { validateDecimal } from "../util/decimal";
import { useSubmit } from "../hooks/useSubmit";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { DecimalInput, Field, Select, TextInput } from "./form";
import { Modal } from "./Modal";

/**
 * Record a credit/debit note. The nested route takes the original from the URL
 * (deliveryId); the general route requires an original id (originalDeliveryId).
 * The original must already be settled, otherwise the API returns
 * 409 original_not_settled.
 */
export function CorrectionForm({
  deliveryId,
  originalDeliveryId,
  onClose,
  onSaved,
}: {
  deliveryId?: number;
  originalDeliveryId?: number;
  onClose: () => void;
  onSaved: (correction: Correction) => void;
}) {
  const [kind, setKind] = useState<GradeNoteKind>("CREDIT_NOTE");
  const [magnitude, setMagnitude] = useState("");
  const [reason, setReason] = useState("");

  const magnitudeError = magnitude
    ? validateDecimal(magnitude, { places: 2, positive: true })
    : "Required.";
  const valid = !magnitudeError && reason.trim() !== "";

  const { submitting, error, submit } = useSubmit(
    () => {
      if (deliveryId !== undefined) {
        return createDeliveryCorrection(deliveryId, {
          kind,
          magnitude: magnitude.trim(),
          reason: reason.trim(),
        });
      }
      const body: CorrectionWrite = {
        original_delivery: originalDeliveryId ?? 0,
        kind,
        magnitude: magnitude.trim(),
        reason: reason.trim(),
      };
      return createCorrection(body);
    },
    (saved) => onSaved(saved),
  );

  return (
    <Modal
      title={deliveryId !== undefined ? `Correct delivery #${deliveryId}` : "Record correction"}
      onClose={onClose}
    >
      <form className="form" onSubmit={submit} noValidate>
        <ErrorBanner error={error} />
        <Field label="Kind" htmlFor="correction-kind">
          <Select
            id="correction-kind"
            value={kind}
            onChange={(value) => setKind(value as GradeNoteKind)}
            options={[
              { value: "CREDIT_NOTE", label: "Credit note (adds to payout)" },
              { value: "DEBIT_NOTE", label: "Debit note (subtracts from payout)" },
            ]}
          />
        </Field>
        <Field
          label="Magnitude (₹)"
          htmlFor="correction-magnitude"
          error={magnitudeError}
          hint="A positive money amount; the kind carries the sign."
        >
          <DecimalInput
            id="correction-magnitude"
            value={magnitude}
            onChange={setMagnitude}
            places={2}
            placeholder="245.00"
          />
        </Field>
        <Field label="Reason" htmlFor="correction-reason">
          <TextInput id="correction-reason" value={reason} onChange={setReason} required />
        </Field>
        <p className="muted">
          The note is stamped with today's IST business date and joins that week's payout, or
          needs a supplementary payout if the week is settled.
        </p>
        <div className="form-actions">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!valid} pending={submitting} pendingLabel="Recording…">
            Record note
          </Button>
        </div>
      </form>
    </Modal>
  );
}
