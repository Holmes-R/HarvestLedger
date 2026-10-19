import type { ReactNode } from "react";

import { Button, type ButtonVariant } from "./Button";
import { Modal } from "./Modal";

/**
 * Accessible confirmation for a consequential action. Rendered as an
 * `alertdialog` with the message wired as its description, an initial focus
 * inside the dialog, Escape/backdrop to cancel, and focus restored to the
 * trigger on close. The confirm control carries the pending state so the caller
 * can show an in-flight financial write.
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "primary",
  pending = false,
  pendingLabel,
  onConfirm,
  onCancel,
  children,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: ButtonVariant;
  pending?: boolean;
  pendingLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}) {
  return (
    <Modal
      title={title}
      description={message}
      role="alertdialog"
      onClose={pending ? () => undefined : onCancel}
    >
      {children}
      <div className="form-actions confirm-actions">
        <Button variant="ghost" onClick={onCancel} disabled={pending}>
          {cancelLabel}
        </Button>
        <Button
          variant={tone}
          onClick={onConfirm}
          pending={pending}
          pendingLabel={pendingLabel ?? `${confirmLabel}…`}
        >
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
