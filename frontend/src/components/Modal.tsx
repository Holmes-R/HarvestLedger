import { useEffect, useId, useRef, type ReactNode } from "react";

const FOCUSABLE = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(",");

export interface ModalProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
  /** Rendered under the title and wired as the dialog's accessible description. */
  description?: string;
  footer?: ReactNode;
  wide?: boolean;
  role?: "dialog" | "alertdialog";
}

/**
 * Accessible modal dialog. On open it moves focus into the dialog and traps Tab
 * within it; Escape and a backdrop click close it; on close focus returns to the
 * element that opened it. `role="alertdialog"` + a description is used for
 * confirmations of financial actions.
 */
export function Modal({
  title,
  onClose,
  children,
  description,
  footer,
  wide,
  role = "dialog",
}: ModalProps) {
  const titleId = useId();
  const descriptionId = useId();
  const container = useRef<HTMLDivElement>(null);

  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const node = container.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusables = () =>
      node ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)) : [];

    (focusables()[0] ?? node)?.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !node) return;
      const items = focusables();
      if (items.length === 0) {
        event.preventDefault();
        node.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === node)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus?.();
    };
  }, []);

  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={container}
        className={wide ? "modal modal-wide" : "modal"}
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
      >
        <header className="modal-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
            ×
          </button>
        </header>
        <div className="modal-body">
          {description ? (
            <p className="modal-desc" id={descriptionId}>
              {description}
            </p>
          ) : null}
          {children}
        </div>
        {footer ? <footer className="modal-foot">{footer}</footer> : null}
      </div>
    </div>
  );
}

/** Loading state with a spinner and a polite live region. */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p className="state state-loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span className="muted">{label}</span>
    </p>
  );
}

/** Empty state (no rows yet / no matches). */
export function Empty({ children }: { children: ReactNode }) {
  return <p className="state muted">{children}</p>;
}
