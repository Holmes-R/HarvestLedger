import { useState } from "react";

import { listDeliveries } from "../api/endpoints";
import { farmerLabel, gradeLabel, invalidateFarmerMap, invalidateGradeMap } from "../api/lookups";
import { DELIVERY_KIND_LABEL, deliveryKindTone } from "../util/labels";
import { navigate } from "../hooks/useHashRoute";
import { useAsync } from "../hooks/useAsync";
import { useLookups } from "../hooks/useLookups";
import { Button } from "../components/Button";
import { DataTable } from "../components/DataTable";
import { DeliveryEntryForm } from "../components/DeliveryEntryForm";
import { ErrorBanner } from "../components/ErrorBanner";
import { CropForm } from "../components/CropForm";
import { FarmerForm } from "../components/FarmerForm";
import { DateOnly, Money } from "../components/format";
import { Empty, Loading } from "../components/Modal";
import { Pagination } from "../components/Pagination";
import { StatusBadge } from "../components/StatusBadge";
import { PageHeader } from "../components/AppShell";

const PAGE_SIZE = 20;

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
            <Button variant="ghost" onClick={() => setNewFarmer(true)}>
              New farmer
            </Button>
            <Button variant="ghost" onClick={() => setNewCrop(true)}>
              New crop
            </Button>
          </>
        }
      />

      <DeliveryEntryForm
        farmers={lookups.data?.farmers}
        grades={lookups.data?.grades}
        onSaved={refreshAll}
      />

      <section className="panel">
        <h2>Recent deliveries</h2>
        <ErrorBanner error={deliveries.error} />
        {deliveries.loading ? <Loading /> : null}
        {deliveries.data && deliveries.data.results.length === 0 ? (
          <Empty>No deliveries recorded yet.</Empty>
        ) : null}
        {deliveries.data && deliveries.data.results.length > 0 ? (
          <DataTable label="Recent deliveries">
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
                  <td>
                    <DateOnly value={delivery.delivered_on ?? delivery.accounting_date} />
                  </td>
                  <td>{farmerLabel(lookups.data?.farmers, delivery.farmer)}</td>
                  <td>{gradeLabel(lookups.data?.grades, delivery.crop_grade)}</td>
                  <td>
                    <StatusBadge tone={deliveryKindTone(delivery.kind)}>
                      {DELIVERY_KIND_LABEL[delivery.kind]}
                    </StatusBadge>
                  </td>
                  <td className="num">{delivery.net_kg}</td>
                  <td className="num">
                    <Money value={delivery.amount} />
                  </td>
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
          </DataTable>
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
