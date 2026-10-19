import { useMemo, useState, type FormEvent } from "react";

import { toApiError, type ApiError } from "../api/client";
import { createDelivery } from "../api/endpoints";
import type {
  CropGrade,
  Delivery,
  DeliveryPreview,
  DeliveryWrite,
  Farmer,
} from "../api/types";
import { useDeliveryPreview } from "../hooks/useDeliveryPreview";
import { navigate } from "../hooks/useHashRoute";
import {
  comparePreviewToStored,
  gradeBelongsToCrop,
  validateDeliveryInputs,
} from "../util/delivery";
import { istToday } from "../util/dates";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { DateOnly, Money, Quantity, Timestamp } from "./format";
import { DecimalInput, Field, Select, TextInput } from "./form";

export interface DeliveryEntryFormProps {
  farmers: Map<number, Farmer> | undefined;
  grades: Map<number, CropGrade> | undefined;
  onSaved: (delivery: Delivery) => void;
}

function optionsFromFarmers(farmers: Map<number, Farmer> | undefined) {
  return farmers
    ? [...farmers.values()]
        .map((farmer) => ({
          value: String(farmer.id),
          label: `${farmer.name} · ${farmer.village}`,
        }))
        .sort((a, b) => a.label.localeCompare(b.label))
    : [];
}

