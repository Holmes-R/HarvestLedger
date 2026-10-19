import { useMemo, useState, type FormEvent } from "react";

import { editDelivery } from "../api/endpoints";
import type { CropGrade, Delivery, DeliveryEdit } from "../api/types";
import { useSubmit } from "../hooks/useSubmit";
import {
  gradeBelongsToCrop,
  validateDeliveryInputs,
} from "../util/delivery";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { DecimalInput, Field, Select, TextInput } from "./form";
import { Modal } from "./Modal";

/**
 * Edit a permitted (procurement, not in a finalised/paid payout) delivery. The
 * farmer is fixed; only the grade, date, gross weight and moisture change. The
 * server recomputes the breakdown and returns the authoritative stored result.
 */
export function DeliveryEditForm({
  delivery,
  grades,
  onClose,
  onSaved,
}: {
  delivery: Delivery;
  grades: Map<number, CropGrade> | undefined;
  onClose: () => void;
  onSaved: (delivery: Delivery) => void;
}) {
  const initialGrade =
    delivery.crop_grade !== null ? grades?.get(delivery.crop_grade) : undefined;

  const [cropId, setCropId] = useState(initialGrade ? String(initialGrade.crop) : "");
  const [gradeId, setGradeId] = useState(
    delivery.crop_grade !== null ? String(delivery.crop_grade) : "",
  );
  const [deliveredOn, setDeliveredOn] = useState(delivery.delivered_on ?? "");
  const [gross, setGross] = useState(delivery.gross_weight_kg ?? "");
  const [moisture, setMoisture] = useState(delivery.moisture_percent ?? "");

  const cropOptions = useMemo(() => {
    const crops = new Map<number, string>();
    grades?.forEach((grade) => crops.set(grade.crop, grade.crop_name));
    return [...crops.entries()]
      .map(([id, name]) => ({ value: String(id), label: name }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [grades]);

  const gradeOptions = useMemo(() => {
    return grades
      ? [...grades.values()]
          .filter((grade) => String(grade.crop) === cropId)
          .map((grade) => ({ value: String(grade.id), label: grade.code }))
          .sort((a, b) => a.label.localeCompare(b.label))
      : [];
  }, [grades, cropId]);

  const validation = validateDeliveryInputs({
    farmerId: "fixed",
    cropId,
    gradeId,
    deliveredOn,
    gross,
    moisture,
  });

  const { submitting, error, submit } = useSubmit(
    () => {
      const body: DeliveryEdit = {
        crop_grade: Number(gradeId),
        delivered_on: deliveredOn,
        gross_weight_kg: gross.trim(),
        moisture_percent: moisture.trim(),
      };
      return editDelivery(delivery.id, body);
    },
    (updated) => onSaved(updated),
  );

  function changeCrop(value: string) {
    setCropId(value);
    const selected = gradeId ? grades?.get(Number(gradeId)) : undefined;
    if (!gradeBelongsToCrop(selected, value)) setGradeId("");
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!validation.valid || submitting) return;
    void submit(event);
  }

  return (
    <Modal title={`Edit delivery #${delivery.id}`} onClose={onClose}>
      <form className="form" onSubmit={onSubmit} noValidate>
        <ErrorBanner error={error} />
        <p className="muted">
          Farmer is fixed. The grade, date, gross weight and moisture are the only
          inputs; the server recomputes the stored breakdown.
        </p>
        <div className="form-row">
          <Field label="Crop" htmlFor="de-crop" error={validation.crop}>
            <Select
              id="de-crop"
              value={cropId}
              onChange={changeCrop}
              placeholder="Select a crop…"
              options={cropOptions}
            />
          </Field>
          <Field label="Grade" htmlFor="de-grade" error={validation.grade}>
            <Select
              id="de-grade"
              value={gradeId}
              onChange={setGradeId}
              placeholder={cropId ? "Select…" : "Pick a crop first"}
              disabled={!cropId}
              options={gradeOptions}
            />
          </Field>
        </div>
        <div className="form-row">
          <Field label="Delivered on" htmlFor="de-date" error={validation.date}>
            <TextInput
              id="de-date"
              type="date"
              value={deliveredOn}
              onChange={setDeliveredOn}
            />
          </Field>
          <Field label="Gross weight (kg)" htmlFor="de-gross" error={validation.gross}>
            <DecimalInput
              id="de-gross"
              value={gross}
              onChange={setGross}
              places={3}
              placeholder="100.125"
            />
          </Field>
          <Field label="Moisture %" htmlFor="de-moisture" error={validation.moisture}>
            <DecimalInput
              id="de-moisture"
              value={moisture}
              onChange={setMoisture}
              places={2}
              placeholder="16.00"
            />
          </Field>
        </div>
        <div className="form-actions">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            type="submit"
            disabled={!validation.valid}
            pending={submitting}
            pendingLabel="Saving…"
          >
            Save changes
          </Button>
        </div>
      </form>
    </Modal>
  );
}
