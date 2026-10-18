import { useState, type FormEvent } from "react";
import { indianMobilePattern, isValidIndianMobile } from "./validation/phone";
import "./App.css";

function App() {
  const [phone, setPhone] = useState("");
  const [touched, setTouched] = useState(false);
  const valid = isValidIndianMobile(phone);
  const showError = touched && !valid;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTouched(true);
  }

  return (
    <main className="page">
      <section className="phone-card" aria-labelledby="phone-title">
        <p className="eyebrow">HarvestLedger · Farmer details</p>
        <h1 id="phone-title">Mobile number</h1>
        <p className="intro">
          Enter an Indian mobile number to check its format.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          <label htmlFor="farmer-phone">Phone number</label>
          <input
            id="farmer-phone"
            name="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="+91 98765 43210"
            maxLength={16}
            pattern={indianMobilePattern}
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
            onBlur={() => setTouched(true)}
            aria-invalid={showError}
            aria-describedby="phone-help phone-feedback"
            required
          />
          <p id="phone-help" className="help">
            10 digits starting with 6, 7, 8, or 9. You can add +91 and spaces as
            shown.
          </p>
          <p
            id="phone-feedback"
            className={showError ? "feedback error" : "feedback"}
            role="status"
          >
            {showError
              ? "Enter a valid Indian mobile number, such as 9876543210 or +91 98765 43210."
              : touched && valid
                ? "Valid Indian mobile number."
                : ""}
          </p>
          <button type="submit">Check number</button>
        </form>
      </section>
    </main>
  );
}

export default App;
