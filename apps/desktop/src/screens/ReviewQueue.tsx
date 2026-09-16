import { useEffect, useState } from "react";
import { confirmMatch, fetchReviewQueue, rejectMatch, type ReviewQueueItem } from "../api/client";

export function ReviewQueueScreen() {
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = () => {
    fetchReviewQueue()
      .then(setItems)
      .catch((err: Error) => setError(err.message));
  };

  useEffect(reload, []);

  const act = async (id: number, action: "confirm" | "reject") => {
    await (action === "confirm" ? confirmMatch(id) : rejectMatch(id));
    reload();
  };

  return (
    <div className="p-6">
      <h1 className="mb-1 text-xl font-semibold">Review Queue</h1>
      <p className="mb-4 text-sm text-[var(--color-text-muted)]">
        Low-confidence sale-to-card matches land here for confirmation (Section 8). Empty today
        by construction: the connectors built so far (pokemontcg.io, TCGdex) are structured APIs
        that resolve straight to a card, with no free-text listing title to fuzzy-match — see
        DATA_SOURCES.md for why. This screen is ready for the day a real listing-based sale
        connector exists.
      </p>
      {error && <p className="text-[var(--color-loss)]">Couldn't reach the backend: {error}</p>}
      {!error && items.length === 0 && (
        <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-6 text-center text-[var(--color-text-muted)]">
          Nothing pending review.
        </div>
      )}
      <div className="grid gap-2">
        {items.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3"
          >
            <div>
              <div className="font-medium">{item.raw_title}</div>
              <div className="text-sm text-[var(--color-text-muted)]">
                {item.source_name} · confidence {(item.confidence * 100).toFixed(0)}%
              </div>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => act(item.id, "confirm")}
                className="rounded-md bg-[var(--color-gain)] px-3 py-1 text-sm text-white"
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => act(item.id, "reject")}
                className="rounded-md bg-[var(--color-loss)] px-3 py-1 text-sm text-white"
              >
                Reject
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
