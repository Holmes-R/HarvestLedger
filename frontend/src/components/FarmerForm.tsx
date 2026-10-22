import { useState } from "react";

import { createFarmer, updateFarmer } from "../api/endpoints";
import type { Farmer, FarmerWrite } from "../api/types";
import { fieldError } from "../util/errors";
import { isValidIndianMobile } from "../validation/phone";
import { Button } from "./Button";
import { ErrorBanner } from "./ErrorBanner";
import { Field, TextInput } from "./form";
import { Money } from "./format";
import { Modal } from "./Modal";
import { useSubmit } from "../hooks/useSubmit";

export function FarmerForm({
  farmer,
  onClose,
  onSaved,
}: {
  farmer?: Farmer;
  onClose: () => void;
  onSaved: (farmer: Farmer) => void;
}) {
  const [name, setName] = useState(farmer?.name ?? "");
  const [phone, setPhone] = useState(farmer?.phone ?? "");
  const [village, setVillage] = useState(farmer?.village ?? "");
  const [bankReference, setBankReference] = useState(farmer?.bank_reference ?? "");

  const { submitting, error, submit } = useSubmit(
    () => {
      const body: FarmerWrite = {
        name: name.trim(),
        phone: phone.trim(),
        village: village.trim(),
        bank_reference: bankReference.trim(),
      };
      return farmer ? updateFarmer(farmer.id, body) : createFarmer(body);
    },
    (saved) => onSaved(saved),
  );

  const phoneError = !phone
    ? "Required."
    : isValidIndianMobile(phone)
      ? null
      : "Enter a valid Indian mobile number (10 digits starting 6-9).";
  const nameError = name.trim() ? fieldError(error, "name") : "Required.";
  const serverPhoneError = fieldError(error, "phone");
  const villageError = village.trim() ? fieldError(error, "village") : "Required.";
  const bankError = fieldError(error, "bank_reference");
  const valid = name.trim() !== "" && village.trim() !== "" && isValidIndianMobile(phone);

  return (
    <Modal title={farmer ? `Edit farmer #${farmer.id}` : "New farmer"} onClose={onClose}>
      <form className="form" onSubmit={submit} noValidate>
        <ErrorBanner error={error} />
        {farmer ? (
          <p className="muted">
            Outstanding advance <Money value={farmer.outstanding_advance} /> is
            server-owned and read-only here.
          </p>
        ) : null}
        <Field label="Name" htmlFor="farmer-name" error={nameError}>
          <TextInput id="farmer-name" value={name} onChange={setName} required />
        </Field>
        <Field
          label="Phone"
          htmlFor="farmer-phone"
          error={phoneError ?? serverPhoneError}
          hint="10 digits starting 6, 7, 8 or 9; optional +91 and spaces."
        >
          <TextInput
            id="farmer-phone"
            value={phone}
            onChange={setPhone}
            type="tel"
            inputMode="tel"
            maxLength={16}
            invalid={Boolean(phoneError ?? serverPhoneError)}
            required
          />
        </Field>
        <Field label="Village" htmlFor="farmer-village" error={villageError}>
          <TextInput id="farmer-village" value={village} onChange={setVillage} required />
        </Field>
        <Field
          label="Bank reference (optional)"
          htmlFor="farmer-bank"
          error={bankError}
          hint="Stored for the demo only; never logged or sent to a banking service."
        >
          <TextInput id="farmer-bank" value={bankReference} onChange={setBankReference} />
        </Field>
        <div className="form-actions">
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" disabled={!valid} pending={submitting} pendingLabel="Saving...">
            {farmer ? "Save changes" : "Create farmer"}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
