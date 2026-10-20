import { useMemo, useState } from "react";

import { toApiError, type ApiError } from "../api/client";
import { generatePayout, listPayouts } from "../api/endpoints";
import type { Farmer, Payout } from "../api/types";
import { isApiDate, istToday, mondayOf, sundayOf } from "../util/dates";
import {
  classifyGeneration,
  generateEmptyMessage,
  isPayoutStateConflict,
} from "../util/payout";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { DateOnly } from "./format";
import { Field, Select, TextInput } from "./form";

/**
 * Pick a farmer and any day in a business week, then create or extend the DRAFT
 * through `POST /payouts/generate/`. The API normalises the chosen day to that
 * week's Monday; the preview here is only a label, and the returned statement's
 * `week_start`/`week_end` remain authoritative.
 */
export function PayoutGenerateForm({
  farmers,
  onGenerated,
  onChanged,
}: {
  farmers: Map<number, Farmer> | undefined;
  onGenerated: (payout: Payout) => void;
  onChanged: () => void;
}) {
  const [farmerId, setFarmerId] = useState("");
  const [weekDay, setWeekDay] = useState(istToday());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | undefined>(undefined);
  const [empty, setEmpty] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const farmerOptions = useMemo(() => {
    const rows = farmers ? [...farmers.values()] : [];
    return rows
      .map((farmer) => ({
        value: String(farmer.id),
        label: `${farmer.name} · ${farmer.village}`,
      }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [farmers]);

  const validWeek = isApiDate(weekDay);
  const monday = validWeek ? mondayOf(weekDay) : null;
  const sunday = validWeek ? sundayOf(weekDay) : null;
  const ready = farmerId !== "" && validWeek && !busy;

  async function reconcileUnknown() {
    // The POST may have committed even though the response never arrived. Read
    // the week back before offering a retry; never resend automatically.
    try {
      const page = await listPayouts({
        farmer: Number(farmerId),
        week: weekDay,
        ordering: "id",
        page_size: 100,
      });
      onChanged();
      const draft = page.results.find((payout) => payout.status === "DRAFT");
      if (draft) {
        setError(undefined);
        setNotice(
          "The request did apply despite the network error; the draft it created or extended is opening.",
        );
        onGenerated(draft);
        return;
      }
      setNotice(
        "Re-checked the week: no draft was recorded. Review the inputs before retrying; nothing was resent automatically.",
      );
    } catch {
      setNotice(
        "Could not confirm the outcome after the network error. Refresh the statements before retrying; nothing was resent automatically.",
      );
    }
  }

  async function onGenerate() {
    if (!ready) return;
    setBusy(true);
    setError(undefined);
    setEmpty(null);
    setNotice(null);
    try {
      const result = await generatePayout({
        farmer: Number(farmerId),
        // Send the chosen day: the service normalises it to Monday–Sunday.
        week_start: weekDay,
      });
      const outcome = classifyGeneration(result);
      if (outcome.kind === "draft") {
        onGenerated(outcome.payout);
      } else {
        setEmpty(generateEmptyMessage(outcome.reason));
        onChanged();
      }
    } catch (cause) {
      const apiError = toApiError(cause);
      setError(apiError);
      if (isPayoutStateConflict(apiError)) {
        onChanged();
        setNotice(
          "This week is already finalised. The statements were refreshed; a supplementary draft needs a new unassigned record.",
        );
      } else if (apiError.outcomeUnknown) {
        await reconcileUnknown();
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Select farmer and business week</h2>
      <p className="help">
        A business week is Monday–Sunday. Pick any day; the API normalises it to
        that week's Monday and reuses an existing Draft instead of duplicating it.
      </p>
      <ErrorBanner error={error} />
      {notice ? (
        <div className="banner banner-warning" role="status">
          {notice}
        </div>
      ) : null}
      {empty ? (
        <div className="banner banner-ok" role="status">
          <strong>Empty week — no payout created.</strong> {empty}
          {monday && sunday ? (
            <>
              {" "}
              Week <DateOnly value={monday} /> – <DateOnly value={sunday} />.
            </>
          ) : null}
        </div>
      ) : null}

      <div className="form-row">
        <Field label="Farmer" htmlFor="pay-farmer">
          <Select
            id="pay-farmer"
            value={farmerId}
            onChange={setFarmerId}
            placeholder={farmers ? "Select a farmer…" : "Loading farmers…"}
            options={farmerOptions}
            disabled={!farmers}
          />
        </Field>
        <Field
          label="Business week (any day)"
          htmlFor="pay-week"
          error={validWeek ? null : "Choose a valid date."}
        >
          <TextInput
            id="pay-week"
            type="date"
            value={weekDay}
            onChange={setWeekDay}
          />
        </Field>
      </div>

      {monday && sunday ? (
        <p className="help week-preview" role="status" aria-live="polite">
          Normalised week: <DateOnly value={monday} /> –{" "}
          <DateOnly value={sunday} /> (Monday–Sunday).
        </p>
      ) : null}

      <div className="form-actions">
        <Button
          onClick={onGenerate}
          disabled={!ready}
          pending={busy}
          pendingLabel="Generating…"
        >
          Generate / refresh draft
        </Button>
      </div>
    </section>
  );
}
