import { useMemo, useState } from "react";

import { loadCropMap } from "../api/lookups";
import type { Crop } from "../api/types";
import { useAsync } from "../hooks/useAsync";
import { Button } from "./Button";
import { CropForm } from "./CropForm";
import { ErrorBanner } from "./ErrorBanner";
import { Field, Select } from "./form";
import { Loading, Modal } from "./Modal";

export function CropConfigDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (crop: Crop) => void;
}) {
  const crops = useAsync((signal) => loadCropMap(signal), []);
  const [cropId, setCropId] = useState("");
  const selected = cropId ? crops.data?.get(Number(cropId)) : undefined;

  const options = useMemo(
    () =>
      crops.data
        ? [...crops.data.values()]
            .map((crop) => ({ value: String(crop.id), label: crop.name }))
            .sort((a, b) => a.label.localeCompare(b.label))
        : [],
    [crops.data],
  );

  if (selected) {
    return <CropForm crop={selected} onClose={onClose} onSaved={onSaved} />;
  }

  return (
    <Modal
      title="Configure crop"
      onClose={onClose}
      description="Select an existing crop to change its moisture bounds or allowed grade set. Existing delivery snapshots are never re-priced."
    >
      <ErrorBanner error={crops.error} />
      {crops.loading ? <Loading label="Loading crops..." /> : null}
      {crops.data ? (
        <div className="form">
          <Field label="Crop" htmlFor="configure-crop">
            <Select
              id="configure-crop"
              value={cropId}
              onChange={setCropId}
              placeholder="Select a crop"
              options={options}
            />
          </Field>
          <p className="muted">
            Choosing a crop opens its configuration. Adding a grade makes it
            selectable for future deliveries and prices. Removing a grade with
            existing price or delivery history is refused with 409 grade_in_use.
          </p>
          <div className="form-actions">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </Modal>
  );
}
