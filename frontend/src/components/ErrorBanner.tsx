import { ApiError } from "../api/client";

export function ErrorBanner({
  error,
  onDismiss,
}: {
  error: ApiError | null | undefined;
  onDismiss?: () => void;
}) {
  if (!error) return null;
  const fields = error.fieldMessages();
  return (
    <div className="banner banner-error" role="alert" aria-atomic="true">
      <div className="banner-head">
        <strong>
          <span className="banner-severity">Error</span>
          {" · "}
          {error.code}
          {error.status ? ` · HTTP ${error.status}` : ""}
        </strong>
        {onDismiss ? (
          <button type="button" className="link-button" onClick={onDismiss}>
            Dismiss
          </button>
        ) : null}
      </div>
      <p>{error.message}</p>
      {fields.length ? (
        <ul>
          {fields.map((line, index) => (
            <li key={index}>{line}</li>
          ))}
        </ul>
      ) : null}
      {error.requestId ? <p className="banner-meta">request_id: {error.requestId}</p> : null}
      {error.isWrite && error.outcomeUnknown ? (
        <p className="banner-warning" role="status">
          This write may or may not have been applied. Re-check the record before
          retrying — a network failure does not prove nothing was saved.
        </p>
      ) : null}
    </div>
  );
}
