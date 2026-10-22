import { useState } from "react";

import { createAdvance } from "../api/endpoints";
import type { Advance, AdvanceWrite, Farmer } from "../api/types";
import { formatMoney, validateDecimal } from "../util/decimal";
import { isApiDate, istToday } from "../util/dates";
import { fieldError } from "../util/errors";
import { useSubmit } from "../hooks/useSubmit";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { DecimalInput, Field, Select, TextInput } from "./form";
import { Money } from "./format";
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

  const selectedFarmer = farmers.find((farmer) => String(farmer.id) === farmerId);
  const amountShapeError = amount
    ? validateDecimal(amount, { places: 2, positive: true })
    : "Required.";
  const dateError = !givenOn
    ? "Select the date the advance was given."
    : isApiDate(givenOn)
      ? null
      : "Enter a valid date (YYYY-MM-DD).";
  const farmerError = farmerId ? null : "Select a farmer.";
  const amountError = amountShapeError ?? fieldError(error, "amount");
  const givenOnError = dateError ?? fieldError(error, "given_on");
  const farmerServerError = fieldError(error, "farmer");
  const valid = !farmerError && !amountShapeError && !dateError;

  return (
    <Modal title="Post advance" onClose={onClose}>
      <form className="form" onSubmit={submit} noValidate>
        <ErrorBanner error={error} />
        <Field
          label="Farmer"
          htmlFor="advance-farmer"
          error={farmerError ?? farmerServerError}
        >
          <Select
            id="advance-farmer"
            value={farmerId}
            onChange={setFarmerId}
            placeholder="Select a farmer..."
            options={farmers.map((farmer) => ({
              value: String(farmer.id),
              label: `${farmer.name} - outstanding ${formatMoney(farmer.outstanding_advance)}`,
            }))}
          />
        </Field>
        {selectedFarmer ? (
          <p className="muted">
            Current outstanding advance:{" "}
            <Money value={selectedFarmer.outstanding_advance} />. This balance is
            server-owned and read-only; posting adds the principal exactly once.
          </p>
        ) : null}
        <div className="form-row">
          <Field
            label="Amount (INR)"
            htmlFor="advance-amount"
            error={amountError}
            hint="Positive, up to 2 decimal places."
          >
            <DecimalInput
              id="advance-amount"
              value={amount}
              onChange={setAmount}
              places={2}
              placeholder="Enter amount"
            />
          </Field>
          <Field label="Given on" htmlFor="advance-date" error={givenOnError}>
            <TextInput id="advance-date" type="date" value={givenOn} onChange={setGivenOn} />
          </Field>
        </div>
        <p className="muted">
          The balance is not editable here. The server records the advance and
          returns the authoritative movement; refresh the ledger after posting.
        </p>
        <div className="form-actions">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" disabled={!valid} pending={submitting} pendingLabel="Posting...">
            Post advance
          </Button>
        </div>
      </form>
    </Modal>
  );
}
