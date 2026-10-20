import { useEffect, useMemo, useState } from "react";

import { isAbortError, toApiError, type ApiError } from "../api/client";
import { getFarmer, getPayout, listPayouts } from "../api/endpoints";
import type { Payout } from "../api/types";
import { navigate, useHashRoute } from "../hooks/useHashRoute";
import { useAsync } from "../hooks/useAsync";
import { useLookups } from "../hooks/useLookups";
import { PageHeader } from "../components/AppShell";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { DateOnly, Money } from "../components/format";
import { Select } from "../components/form";
import { Empty, Loading } from "../components/Modal";
import { Pagination } from "../components/Pagination";
import { PayoutGenerateForm } from "../components/PayoutGenerateForm";
import { PayoutStatement } from "../components/PayoutStatement";
import { StatusBadge } from "../components/StatusBadge";
import {
  PAYOUT_STATUS_LABEL,
  payoutStatusTone,
} from "../util/labels";
import { ledgerContextSuffix } from "../util/ledger";

const PAGE_SIZE = 20;

export function PayoutsScreen() {
  const lookups = useLookups();
  const [page, setPage] = useState(1);
  const [filterFarmer, setFilterFarmer] = useState("");
  const [filterStatus, setFilterStatus] = useState("");

  const farmerOptions = useMemo(() => {
    const farmers = lookups.data ? [...lookups.data.farmers.values()] : [];
    return farmers
      .map((farmer) => ({ value: String(farmer.id), label: farmer.name }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [lookups.data]);

  const payouts = useAsync(
    (signal) =>
      listPayouts(
        {
          page,
          ordering: "-week_start",
          farmer: filterFarmer || undefined,
          status: filterStatus || undefined,
        },
        { signal },
      ),
    [page, filterFarmer, filterStatus],
  );

  return (
    <>
      <PageHeader
        title="Weekly payouts"
        subtitle="Monday–Sunday statements. Generate a Draft, confirm its effect, finalise it, then mark it paid."
      />

      <PayoutGenerateForm
        farmers={lookups.data?.farmers}
        onGenerated={(payout) => navigate(`#/payouts/${payout.id}`)}
        onChanged={payouts.reload}
      />

      <section className="panel">
        <div className="panel-head">
          <h2>Statements</h2>
          <div className="filters">
            <Select
              value={filterFarmer}
              onChange={(value) => {
                setFilterFarmer(value);
                setPage(1);
              }}
              placeholder="All farmers"
              options={farmerOptions}
              ariaLabel="Filter by farmer"
            />
            <Select
              value={filterStatus}
              onChange={(value) => {
                setFilterStatus(value);
                setPage(1);
              }}
              placeholder="All statuses"
              ariaLabel="Filter by status"
              options={[
                { value: "DRAFT", label: "Draft" },
                { value: "FINALISED", label: "Finalised" },
                { value: "PAID", label: "Paid" },
              ]}
            />
          </div>
        </div>
        <ErrorBanner error={payouts.error} />
        {payouts.loading ? <Loading /> : null}
        {payouts.data && payouts.data.results.length === 0 ? (
          <Empty>No payouts match.</Empty>
        ) : null}
        {payouts.data && payouts.data.results.length > 0 ? (
          <DataTable label="Payout statements">
            <thead>
              <tr>
                <th>#</th>
                <th>Week (Mon–Sun)</th>
                <th>Farmer</th>
                <th>Status</th>
                <th className="num">Gross</th>
                <th className="num">Advance</th>
                <th className="num">Net</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {payouts.data.results.map((payout) => (
                <tr key={payout.id}>
                  <td className="num">{payout.id}</td>
                  <td>
                    <DateOnly value={payout.week_start} /> –{" "}
                    <DateOnly value={payout.week_end} />
                  </td>
                  <td>{payout.farmer_name}</td>
                  <td>
                    <StatusBadge tone={payoutStatusTone(payout.status)}>
                      {PAYOUT_STATUS_LABEL[payout.status]}
                    </StatusBadge>
                  </td>
                  <td className="num">
                    <Money value={payout.gross_amount} />
                  </td>
                  <td className="num">
                    <Money value={payout.advance_deduction} />
                  </td>
                  <td className="num">
                    <Money value={payout.net_amount} />
                  </td>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => navigate(`#/payouts/${payout.id}`)}
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        ) : null}
        {payouts.data ? (
          <Pagination
            count={payouts.data.count}
            page={page}
            pageSize={PAGE_SIZE}
            onPage={setPage}
          />
        ) : null}
      </section>
    </>
  );
}

interface DetailData {
  payout: Payout;
  statementSet: Payout[];
  outstanding: string;
}

interface DetailState {
  id: number | null;
  token: number;
  data?: DetailData;
  error?: ApiError;
}

function usePayoutDetail(payoutId: number) {
  const [token, setToken] = useState(0);
  const [state, setState] = useState<DetailState>({ id: null, token: -1 });

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const payout = await getPayout(payoutId, { signal: controller.signal });
        // Read the week back so supplementary statements are visible, and the
        // farmer so the balance shown with the statement is refreshed together.
        const [sameWeek, farmer] = await Promise.all([
          listPayouts(
            {
              farmer: payout.farmer,
              week: payout.week_start,
              ordering: "id",
              page_size: 100,
            },
            { signal: controller.signal },
          ),
          getFarmer(payout.farmer, { signal: controller.signal }),
        ]);
        if (controller.signal.aborted) return;
        setState({
          id: payoutId,
          token,
          data: {
            payout,
            statementSet: sameWeek.results,
            outstanding: farmer.outstanding_advance,
          },
        });
      } catch (cause) {
        if (controller.signal.aborted || isAbortError(cause)) return;
        setState((prev) => ({
          id: payoutId,
          token,
          data: prev.id === payoutId ? prev.data : undefined,
          error: toApiError(cause),
        }));
      }
    })();
    return () => controller.abort();
  }, [payoutId, token]);

  // A reload keeps the statement mounted (only the first load shows a spinner);
  // changing payout id starts clean, so another farmer's figures never linger.
  const settled = state.id === payoutId && state.token === token;
  return {
    data: state.id === payoutId ? state.data : undefined,
    error: settled ? state.error : undefined,
    loading: !settled,
    reload: () => setToken((value) => value + 1),
  };
}

export function PayoutDetail({
  payoutId,
  onBack,
}: {
  payoutId: number;
  onBack: () => void;
}) {
  const route = useHashRoute();
  const context = ledgerContextSuffix(route.params);
  const detail = usePayoutDetail(payoutId);
  const view = detail.data;

  return (
    <>
      {detail.loading && view ? (
        <p className="help" role="status" aria-live="polite">
          Refreshing statement…
        </p>
      ) : null}
      {detail.loading && !view ? <Loading label="Loading payout…" /> : null}
      <ErrorBanner error={detail.error} />
      {view ? (
        <PayoutStatement
          payout={view.payout}
          statementSet={view.statementSet}
          outstandingAdvance={view.outstanding}
          onChanged={detail.reload}
          onOpenPayout={(id) => navigate(`#/payouts/${id}${context}`)}
          onOpenDelivery={(id) => navigate(`#/deliveries/${id}${context}`)}
          onBack={onBack}
        />
      ) : null}
    </>
  );
}
