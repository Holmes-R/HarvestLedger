import { useState } from "react";

import { createFarmer, updateFarmer } from "../api/endpoints";
import type { Farmer, FarmerWrite } from "../api/types";
import { isValidIndianMobile } from "../validation/phone";
import { ErrorBanner } from "./ErrorBanner";
import { Field, TextInput } from "./form";
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

  const phoneError = phone && !isValidIndianMobile(phone)
    ? "Enter a valid Indian mobile number (10 digits starting 6–9)."
    : null;
  const valid = name.trim() !== "" && village.trim() !== "" && isValidIndianMobile(phone);

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

  return (
    <Modal title={farmer ? `Edit farmer #${farmer.id}` : "New farmer"} onClose={onClose}>
      <form className="form" onSubmit={submit} noValidate>
        <ErrorBanner error={error} />
        <Field label="Name" htmlFor="farmer-name">
          <TextInput id="farmer-name" value={name} onChange={setName} required />
        </Field>
        <Field
          label="Phone"
          htmlFor="farmer-phone"
          error={phoneError}
          hint="10 digits starting 6, 7, 8 or 9; optional +91 and spaces."
        >
          <TextInput
            id="farmer-phone"
            value={phone}
            onChange={setPhone}
            type="tel"
            inputMode="tel"
            maxLength={16}
            invalid={Boolean(phoneError)}
            required
          />
        </Field>
        <Field label="Village" htmlFor="farmer-village">
          <TextInput id="farmer-village" value={village} onChange={setVillage} required />
        </Field>
        <Field label="Bank reference (optional)" htmlFor="farmer-bank">
          <TextInput id="farmer-bank" value={bankReference} onChange={setBankReference} />
        </Field>
        <div className="form-actions">
          <button type="button" className="button button-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="button" disabled={!valid || submitting}>
            {submitting ? "Saving…" : farmer ? "Save changes" : "Create farmer"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
