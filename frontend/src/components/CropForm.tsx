import { useState } from "react";

import { createCrop, updateCrop } from "../api/endpoints";
import type { Crop, CropWrite } from "../api/types";
import { validateDecimal } from "../util/decimal";
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

  const thresholdError = threshold
    ? validateDecimal(threshold, { places: 2 })
    : "Required.";
  const maximumError = maximum ? validateDecimal(maximum, { places: 2 }) : "Required.";
  const boundsError =
    !thresholdError &&
    !maximumError &&
    Number(threshold) > Number(maximum)
      ? "Moisture threshold must not exceed the maximum."
      : null;
  const valid = name.trim() !== "" && !thresholdError && !maximumError && !boundsError;

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

  return (
    <Modal title={crop ? `Edit crop #${crop.id}` : "New crop"} onClose={onClose}>
      <form className="form" onSubmit={submit} noValidate>
        <ErrorBanner error={error} />
        <Field label="Name" htmlFor="crop-name">
          <TextInput id="crop-name" value={name} onChange={setName} required />
        </Field>
        <div className="form-row">
          <Field label="Moisture threshold %" htmlFor="crop-threshold" error={thresholdError}>
            <DecimalInput
              id="crop-threshold"
              value={threshold}
              onChange={setThreshold}
              places={2}
              placeholder="14.00"
            />
          </Field>
          <Field label="Max moisture %" htmlFor="crop-max" error={maximumError ?? boundsError}>
            <DecimalInput
              id="crop-max"
              value={maximum}
              onChange={setMaximum}
              places={2}
              placeholder="20.00"
            />
          </Field>
        </div>
        <Field
          label="Allowed grades"
          htmlFor="crop-grades"
          hint="Comma-separated short codes, e.g. A, B. Removing a grade with history is refused (409)."
        >
          <TextInput
            id="crop-grades"
            value={grades}
            onChange={setGrades}
            placeholder="A, B"
          />
        </Field>
        <div className="form-actions">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!valid} pending={submitting} pendingLabel="Saving…">
            {crop ? "Save crop" : "Create crop"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
