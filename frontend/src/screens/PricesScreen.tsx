import { useMemo, useState } from "react";

import { createPriceEntry, listGrades, listPrices } from "../api/endpoints";
import type { ApiError } from "../api/client";
import { toApiError } from "../api/client";
import type { PriceListEntry } from "../api/types";
import { formatMoney, validateDecimal } from "../util/decimal";
import { istToday } from "../util/dates";
import { useAsync } from "../hooks/useAsync";
import { PageHeader } from "../components/AppShell";
import { Button } from "../components/Button";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { Money } from "../components/format";
import { DecimalInput, Field, Select, TextInput } from "../components/form";
import { Empty, Loading } from "../components/Modal";
import { Pagination } from "../components/Pagination";

const PAGE_SIZE = 20;

export function PricesScreen() {
  const grades = useAsync(
    (signal) => listGrades({ page_size: 100, ordering: "id" }, { signal }),
    [],
  );
  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [filterCrop, setFilterCrop] = useState("");
  const [filterGrade, setFilterGrade] = useState("");

  const [cropId, setCropId] = useState("");
  const [gradeId, setGradeId] = useState("");
  const [price, setPrice] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(istToday());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [notice, setNotice] = useState<string | null>(null);

  const allGrades = useMemo(() => grades.data?.results ?? [], [grades.data]);

  const cropOptions = useMemo(() => {
    const crops = new Map<number, string>();
    allGrades.forEach((grade) => crops.set(grade.crop, grade.crop_name));
    return [...crops.entries()].map(([id, name]) => ({ value: String(id), label: name }));
  }, [allGrades]);

  function gradesFor(crop: string) {
    return allGrades.filter((grade) => (crop ? String(grade.crop) === crop : true));
  }

  const entryGradeOptions = gradesFor(cropId).map((grade) => ({
    value: String(grade.id),
    label: `${grade.crop_name} · ${grade.code}`,
  }));
  const filterGradeOptions = gradesFor(filterCrop).map((grade) => ({
    value: String(grade.id),
    label: `${grade.crop_name} · ${grade.code}`,
  }));

  const entries = useAsync(
    (signal) =>
      listPrices(
        {
          page,
          ordering: "-effective_from",
          crop: filterCrop || undefined,
          crop_grade: filterGrade || undefined,
        },
        { signal },
      ),
    [page, refreshKey, filterCrop, filterGrade],
  );

  const priceError = price ? validateDecimal(price, { places: 2, positive: true }) : "Required.";
  const valid = gradeId !== "" && effectiveFrom !== "" && !priceError;

  async function onSubmit() {
    setError(undefined);
    setNotice(null);
    setBusy(true);
    try {
      const saved: PriceListEntry = await createPriceEntry({
        crop: Number(cropId),
        grade: Number(gradeId),
        price_per_kg: price.trim(),
        effective_from: effectiveFrom,
      });
      setNotice(
        `Recorded ${formatMoney(saved.price_per_kg)}/kg for ${saved.crop_name} ${saved.crop_grade_code} from ${saved.effective_from}.`,
      );
      setPrice("");
      setRefreshKey((value) => value + 1);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Price history"
        subtitle="Effective-dated price list entries. Deliveries resolve the latest entry on or before the business date."
      />

      <section className="panel">
        <h2>Add price entry</h2>
        <ErrorBanner error={error} />
        {notice ? <div className="banner banner-ok">{notice}</div> : null}
        <div className="form-row">
          <Field label="Crop" htmlFor="p-crop">
            <Select
              id="p-crop"
              value={cropId}
              onChange={(value) => {
                setCropId(value);
                setGradeId("");
              }}
              placeholder="Select a crop…"
              options={cropOptions}
            />
          </Field>
          <Field label="Grade" htmlFor="p-grade">
            <Select
              id="p-grade"
              value={gradeId}
              onChange={setGradeId}
              placeholder={cropId ? "Select…" : "Pick a crop first"}
              disabled={!cropId}
              options={entryGradeOptions}
            />
          </Field>
          <Field label="Price (₹/kg)" htmlFor="p-price" error={priceError}>
            <DecimalInput
              id="p-price"
              value={price}
              onChange={setPrice}
              places={2}
              placeholder="24.50"
            />
          </Field>
          <Field label="Effective from" htmlFor="p-from">
            <TextInput id="p-from" type="date" value={effectiveFrom} onChange={setEffectiveFrom} />
          </Field>
        </div>
        <div className="form-actions">
          <Button onClick={onSubmit} disabled={!valid} pending={busy} pendingLabel="Saving…">
            Add price
          </Button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Entries</h2>
          <div className="filters">
            <Select
              value={filterCrop}
              onChange={(value) => {
                setFilterCrop(value);
                setFilterGrade("");
                setPage(1);
              }}
              placeholder="All crops"
              options={cropOptions}
              ariaLabel="Filter by crop"
            />
            <Select
              value={filterGrade}
              onChange={(value) => {
                setFilterGrade(value);
                setPage(1);
              }}
              placeholder="All grades"
              options={filterGradeOptions}
              ariaLabel="Filter by grade"
            />
          </div>
        </div>
        <ErrorBanner error={entries.error} />
        {entries.loading ? <Loading /> : null}
        {entries.data && entries.data.results.length === 0 ? (
          <Empty>No price entries match.</Empty>
        ) : null}
        {entries.data && entries.data.results.length > 0 ? (
          <DataTable label="Price entries">
            <thead>
              <tr>
                <th>Effective from</th>
                <th>Crop</th>
                <th>Grade</th>
                <th className="num">Price / kg</th>
              </tr>
            </thead>
            <tbody>
              {entries.data.results.map((entry) => (
                <tr key={entry.id}>
                  <td>{entry.effective_from}</td>
                  <td>{entry.crop_name}</td>
                  <td>{entry.crop_grade_code}</td>
                  <td className="num">
                    <Money value={entry.price_per_kg} suffix=" / kg" />
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        ) : null}
        {entries.data ? (
          <Pagination
            count={entries.data.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPage={setPage}
          />
        ) : null}
      </section>
    </>
  );
}
