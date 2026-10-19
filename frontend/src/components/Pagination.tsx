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
    <div className="pagination">
      <span className="muted">
        {count === 0 ? "No rows" : `${first}–${last} of ${count}`}
      </span>
      <div className="pagination-controls">
        <button
          type="button"
          className="button button-ghost"
          onClick={() => onPage(page - 1)}
          disabled={page <= 1}
        >
          Previous
        </button>
        <span className="muted">
          Page {page} / {totalPages}
        </span>
        <button
          type="button"
          className="button button-ghost"
          onClick={() => onPage(page + 1)}
          disabled={page >= totalPages}
        >
          Next
        </button>
      </div>
    </div>
  );
}
