import { useMemo, useState } from "react";

import { generatePayout, getPayout, listPayouts, finalisePayout, markPayoutPaid } from "../api/endpoints";
import { type ApiError, toApiError } from "../api/client";
import type { Payout } from "../api/types";
import { mondayOf, istToday } from "../util/dates";
import { DELIVERY_KIND_LABEL, PAYOUT_STATUS_LABEL, deliveryKindTone, payoutStatusTone } from "../util/labels";
import { navigate } from "../hooks/useHashRoute";
import { useAsync } from "../hooks/useAsync";
import { useLookups } from "../hooks/useLookups";
import { PageHeader } from "../components/AppShell";
import { Button } from "../components/Button";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DataTable } from "../components/DataTable";
import { ErrorBanner } from "../components/ErrorBanner";
import { DateOnly, Money, Timestamp } from "../components/format";
import { Field, Select, TextInput } from "../components/form";
import { Empty, Loading } from "../components/Modal";
import { Pagination } from "../components/Pagination";
import { StatusBadge } from "../components/StatusBadge";

const PAGE_SIZE = 20;

function GenerateForm({ onGenerated }: { onGenerated: (payout: Payout) => void }) {
  const lookups = useLookups();
  const [farmerId, setFarmerId] = useState("");
  const [weekStart, setWeekStart] = useState(mondayOf(istToday()));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [notice, setNotice] = useState<string | null>(null);

  const farmerOptions = useMemo(() => {
    const farmers = lookups.data ? [...lookups.data.farmers.values()] : [];
    return farmers
      .map((farmer) => ({ value: String(farmer.id), label: `${farmer.name} · ${farmer.village}` }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [lookups.data]);

  async function onGenerate() {
    setBusy(true);
    setError(undefined);
    setNotice(null);
    try {
      const result = await generatePayout({
        farmer: Number(farmerId),
        week_start: weekStart,
      });
      if (result.payout) {
        onGenerated(result.payout);
      } else {
        setNotice(
          result.reason === "NO_ELIGIBLE_DELIVERIES"
            ? "No eligible deliveries for that week — nothing to generate."
            : `Nothing generated (${result.reason ?? "unknown reason"}).`,
        );
      }
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Generate weekly payout</h2>
      <ErrorBanner error={error} />
      {notice ? <div className="banner banner-ok">{notice}</div> : null}
      <div className="form-row">
        <Field label="Farmer" htmlFor="g-farmer">
          <Select
            id="g-farmer"
            value={farmerId}
            onChange={setFarmerId}
            placeholder="Select a farmer…"
            options={farmerOptions}
          />
        </Field>
        <Field
          label="Week (any day; normalised to Monday)"
          htmlFor="g-week"
          hint={`IST Monday: ${weekStart}`}
        >
          <TextInput
            id="g-week"
            type="date"
            value={weekStart}
            onChange={(value) => setWeekStart(mondayOf(value))}
          />
        </Field>
      </div>
      <div className="form-actions">
        <Button
          onClick={onGenerate}
          disabled={farmerId === ""}
          pending={busy}
          pendingLabel="Generating…"
        >
          Generate payout
        </Button>
      </div>
    </section>
  );
}

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
        subtitle="Mon–Sun statements. Finalise a draft, then mark it paid."
      />

      <GenerateForm
        onGenerated={(payout) => navigate(`#/payouts/${payout.id}`)}
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
                <th>Week</th>
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
                    <DateOnly value={payout.week_start} /> → <DateOnly value={payout.week_end} />
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

export function PayoutDetail({ payoutId, onBack }: { payoutId: number; onBack: () => void }) {
  const { data, error, loading, reload } = useAsync(
    (signal) => getPayout(payoutId, { signal }),
    [payoutId],
  );
  const [actionError, setActionError] = useState<ApiError | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState<null | "finalise" | "mark-paid">(null);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    setActionError(undefined);
    try {
      await action();
      setConfirming(null);
      reload();
    } catch (cause) {
      setActionError(toApiError(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <div className="panel-head">
        <button type="button" className="link-button" onClick={onBack}>
          ← Back
        </button>
        <h2>Payout #{payoutId}</h2>
        {data ? (
          <StatusBadge tone={payoutStatusTone(data.status)}>
            {PAYOUT_STATUS_LABEL[data.status]}
          </StatusBadge>
        ) : null}
      </div>

      {loading ? <Loading label="Loading payout…" /> : null}
      <ErrorBanner error={error} />
      <ErrorBanner error={actionError} />

      {data ? (
        <>
          <dl className="detail-grid">
            <dt>Farmer</dt>
            <dd>{data.farmer_name}</dd>
            <dt>Week</dt>
            <dd>
              <DateOnly value={data.week_start} /> → <DateOnly value={data.week_end} />
            </dd>
            <dt>Gross</dt>
            <dd>
              <Money value={data.gross_amount} />
            </dd>
            <dt>Advance deduction</dt>
            <dd>
              <Money value={data.advance_deduction} />
            </dd>
            <dt>Net payable</dt>
            <dd>
              <strong>
                <Money value={data.net_amount} />
              </strong>
            </dd>
            <dt>Finalised</dt>
            <dd>
              <Timestamp value={data.finalised_at} />
            </dd>
            <dt>Paid</dt>
            <dd>
              <Timestamp value={data.paid_at} />
            </dd>
          </dl>

          <h3>Statement lines</h3>
          {data.deliveries.length === 0 ? (
            <Empty>No member deliveries.</Empty>
          ) : (
            <DataTable label="Statement lines">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Date</th>
                  <th>Kind</th>
                  <th className="num">Net kg</th>
                  <th className="num">Amount</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.deliveries.map((delivery) => (
                  <tr key={delivery.id}>
                    <td className="num">{delivery.id}</td>
                    <td>
                      <DateOnly value={delivery.delivered_on ?? delivery.accounting_date} />
                    </td>
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
          )}

          <div className="panel-actions">
            {data.status === "DRAFT" ? (
              <Button onClick={() => setConfirming("finalise")} disabled={busy}>
                Finalise
              </Button>
            ) : null}
            {data.status === "FINALISED" ? (
              <Button onClick={() => setConfirming("mark-paid")} disabled={busy}>
                Mark paid
              </Button>
            ) : null}
            {data.status === "PAID" ? (
              <p className="muted">This payout is settled; later corrections need a supplementary payout.</p>
            ) : null}
          </div>

          {confirming === "finalise" ? (
            <ConfirmDialog
              title="Finalise this payout?"
              message={`Finalising statement #${data.id} locks it for ${data.farmer_name}. It can then only be marked paid, and settled corrections need a supplementary payout.`}
              confirmLabel="Finalise"
              pending={busy}
              pendingLabel="Finalising…"
              onCancel={() => setConfirming(null)}
              onConfirm={() => act(() => finalisePayout(data.id))}
            >
              <ErrorBanner error={actionError} />
            </ConfirmDialog>
          ) : null}

          {confirming === "mark-paid" ? (
            <ConfirmDialog
              title="Mark this payout paid?"
              message={`Marking statement #${data.id} paid records the money as handed over to ${data.farmer_name}. This is the final state for the week.`}
              confirmLabel="Mark paid"
              pending={busy}
              pendingLabel="Marking paid…"
              onCancel={() => setConfirming(null)}
              onConfirm={() => act(() => markPayoutPaid(data.id))}
            >
              <ErrorBanner error={actionError} />
            </ConfirmDialog>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
