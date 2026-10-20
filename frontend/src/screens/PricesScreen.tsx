import { useMemo, useState } from "react";

import type { PriceListEntry } from "../api/types";
import { listPrices } from "../api/endpoints";
import { loadGradeMap } from "../api/lookups";
import { useAsync } from "../hooks/useAsync";
import { cropOptionsFromGrades, gradeOptionsFromGrades, PRICE_ORDERING } from "../util/pricing";
import { PageHeader } from "../components/AppShell";
import { Button } from "../components/Button";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { DateOnly, Money, Timestamp } from "../components/format";
import { Select } from "../components/form";
import { Empty, Loading } from "../components/Modal";
import { Pagination } from "../components/Pagination";
import { PriceEntryForm } from "../components/PriceEntryForm";

const PAGE_SIZE = 20;

export function PricesScreen() {
  // Every grade (all pages), so no crop or grade is hidden by pagination.
  const grades = useAsync((signal) => loadGradeMap(signal), []);

  const [page, setPage] = useState(1);
  const [refreshKey, setRefreshKey] = useState(0);
  const [filterCrop, setFilterCrop] = useState("");
  const [filterGrade, setFilterGrade] = useState("");
  const [notice, setNotice] = useState<PriceListEntry | null>(null);

  const gradeMap = grades.data;
  const cropOptions = useMemo(() => cropOptionsFromGrades(gradeMap), [gradeMap]);
  const filterGradeOptions = useMemo(
    () => gradeOptionsFromGrades(gradeMap, filterCrop),
    [gradeMap, filterCrop],
  );

  const entries = useAsync(
    (signal) =>
      listPrices(
        {
          page,
          ordering: PRICE_ORDERING,
          crop: filterCrop || undefined,
          crop_grade: filterGrade || undefined,
        },
        { signal },
      ),
    [page, refreshKey, filterCrop, filterGrade],
  );

  function onSaved(entry: PriceListEntry) {
    // Refresh and return to the first page, but keep the current filters.
    setNotice(entry);
    setPage(1);
    setRefreshKey((value) => value + 1);
  }

  function showInHistory(entry: PriceListEntry) {
    setFilterCrop(String(entry.crop));
    setFilterGrade(String(entry.crop_grade));
    setPage(1);
    setNotice(null);
  }

  const filtered = Boolean(filterCrop || filterGrade);

  return (
    <>
      <PageHeader
        title="Price history"
        subtitle="Effective-dated price list entries. A delivery is priced with the latest entry effective on or before its date."
      />

      <section className="panel">
        <h2>Add price entry</h2>
        <p className="help">
          Price history is <strong>append-only</strong>: entries are never edited
          or deleted. Add a new effective-dated entry instead. Deliveries already
          recorded keep the price and breakdown they were saved with.
        </p>
        <ErrorBanner error={grades.error} />
        {notice ? (
          <div className="banner banner-ok" role="status">
            <p>
              Added <Money value={notice.price_per_kg} suffix=" / kg" /> for{" "}
              {notice.crop_name} {notice.crop_grade_code}, effective{" "}
              <DateOnly value={notice.effective_from} />.
            </p>
            <p className="muted">
              Existing deliveries keep the price and breakdown saved when they
              were recorded.
            </p>
            <Button variant="ghost" onClick={() => showInHistory(notice)}>
              Show this entry in history
            </Button>
          </div>
        ) : null}
        <PriceEntryForm grades={gradeMap} onSaved={onSaved} />
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
              disabled={!gradeMap}
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
              disabled={!gradeMap}
              ariaLabel="Filter by grade"
            />
          </div>
        </div>

        <ErrorBanner error={entries.error} />
        {entries.loading ? <Loading /> : null}
        {entries.data && entries.data.results.length === 0 ? (
          <Empty>
            {filtered
              ? "No price entries match these filters."
              : "No price entries yet. Add the first one above."}
          </Empty>
        ) : null}
        {entries.data && entries.data.results.length > 0 ? (
          <DataTable label="Price entries">
            <caption>
              Newest effective date first; ties are broken by id so paging is
              stable.
            </caption>
            <thead>
              <tr>
                <th>Effective from</th>
                <th>Crop</th>
                <th>Grade</th>
                <th className="num">Rate / kg</th>
                <th>Added</th>
              </tr>
            </thead>
            <tbody>
              {entries.data.results.map((entry) => (
                <tr key={entry.id}>
                  <td>
                    <DateOnly value={entry.effective_from} />
                  </td>
                  <td>{entry.crop_name}</td>
                  <td>{entry.crop_grade_code}</td>
                  <td className="num" title={`${entry.price_per_kg} / kg`}>
                    <Money value={entry.price_per_kg} suffix=" / kg" />
                  </td>
                  <td>
                    <Timestamp value={entry.created_at} />
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