function cropOptionsFromGrades(grades: Map<number, CropGrade> | undefined) {
  const crops = new Map<number, string>();
  grades?.forEach((grade) => crops.set(grade.crop, grade.crop_name));
  return [...crops.entries()]
    .map(([id, name]) => ({ value: String(id), label: name }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

function gradeOptionsFor(grades: Map<number, CropGrade> | undefined, cropId: string) {
  return grades
    ? [...grades.values()]
        .filter((grade) => String(grade.crop) === cropId)
        .map((grade) => ({ value: String(grade.id), label: grade.code }))
        .sort((a, b) => a.label.localeCompare(b.label))
    : [];
}

function previewErrorMessage(error: ApiError): string {
  if (error.code === "price_not_found") {
    return "No effective price for this grade on that date. Add a price entry first, then the preview will update.";
  }
  if (error.code === "moisture_exceeds_maximum") {
    return `Moisture is above the crop maximum. ${error.message}`;
  }
  if (error.code === "future_delivery_date") {
    return "The delivery date is in the future for the effective business date.";
  }
  return `${error.code}: ${error.message}`;
}

function PreviewPanel({ preview }: { preview: DeliveryPreview }) {
  return (
    <div className="preview-grid" role="group" aria-label="Delivery preview">
      <div>
        <span className="muted">Applied price</span>
        <strong>
          <Money value={preview.applied_price} suffix=" / kg" />
        </strong>
      </div>
      <div>
        <span className="muted">Price entry</span>
        <strong>#{preview.price_list_entry}</strong>
      </div>
      <div>
        <span className="muted">Deduction</span>
        <strong>
          <Quantity value={preview.deduction_percent} unit="%" /> ·{" "}
          <Quantity value={preview.deduction_kg} unit="kg" />
        </strong>
      </div>
      <div>
        <span className="muted">Net weight</span>
        <strong>
          <Quantity value={preview.net_kg} unit="kg" />
        </strong>
      </div>
      <div>
        <span className="muted">Amount</span>
        <strong>
          <Money value={preview.amount} />
        </strong>
      </div>
      <div>
        <span className="muted">Accounting date</span>
        <strong>
          <DateOnly value={preview.accounting_date} />
        </strong>
      </div>
      <div>
        <span className="muted">Business date</span>
        <strong>
          <DateOnly value={preview.business_date} />
        </strong>
      </div>
      <div>
        <span className="muted">Threshold</span>
        <strong>
          <Quantity value={preview.threshold_used} unit="%" />
        </strong>
      </div>
    </div>
  );
}

function StoredResult({
  delivery,
  preview,
}: {
  delivery: Delivery;
  preview: DeliveryPreview | null;
}) {
  const comparison = preview ? comparePreviewToStored(preview, delivery) : null;
  return (
    <div className="stored-result">
      <h3>Recorded delivery #{delivery.id}</h3>
      <div className="preview-grid" role="group" aria-label="Stored delivery breakdown">
        <div>
          <span className="muted">Gross weight</span>
          <strong>
            <Quantity value={delivery.gross_weight_kg} unit="kg" />
          </strong>
        </div>
        <div>
          <span className="muted">Moisture</span>
          <strong>
            <Quantity value={delivery.moisture_percent} unit="%" />
          </strong>
        </div>
        <div>
          <span className="muted">Threshold</span>
          <strong>
            <Quantity value={delivery.threshold_used} unit="%" />
          </strong>
        </div>
        <div>
          <span className="muted">Deduction</span>
          <strong>
            <Quantity value={delivery.deduction_percent} unit="%" /> ·{" "}
            <Quantity value={delivery.deduction_kg} unit="kg" />
          </strong>
        </div>
        <div>
          <span className="muted">Net weight</span>
          <strong>
            <Quantity value={delivery.net_kg} unit="kg" />
          </strong>
        </div>
        <div>
          <span className="muted">Applied price</span>
          <strong>
            <Money value={delivery.applied_price} suffix=" / kg" />
          </strong>
        </div>
        <div>
          <span className="muted">Price entry</span>
          <strong>{delivery.price_list_entry ? `#${delivery.price_list_entry}` : "—"}</strong>
        </div>
        <div>
          <span className="muted">Amount</span>
          <strong>
            <Money value={delivery.amount} />
          </strong>
        </div>
        <div>
          <span className="muted">Accounting date</span>
          <strong>
            <DateOnly value={delivery.accounting_date} />
          </strong>
        </div>
        <div>
          <span className="muted">Recorded at</span>
          <strong>
            <Timestamp value={delivery.recorded_at} />
          </strong>
        </div>
      </div>

      <div className="panel-actions">
        <Button variant="ghost" onClick={() => navigate(`#/deliveries/${delivery.id}`)}>
          Open delivery
        </Button>
      </div>

      {comparison ? (
        comparison.changed ? (
          <div className="banner banner-warning" role="status">
            <strong>Stored result differs from the preview.</strong> The stored
            values are authoritative.
            {comparison.amountDelta ? <p>Amount change: {comparison.amountDelta}</p> : null}
            <ul>
              {comparison.fields
                .filter((field) => field.changed)
                .map((field) => (
                  <li key={field.key}>
                    {field.label}: preview {field.preview ?? "—"} → stored{" "}
                    {field.stored ?? "—"}
                  </li>
                ))}
            </ul>
          </div>
        ) : (
          <p className="banner banner-ok" role="status">
            Stored result matches the preview.
          </p>
        )
      ) : (
        <p className="muted">No preview was available before saving; these are the stored values.</p>
      )}
    </div>
  );
}

export function DeliveryEntryForm({ farmers, grades, onSaved }: DeliveryEntryFormProps) {
  const [farmerId, setFarmerId] = useState("");
  const [cropId, setCropId] = useState("");
  const [gradeId, setGradeId] = useState("");
  const [deliveredOn, setDeliveredOn] = useState(istToday());
  const [gross, setGross] = useState("");
  const [moisture, setMoisture] = useState("");
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<ApiError | undefined>(undefined);
  const [saved, setSaved] = useState<{
    delivery: Delivery;
    preview: DeliveryPreview | null;
  } | null>(null);

  const farmerOptions = useMemo(() => optionsFromFarmers(farmers), [farmers]);
  const cropOptions = useMemo(() => cropOptionsFromGrades(grades), [grades]);
  const gradeOptions = useMemo(() => gradeOptionsFor(grades, cropId), [grades, cropId]);

  const validation = validateDeliveryInputs({
    farmerId,
    cropId,
    gradeId,
    deliveredOn,
    gross,
    moisture,
  });

  const previewBody: DeliveryWrite | null = validation.valid
    ? {
        farmer: Number(farmerId),
        crop_grade: Number(gradeId),
        delivered_on: deliveredOn,
        gross_weight_kg: gross.trim(),
        moisture_percent: moisture.trim(),
      }
    : null;

  const preview = useDeliveryPreview(previewBody);

  function changeCrop(value: string) {
    setCropId(value);
    const selected = gradeId ? grades?.get(Number(gradeId)) : undefined;
    if (!gradeBelongsToCrop(selected, value)) setGradeId("");
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validation.valid || !previewBody || busy) return;

    const previewSnapshot = preview.preview ?? null;
    setBusy(true);
    setSaveError(undefined);
    try {
      const delivery = await createDelivery(previewBody);
      setSaved({ delivery, preview: previewSnapshot });
      setGross("");
      setMoisture("");
      onSaved(delivery);
    } catch (cause) {
      // Preserve every input on failure so the user can correct and resubmit.
      setSaveError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  const referenceReady = Boolean(farmers && grades);
  const status = !referenceReady
    ? "Loading reference data…"
    : !validation.valid
      ? "Complete the farmer, crop, grade, date, gross weight and moisture to preview."
      : preview.loading
        ? "Updating preview…"
        : "Preview is up to date.";

  return (
    <section className="panel">
      <h2>Record a delivery</h2>
      <ErrorBanner error={saveError} />

      <form className="form" onSubmit={onSubmit} noValidate>
        <div className="form-row">
          <Field label="Farmer" htmlFor="d-farmer" error={validation.farmer}>
            <Select
              id="d-farmer"
              value={farmerId}
              onChange={setFarmerId}
              placeholder="Select a farmer…"
              options={farmerOptions}
              disabled={!referenceReady}
            />
          </Field>
          <Field label="Crop" htmlFor="d-crop" error={validation.crop}>
            <Select
              id="d-crop"
              value={cropId}
              onChange={changeCrop}
              placeholder="Select a crop…"
              options={cropOptions}
              disabled={!referenceReady}
            />
          </Field>
          <Field label="Grade" htmlFor="d-grade" error={validation.grade}>
            <Select
              id="d-grade"
              value={gradeId}
              onChange={setGradeId}
              placeholder={cropId ? "Select…" : "Pick a crop first"}
              disabled={!cropId}
              options={gradeOptions}
            />
          </Field>
        </div>

        <div className="form-row">
          <Field label="Delivered on" htmlFor="d-date" error={validation.date}>
            <TextInput
              id="d-date"
              type="date"
              value={deliveredOn}
              onChange={setDeliveredOn}
              disabled={!referenceReady}
            />
          </Field>
          <Field label="Gross weight (kg)" htmlFor="d-gross" error={validation.gross}>
            <DecimalInput
              id="d-gross"
              value={gross}
              onChange={setGross}
              places={3}
              placeholder="100.125"
              disabled={!referenceReady}
            />
          </Field>
          <Field
            label="Moisture %"
            htmlFor="d-moisture"
            error={validation.moisture}
            hint="Above the crop threshold, weight is reduced."
          >
            <DecimalInput
              id="d-moisture"
              value={moisture}
              onChange={setMoisture}
              places={2}
              placeholder="16.00"
              disabled={!referenceReady}
            />
          </Field>
        </div>

        <div className="form-actions">
          <Button
            type="submit"
            disabled={!validation.valid}
            pending={busy}
            pendingLabel="Recording…"
          >
            Record delivery
          </Button>
        </div>

        <p className="muted" role="status" aria-live="polite">
          {status}
        </p>
      </form>

      {preview.error ? (
        <p className="field-error" role="alert">
          <span className="err-tag">Preview unavailable</span>{" "}
          {previewErrorMessage(preview.error)}
        </p>
      ) : null}

      {preview.preview ? <PreviewPanel preview={preview.preview} /> : null}

      {saved ? <StoredResult delivery={saved.delivery} preview={saved.preview} /> : null}
    </section>
  );
}
