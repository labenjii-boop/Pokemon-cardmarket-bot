import { useEffect, useState } from "react";
import { searchCards, type CardSearchResult } from "../api/client";

const LANGUAGE_LABEL: Record<string, string> = {
  en: "English",
  ja: "Japanese",
  "zh-tw": "Chinese (Traditional)",
  "zh-cn": "Chinese (Simplified)",
};

export function SearchScreen() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<CardSearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const handle = setTimeout(() => {
      searchCards(query)
        .then((r) => {
          setResults(r);
          setError(null);
        })
        .catch((err: Error) => setError(err.message));
    }, 200); // small debounce so every keystroke doesn't fire a request
    return () => clearTimeout(handle);
  }, [query]);

  return (
    <div className="flex h-full flex-col p-6">
      <h1 className="mb-1 text-xl font-semibold">Search</h1>
      <p className="mb-4 text-sm text-[var(--color-text-muted)]">
        Searches whatever's currently in the catalog — this works as soon as a catalog connector
        has run, independently of price data (see Source Status if this looks empty).
      </p>
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search by card name (English, Japanese, or Chinese)..."
        className="mb-4 w-full max-w-lg rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2"
        autoFocus
      />

      {error && (
        <p className="text-[var(--color-loss)]">Couldn't reach the backend: {error}</p>
      )}

      {!error && results.length === 0 && (
        <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-6 text-center text-[var(--color-text-muted)]">
          {query.trim() ? "No matching cards." : "No cards in the catalog yet — run a catalog import first."}
        </div>
      )}

      <div className="grid flex-1 auto-rows-min grid-cols-2 gap-3 overflow-auto sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
        {results.map((card) => (
          <div
            key={card.id}
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-2"
          >
            <div className="mb-2 aspect-[5/7] overflow-hidden rounded bg-[var(--color-surface-raised)]">
              {card.image_source_url && (
                <img
                  // TCGdex's `image` field is a base path with no quality/format suffix — the
                  // actual asset lives at "<base>/<quality>.<ext>" (Section 10: "Image storage:
                  // local folder cache" will replace this hotlinking with a real download +
                  // cache later; for now this talks straight to TCGdex's CDN). webp first
                  // (their documented default), falling back to png once, since not every
                  // quality/format combination is guaranteed to exist for every card.
                  src={`${card.image_source_url}/high.webp`}
                  onError={(e) => {
                    const img = e.currentTarget;
                    if (img.dataset.fallback !== "1") {
                      img.dataset.fallback = "1";
                      img.src = `${card.image_source_url}/high.png`;
                    }
                  }}
                  alt={card.name}
                  className="h-full w-full object-cover"
                  loading="lazy"
                />
              )}
            </div>
            <div className="truncate text-sm font-medium">{card.name}</div>
            <div className="truncate text-xs text-[var(--color-text-muted)]">
              {card.set_name} · #{card.number}
            </div>
            <div className="text-xs text-[var(--color-text-muted)]">
              {LANGUAGE_LABEL[card.language] ?? card.language}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
