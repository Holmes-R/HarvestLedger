import { Button } from "./Button";

export function Pagination({
  count,
  page,
  pageSize,
  onPage,
}: {
  count: number;
  page: number;
  pageSize: number;
  onPage: (page: number) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(count / pageSize));
  const first = count === 0 ? 0 : (page - 1) * pageSize + 1;
  const last = Math.min(count, page * pageSize);
  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="muted" aria-live="polite">
        {count === 0 ? "No rows" : `${first}–${last} of ${count}`}
      </span>
      <div className="pagination-controls">
        <Button
          variant="ghost"
          onClick={() => onPage(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          Previous
        </Button>
        <span className="muted">
          Page {page} / {totalPages}
        </span>
        <Button
          variant="ghost"
          onClick={() => onPage(page + 1)}
          disabled={page >= totalPages}
          aria-label="Next page"
        >
          Next
        </Button>
      </div>
    </nav>
  );
}
