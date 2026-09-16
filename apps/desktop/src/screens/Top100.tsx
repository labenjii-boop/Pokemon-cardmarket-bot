import { useEffect, useState } from "react";
import { fetchTop100, type SortKey, type TimeRange, type Top100Entry } from "../api/client";
import { CardImage } from "../components/CardImage";

const TIME_RANGES: TimeRange[] = ["1D", "7D", "30D", "6M", "1Y"];
const SORT_OPTIONS: { key: SortKey; label: string }[] = [
  { key: "change_pct", label: "% change" },
  { key: "change_abs", label: "Absolute change" },
  { key: "volume", label: "Sales volume" },
];

function formatEur(amount: number): string {
  return new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" }).format(amount);
}

function ChangeBadge({ pct, abs }: { pct: number; abs: number }) {
  const positive = pct >= 0;
  const color = positive ? "text-[var(--color-gain)]" : "text-[var(--color-loss)]";
  const sign = positive ? "+" : "";
  return (
    <span className={`font-medium ${color}`}>
      {sign}
      {pct.toFixed(1)}% ({sign}
      {formatEur(abs)})
    </span>
  );
}

export function Top100Screen({ onSelectCard }: { onSelectCard: (cardId: string) => void }) {
  const [timeRange, setTimeRange] = useState<TimeRange>("7D");
  const [sortKey, setSortKey] = useState<SortKey>("change_pct");
  const [entries, setEntries] = useState<Top100Entry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchTop100({ timeRange, sortKey })
      .then((data) => {
        if (!cancelled) setEntries(data);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [timeRange, sortKey]);

  return (
    <div className="flex h-full flex-col p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Top 100 Hottest Cards</h1>
        <div className="flex items-center gap-4">
          <div className="flex rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-0.5">
            {TIME_RANGES.map((range) => (
              <button
                key={range}
                type="button"
                onClick={() => setTimeRange(range)}
                className={`rounded px-3 py-1 text-sm ${
                  timeRange === range
                    ? "bg-[var(--color-accent)] text-white"
                    : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
                }`}
              >
                {range}
              </button>
            ))}
          </div>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-sm"
          >
            {SORT_OPTIONS.map((opt) => (
              <option key={opt.key} value={opt.key}>
                Sort: {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-[var(--color-loss)] bg-[var(--color-surface)] p-3 text-sm text-[var(--color-loss)]">
          Couldn't reach the backend: {error}
        </div>
      )}

      {!error && !loading && entries.length === 0 && (
        <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-6 text-center text-[var(--color-text-muted)]">
          No ranking has been computed yet for {timeRange}. The Top 100 job runs once the catalog
          import and price-snapshot connectors have been scheduled (Phase 6/8).
        </div>
      )}

      <div className="flex-1 overflow-auto rounded-md border border-[var(--color-border)]">
        <table className="w-full text-left text-sm">
          <thead className="sticky top-0 bg-[var(--color-surface-raised)] text-[var(--color-text-muted)]">
            <tr>
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2" />
              <th className="px-3 py-2">Card</th>
              <th className="px-3 py-2">Grade</th>
              <th className="px-3 py-2">Start</th>
              <th className="px-3 py-2">Current</th>
              <th className="px-3 py-2">Change</th>
              <th className="px-3 py-2">Observations</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr
                key={`${entry.card_id}-${entry.grade_id}`}
                onClick={() => onSelectCard(entry.card_id)}
                className="cursor-pointer border-t border-[var(--color-border)] hover:bg-[var(--color-surface)]"
              >
                <td className="px-3 py-2 text-[var(--color-text-muted)]">{entry.rank}</td>
                <td className="px-3 py-2">
                  <div className="h-14 w-10 overflow-hidden rounded bg-[var(--color-surface-raised)]">
                    <CardImage src={entry.image_source_url} alt={entry.name} quality="low" className="h-full w-full object-cover" />
                  </div>
                </td>
                <td className="px-3 py-2">
                  {entry.name} <span className="text-[var(--color-text-muted)]">#{entry.number}</span>
                </td>
                <td className="px-3 py-2">
                  {entry.grading_company} {entry.grade_label}
                </td>
                <td className="px-3 py-2">{formatEur(entry.start_price_eur)}</td>
                <td className="px-3 py-2">{formatEur(entry.end_price_eur)}</td>
                <td className="px-3 py-2">
                  <ChangeBadge pct={entry.change_pct} abs={entry.change_abs_eur} />
                </td>
                <td className="px-3 py-2 text-[var(--color-text-muted)]">{entry.observation_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
