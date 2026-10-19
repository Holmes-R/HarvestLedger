import { useMemo, useState } from "react";

import { createDelivery, listDeliveries, listGrades, previewDelivery } from "../api/endpoints";
import { ApiError, toApiError } from "../api/client";
import { farmerLabel, gradeLabel, invalidateFarmerMap, invalidateGradeMap } from "../api/lookups";
import type { Delivery, DeliveryPreview } from "../api/types";
import { validateDecimal } from "../util/decimal";
import { istToday } from "../util/dates";
import { DELIVERY_KIND_LABEL, deliveryKindTone } from "../util/labels";
import { navigate } from "../hooks/useHashRoute";
import { useAsync } from "../hooks/useAsync";
import { useLookups } from "../hooks/useLookups";
import { ErrorBanner } from "../components/ErrorBanner";
import { CropForm } from "../components/CropForm";
import { FarmerForm } from "../components/FarmerForm";
import { DecimalInput, Field, Select, TextInput } from "../components/form";
import { Empty, Loading } from "../components/Modal";
import { Pagination } from "../components/Pagination";
import { StatusBadge } from "../components/StatusBadge";
import { PageHeader } from "../components/AppShell";

const PAGE_SIZE = 20;

function DeliveryEntryForm({ onSaved }: { onSaved: (delivery: Delivery) => void }) {
  const lookups = useLookups();
  const grades = useAsync(
    (signal) => listGrades({ page_size: 100, ordering: "id" }, { signal }),
    [],
  );
  const [farmerId, setFarmerId] = useState("");
  const [cropId, setCropId] = useState("");
  const [gradeId, setGradeId] = useState("");
  const [deliveredOn, setDeliveredOn] = useState(istToday());
  const [gross, setGross] = useState("");
  const [moisture, setMoisture] = useState("");
  const [preview, setPreview] = useState<DeliveryPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | undefined>(undefined);

  const farmerOptions = useMemo(() => {
    const farmers = lookups.data ? [...lookups.data.farmers.values()] : [];
    return farmers
      .map((farmer) => ({ value: String(farmer.id), label: `${farmer.name} · ${farmer.village}` }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [lookups.data]);

  const cropOptions = useMemo(() => {
    const grades2 = grades.data?.results ?? [];
    const crops = new Map<number, string>();
    grades2.forEach((grade) => crops.set(grade.crop, grade.crop_name));
    return [...crops.entries()]
      .map(([id, name]) => ({ value: String(id), label: name }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [grades.data]);

  const gradeOptions = useMemo(() => {
    const list = grades.data?.results ?? [];
    return list
      .filter((grade) => String(grade.crop) === cropId)
      .map((grade) => ({ value: String(grade.id), label: grade.code }));
  }, [grades.data, cropId]);

  const grossError = gross ? validateDecimal(gross, { places: 3, positive: true }) : "Required.";
  const moistureError = moisture
    ? validateDecimal(moisture, { places: 2, positive: true })
    : "Required.";
  const valid =
    farmerId !== "" &&
    gradeId !== "" &&
    deliveredOn !== "" &&
    !grossError &&
    !moistureError;

  function resetPreview() {
    setPreview(null);
    setPreviewError(null);
  }

  async function onPreview() {
    resetPreview();
    setError(undefined);
    try {
      setPreview(
        await previewDelivery({
          farmer: Number(farmerId),
          crop_grade: Number(gradeId),
          delivered_on: deliveredOn,
          gross_weight_kg: gross.trim(),
          moisture_percent: moisture.trim(),
        }),
      );
    } catch (cause) {
      setPreviewError(cause instanceof Error ? cause.message : String(cause));
    }
  }

  async function onSubmit() {
    setError(undefined);
    setNotice(null);
    setBusy(true);
    try {
      const saved = await createDelivery({
        farmer: Number(farmerId),
        crop_grade: Number(gradeId),
        delivered_on: deliveredOn,
        gross_weight_kg: gross.trim(),
        moisture_percent: moisture.trim(),
      });
      setNotice(`Recorded delivery #${saved.id} for ₹${saved.amount ?? "—"}.`);
      setGross("");
      setMoisture("");
      resetPreview();
      onSaved(saved);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Record a delivery</h2>
      <ErrorBanner error={error} />
      {notice ? <div className="banner banner-ok">{notice}</div> : null}
      <div className="form-row">
        <Field label="Farmer" htmlFor="d-farmer">
          <Select
            id="d-farmer"
            value={farmerId}
            onChange={(value) => {
              setFarmerId(value);
              resetPreview();
            }}
            placeholder="Select a farmer…"
            options={farmerOptions}
          />
        </Field>
        <Field label="Crop" htmlFor="d-crop">
          <Select
            id="d-crop"
            value={cropId}
            onChange={(value) => {
              setCropId(value);
              setGradeId("");
              resetPreview();
            }}
            placeholder="Select a crop…"
            options={cropOptions}
          />
        </Field>
        <Field label="Grade" htmlFor="d-grade">
          <Select
            id="d-grade"
            value={gradeId}
            onChange={(value) => {
              setGradeId(value);
              resetPreview();
            }}
            placeholder={cropId ? "Select…" : "Pick a crop first"}
            disabled={!cropId}
            options={gradeOptions}
          />
        </Field>
      </div>
      <div className="form-row">
        <Field label="Delivered on" htmlFor="d-date">
          <TextInput
            id="d-date"
            type="date"
            value={deliveredOn}
            onChange={(value) => {
              setDeliveredOn(value);
              resetPreview();
            }}
          />
        </Field>
        <Field label="Gross weight (kg)" htmlFor="d-gross" error={grossError}>
          <DecimalInput
            id="d-gross"
            value={gross}
            onChange={(value) => {
              setGross(value);
              resetPreview();
            }}
            places={3}
            placeholder="100.125"
          />
        </Field>
        <Field
          label="Moisture %"
          htmlFor="d-moisture"
          error={moistureError}
          hint="Above the crop threshold, weight is reduced."
        >
          <DecimalInput
            id="d-moisture"
            value={moisture}
            onChange={(value) => {
              setMoisture(value);
              resetPreview();
            }}
            places={2}
            placeholder="16.00"
          />
        </Field>
      </div>

      <div className="form-actions">
        <button
          type="button"
          className="button button-ghost"
          onClick={onPreview}
          disabled={!valid}
        >
          Preview
        </button>
        <button type="button" className="button" onClick={onSubmit} disabled={!valid || busy}>
          {busy ? "Recording…" : "Record delivery"}
        </button>
      </div>
      {previewError ? <p className="field-error">{previewError}</p> : null}

      {preview ? (
        <div className="preview-grid">
          <div>
            <span className="muted">Threshold</span>
            <strong>{preview.threshold_used}%</strong>
          </div>
          <div>
            <span className="muted">Deduction</span>
            <strong>
              {preview.deduction_percent}% · {preview.deduction_kg} kg
            </strong>
          </div>
          <div>
            <span className="muted">Net weight</span>
            <strong>{preview.net_kg} kg</strong>
          </div>
          <div>
            <span className="muted">Price</span>
            <strong>₹{preview.applied_price} / kg</strong>
          </div>
          <div>
            <span className="muted">Amount</span>
            <strong>₹{preview.amount}</strong>
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function DeliveriesScreen() {
  const lookups = useLookups();
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [newFarmer, setNewFarmer] = useState(false);
  const [newCrop, setNewCrop] = useState(false);

  const deliveries = useAsync(
    (signal) => listDeliveries({ page }, { signal }),
    [page, refreshKey],
  );

  function refreshAll() {
    setPage(1);
    setRefreshKey((value) => value + 1);
  }

  return (
    <>
      <PageHeader
        title="Delivery entry"
        subtitle="Capture weigh-ins with a live preview of the stored breakdown."
        actions={
          <>
            <button type="button" className="button button-ghost" onClick={() => setNewFarmer(true)}>
              New farmer
            </button>
            <button type="button" className="button button-ghost" onClick={() => setNewCrop(true)}>
              New crop
            </button>
          </>
        }
      />

      <DeliveryEntryForm onSaved={refreshAll} />

      <section className="panel">
        <h2>Recent deliveries</h2>
        <ErrorBanner error={deliveries.error} />
        {deliveries.loading ? <Loading /> : null}
        {deliveries.data && deliveries.data.results.length === 0 ? (
          <Empty>No deliveries recorded yet.</Empty>
        ) : null}
        {deliveries.data && deliveries.data.results.length > 0 ? (
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Date</th>
                <th>Farmer</th>
                <th>Grade</th>
                <th>Kind</th>
                <th className="num">Net kg</th>
                <th className="num">Amount</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {deliveries.data.results.map((delivery) => (
                <tr key={delivery.id}>
                  <td className="num">{delivery.id}</td>
                  <td>{delivery.delivered_on ?? delivery.accounting_date ?? "—"}</td>
                  <td>{farmerLabel(lookups.data?.farmers, delivery.farmer)}</td>
                  <td>{gradeLabel(lookups.data?.grades, delivery.crop_grade)}</td>
                  <td>
                    <StatusBadge tone={deliveryKindTone(delivery.kind)}>
                      {DELIVERY_KIND_LABEL[delivery.kind]}
                    </StatusBadge>
                  </td>
                  <td className="num">{delivery.net_kg}</td>
                  <td className="num">₹{delivery.amount ?? "—"}</td>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => navigate(`#/deliveries/${delivery.id}`)}
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {deliveries.data ? (
          <Pagination
            count={deliveries.data.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPage={setPage}
          />
        ) : null}
      </section>

      {newFarmer ? (
        <FarmerForm
          onClose={() => setNewFarmer(false)}
          onSaved={() => {
            setNewFarmer(false);
            invalidateFarmerMap();
            lookups.reload();
          }}
        />
      ) : null}

      {newCrop ? (
        <CropForm
          onClose={() => setNewCrop(false)}
          onSaved={() => {
            setNewCrop(false);
            invalidateGradeMap();
            lookups.reload();
          }}
        />
      ) : null}
    </>
  );
}
