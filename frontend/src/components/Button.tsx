import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "ghost" | "warn" | "danger";

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: "",
  ghost: "button-ghost",
  warn: "button-warn",
  danger: "button-danger",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** While true the control is disabled, marked `aria-busy` and shows a spinner. */
  pending?: boolean;
  /** Accessible label shown while pending (defaults to the normal label). */
  pendingLabel?: ReactNode;
  children: ReactNode;
}

/**
 * The single button primitive. Variants map to the shared `.button-*` classes so
 * every action looks the same across screens. A `pending` action control is
 * disabled and announces its busy state, which is how in-flight financial writes
 * are represented instead of a silently-dead button.
 */
export function Button({
  variant = "primary",
  pending = false,
  pendingLabel,
  children,
  className,
  disabled,
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = ["button", VARIANT_CLASS[variant], className].filter(Boolean).join(" ");
  const label = pending && pendingLabel ? pendingLabel : children;
  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      {...rest}
    >
      {pending ? <span className="spinner" aria-hidden="true" /> : null}
      <span className="button-label">{label}</span>
    </button>
  );
}
