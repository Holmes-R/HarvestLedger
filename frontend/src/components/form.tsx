import type { ChangeEvent, ReactNode } from "react";

export interface FieldProps {
  label: string;
  htmlFor?: string;
  error?: string | null;
  hint?: ReactNode;
  children: ReactNode;
}

export function Field({ label, htmlFor, error, hint, children }: FieldProps) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint ? <p className="help">{hint}</p> : null}
      {error ? (
        <p className="field-error" role="alert">
          {error}
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
}: TextInputProps) {
  function handle(event: ChangeEvent<HTMLInputElement>) {
    onChange(event.target.value);
  }
  return (
    <input
      id={id}
      type={type}
      value={value}
      onChange={handle}
      placeholder={placeholder}
      maxLength={maxLength}
      autoComplete={autoComplete}
      inputMode={inputMode}
      required={required}
      disabled={disabled}
      aria-invalid={invalid || undefined}
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
}

export function Select({
  id,
  value,
  onChange,
  options,
  placeholder,
  disabled,
  invalid,
}: SelectProps) {
  return (
    <select
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      aria-invalid={invalid || undefined}
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
