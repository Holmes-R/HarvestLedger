import { useState } from "react";

import { createCrop, updateCrop } from "../api/endpoints";
import type { Crop, CropWrite } from "../api/types";
import { compareDecimal, validateDecimal } from "../util/decimal";
import { fieldError } from "../util/errors";
import { useSubmit } from "../hooks/useSubmit";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { DecimalInput, Field, TextInput } from "./form";
import { Modal } from "./Modal";

export function CropForm({
  crop,
  onClose,
  onSaved,
}: {
  crop?: Crop;
  onClose: () => void;
  onSaved: (crop: Crop) => void;
}) {
  const [name, setName] = useState(crop?.name ?? "");
  const [threshold, setThreshold] = useState(crop?.moisture_threshold ?? "");
  const [maximum, setMaximum] = useState(crop?.max_moisture ?? "");
  const [grades, setGrades] = useState(
    crop ? crop.allowed_grades.map((grade) => grade.code).join(", ") : "",
  );

  const { submitting, error, submit } = useSubmit(
    () => {
      const body: CropWrite = {
        name: name.trim(),
        moisture_threshold: threshold.trim(),
        max_moisture: maximum.trim(),
      };
      const codes = grades
        .split(",")
        .map((code) => code.trim())
        .filter(Boolean);
      if (crop || codes.length) body.allowed_grades = codes;
      return crop ? updateCrop(crop.id, body) : createCrop(body);
    },
    (saved) => onSaved(saved),
  );

  const thresholdShapeError = threshold
    ? validateDecimal(threshold, { places: 2, allowNegative: true })
    : "Required.";
  const maximumShapeError = maximum
    ? validateDecimal(maximum, { places: 2, allowNegative: true })
    : "Required.";
  const thresholdRangeError = !thresholdShapeError
    ? percentageRangeError(threshold)
    : null;
  const maximumRangeError = !maximumShapeError ? percentageRangeError(maximum) : null;
  const orderError =
    !thresholdShapeError &&
    !maximumShapeError &&
    !thresholdRangeError &&
    !maximumRangeError &&
    compareDecimal(threshold, maximum) === 1
      ? "Must be at least the moisture threshold."
      : null;

  const thresholdError =
    thresholdShapeError ??
    thresholdRangeError ??
    fieldError(error, "moisture_threshold");
  const maximumError =
    maximumShapeError ??
    maximumRangeError ??
    orderError ??
    fieldError(error, "max_moisture");
  const nameError = name.trim() ? fieldError(error, "name") : "Required.";
  const gradesError = fieldError(error, "allowed_grades");
  const valid =
    name.trim() !== "" &&
    !thresholdShapeError &&
    !thresholdRangeError &&
    !maximumShapeError &&
    !maximumRangeError &&
    !orderError;

  return (
    <Modal title={crop ? `Configure crop #${crop.id}` : "New crop"} onClose={onClose}>
      <form className="form" onSubmit={submit} noValidate>
        <ErrorBanner error={error} />
        <Field label="Name" htmlFor="crop-name" error={nameError}>
          <TextInput id="crop-name" value={name} onChange={setName} required />
        </Field>
        <div className="form-row">
          <Field label="Moisture threshold %" htmlFor="crop-threshold" error={thresholdError}>
            <DecimalInput
              id="crop-threshold"
              value={threshold}
              onChange={setThreshold}
              places={2}
              placeholder="Enter percentage"
            />
          </Field>
          <Field label="Max moisture %" htmlFor="crop-max" error={maximumError}>
            <DecimalInput
              id="crop-max"
              value={maximum}
              onChange={setMaximum}
              places={2}
              placeholder="Enter percentage"
            />
          </Field>
        </div>
        <Field
          label="Allowed grades"
          htmlFor="crop-grades"
          error={gradesError}
          hint="Comma-separated short codes. Saving replaces the crop's grade set; a grade with price or delivery history cannot be removed (409 grade_in_use)."
        >
          <TextInput
            id="crop-grades"
            value={grades}
            onChange={setGrades}
            placeholder="Comma-separated codes"
          />
        </Field>
        <p className="muted">
          Moisture configuration must satisfy 0 &lt;= threshold &lt;= maximum &lt;= 100.
          Changing it never re-prices existing deliveries.
        </p>
        <div className="form-actions">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" disabled={!valid} pending={submitting} pendingLabel="Saving...">
            {crop ? "Save crop" : "Create crop"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function percentageRangeError(value: string): string | null {
  const belowZero = compareDecimal(value, "0");
  const aboveHundred = compareDecimal(value, "100");
  if (belowZero === -1) return "Must be at least 0.";
  if (aboveHundred === 1) return "Must be at most 100.";
  return null;
}
