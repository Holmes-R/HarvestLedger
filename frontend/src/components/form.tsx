import { createContext, useContext, useId, type ChangeEvent, type ReactNode } from "react";

/**
 * A labelled form control. `Field` owns the label, help and error text and
 * exposes the generated ids to the wrapped input through context, so the input
 * is programmatically associated with its label and with its help/error text
 * (`aria-describedby`) and is marked `aria-invalid`. Errors are then announced
 * and associated, not merely tinted red.
 */
export interface FieldProps {
  label: string;
  htmlFor?: string;
  error?: string | null;
  hint?: ReactNode;
  children: ReactNode;
}

interface FieldControl {
  inputId?: string;
  describedBy?: string;
  invalid: boolean;
}

const FieldContext = createContext<FieldControl | null>(null);

export function Field({ label, htmlFor, error, hint, children }: FieldProps) {
  const generatedId = useId();
  const inputId = htmlFor ?? generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className="field">
      <label htmlFor={inputId}>{label}</label>
      <FieldContext.Provider value={{ inputId, describedBy, invalid: Boolean(error) }}>
        {children}
      </FieldContext.Provider>
      {hint ? (
        <p className="help" id={hintId}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="field-error" id={errorId} role="alert">
          <span className="err-tag">Error:</span> {error}
        </p>
      ) : null}
    </div>
  );
}

export interface TextInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "tel" | "date";
  placeholder?: string;
  maxLength?: number;
  autoComplete?: string;
  inputMode?: "text" | "tel" | "decimal" | "numeric";
  required?: boolean;
  invalid?: boolean;
  disabled?: boolean;
  ariaLabel?: string;
}

export function TextInput({
  id,
  value,
  onChange,
  type = "text",
  placeholder,
  maxLength,
  autoComplete,
  inputMode,
  required,
  invalid,
  disabled,
  ariaLabel,
}: TextInputProps) {
  const field = useContext(FieldContext);
  const isInvalid = invalid ?? field?.invalid ?? false;

  function handle(event: ChangeEvent<HTMLInputElement>) {
    onChange(event.target.value);
  }
  return (
    <input
      id={id ?? field?.inputId}
      type={type}
      value={value}
      onChange={handle}
      placeholder={placeholder}
      maxLength={maxLength}
      autoComplete={autoComplete}
      inputMode={inputMode}
      required={required}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-describedby={field?.describedBy}
      aria-invalid={isInvalid || undefined}
    />
  );
}

export interface CoefficientInputProps extends TextInputProps {
  /** Decimal places the destination column accepts (hint only; API validates). */
  places?: number;
}

/** A text input tuned for exact decimal strings (never a number input). */
export function DecimalInput({ places = 2, placeholder, ...rest }: CoefficientInputProps) {
  return (
    <TextInput
      {...rest}
      inputMode="decimal"
      autoComplete="off"
      placeholder={placeholder ?? `e.g. ${places === 3 ? "100.125" : "24.50"}`}
    />
  );
}

export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  disabled?: boolean;
  invalid?: boolean;
  ariaLabel?: string;
}

export function Select({
  id,
  value,
  onChange,
  options,
  placeholder,
  disabled,
  invalid,
  ariaLabel,
}: SelectProps) {
  const field = useContext(FieldContext);
  const isInvalid = invalid ?? field?.invalid ?? false;

  return (
    <select
      id={id ?? field?.inputId}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-describedby={field?.describedBy}
      aria-invalid={isInvalid || undefined}
    >
      {placeholder ? <option value="">{placeholder}</option> : null}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
}
