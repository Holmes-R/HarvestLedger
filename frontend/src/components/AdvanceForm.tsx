import { useState } from "react";

import { createAdvance } from "../api/endpoints";
import type { Advance, AdvanceWrite, Farmer } from "../api/types";
import { formatMoney, validateDecimal } from "../util/decimal";
import { istToday } from "../util/dates";
import { useSubmit } from "../hooks/useSubmit";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { DecimalInput, Field, Select, TextInput } from "./form";
import { Modal } from "./Modal";

export function AdvanceForm({
  farmers,
  defaultFarmerId,
  onClose,
  onSaved,
}: {
  farmers: Farmer[];
  defaultFarmerId?: number;
  onClose: () => void;
  onSaved: (advance: Advance) => void;
}) {
  const [farmerId, setFarmerId] = useState(
    defaultFarmerId ? String(defaultFarmerId) : "",
  );
  const [amount, setAmount] = useState("");
  const [givenOn, setGivenOn] = useState(istToday());

  const amountError = amount ? validateDecimal(amount, { places: 2, positive: true }) : "Required.";
  const valid = farmerId !== "" && !amountError && givenOn !== "";

  const { submitting, error, submit } = useSubmit(
    () => {
      const body: AdvanceWrite = {
        farmer: Number(farmerId),
        amount: amount.trim(),
        given_on: givenOn,
      };
      return createAdvance(body);
    },
    (saved) => onSaved(saved),
  );

  return (
    <Modal title="Post advance" onClose={onClose}>
      <form className="form" onSubmit={submit} noValidate>
        <ErrorBanner error={error} />
        <Field label="Farmer" htmlFor="advance-farmer">
          <Select
            id="advance-farmer"
            value={farmerId}
            onChange={setFarmerId}
            placeholder="Select a farmer…"
            options={farmers.map((farmer) => ({
              value: String(farmer.id),
              label: `${farmer.name} — outstanding ${formatMoney(farmer.outstanding_advance)}`,
            }))}
          />
        </Field>
        <div className="form-row">
          <Field
            label="Amount (₹)"
            htmlFor="advance-amount"
            error={amountError}
            hint="Positive, up to 2 decimal places."
          >
            <DecimalInput
              id="advance-amount"
              value={amount}
              onChange={setAmount}
              places={2}
              placeholder="500.00"
            />
          </Field>
          <Field label="Given on" htmlFor="advance-date">
            <TextInput id="advance-date" type="date" value={givenOn} onChange={setGivenOn} />
          </Field>
        </div>
        <p className="muted">
          The outstanding balance is server-owned and increases by the amount exactly once.
        </p>
        <div className="form-actions">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={!valid} pending={submitting} pendingLabel="Posting…">
            Post advance
          </Button>
        </div>
      </form>
    </Modal>
  );
}
