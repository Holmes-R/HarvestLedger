import { useState } from "react";

import { createCorrection, createDeliveryCorrection } from "../api/endpoints";
import type {
  Correction,
  CorrectionWrite,
  Delivery,
  Farmer,
  GradeNoteKind,
} from "../api/types";
import { validateDecimal } from "../util/decimal";
import { fieldError } from "../util/errors";
import { useSubmit } from "../hooks/useSubmit";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { DecimalInput, Field, Select, TextInput } from "./form";
import { Modal } from "./Modal";

/**
 * Record a credit/debit note. The nested route takes the original from the URL
 * (deliveryId); the general route requires an original id (originalDeliveryId).
 * The original must already be in a Finalised/Paid payout, otherwise the API
 * returns 409 original_not_settled.
 */
export function CorrectionForm({
  deliveryId,
  originalDeliveryId,
  original,
  farmer,
  onClose,
  onSaved,
}: {
  deliveryId?: number;
  originalDeliveryId?: number;
  original?: Pick<Delivery, "id" | "farmer">;
  farmer?: Farmer;
  onClose: () => void;
  onSaved: (correction: Correction) => void;
}) {
  const [kind, setKind] = useState<GradeNoteKind>("CREDIT_NOTE");
  const [magnitude, setMagnitude] = useState("");
  const [reason, setReason] = useState("");

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

  const magnitudeShapeError = magnitude
    ? validateDecimal(magnitude, { places: 2, positive: true })
    : "Required.";
  const magnitudeError =
    magnitudeShapeError ?? fieldError(error, "magnitude");
  const reasonError = reason.trim()
    ? fieldError(error, "reason")
    : "Required.";
  const kindError = fieldError(error, "kind");
  const originalError = fieldError(error, "original_delivery");
  const valid = !magnitudeShapeError && reason.trim() !== "";
  const originalId = original?.id ?? deliveryId ?? originalDeliveryId;
  const farmerName = farmer?.name ??
    (original ? `farmer #${original.farmer}` : "the original delivery's farmer");

  return (
    <Modal
      title={originalId !== undefined ? `Correct delivery #${originalId}` : "Record correction"}
      onClose={onClose}
      description="A correction creates a new linked credit or debit note. It never edits the original delivery snapshot."
    >
      <form className="form" onSubmit={submit} noValidate>
        <ErrorBanner error={error} />
        {originalId !== undefined ? (
          <p className="muted">
            Original delivery <strong>#{originalId}</strong> for{" "}
            <strong>{farmerName}</strong>. Its weight, price and recorded amount
            stay frozen.
          </p>
        ) : null}
        <Field label="Kind" htmlFor="correction-kind" error={kindError}>
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
          label="Magnitude (INR)"
          htmlFor="correction-magnitude"
          error={magnitudeError}
          hint="Enter a positive money amount; the selected kind carries the sign."
        >
          <DecimalInput
            id="correction-magnitude"
            value={magnitude}
            onChange={setMagnitude}
            places={2}
            placeholder="Enter amount"
          />
        </Field>
        <Field label="Reason" htmlFor="correction-reason" error={reasonError}>
          <TextInput id="correction-reason" value={reason} onChange={setReason} required />
        </Field>
        {originalError ? (
          <p className="field-error" role="alert">
            <span className="err-tag">Error:</span> {originalError}
          </p>
        ) : null}
        <p className="muted">
          A credit note increases the amount due and a debit note reduces it. The
          note is stamped with today's IST business date, joins that week's payout,
          or requires a supplementary payout if the original week is already
          settled.
        </p>
        <div className="form-actions">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" disabled={!valid} pending={submitting} pendingLabel="Recording...">
            Record note
          </Button>
        </div>
      </form>
    </Modal>
  );
}
