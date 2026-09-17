import { createChart, LineSeries, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import {
  fetchCard,
  fetchCardPrices,
  fetchCardVariants,
  type CardDetail as CardDetailType,
  type CardPricePoint,
  type CardVariantPricing,
  type TimeRange,
} from "../api/client";
import { CardImage } from "../components/CardImage";

const TIME_RANGES: TimeRange[] = ["1D", "7D", "30D", "6M", "1Y"];

function formatEur(amount: number): string {
  return new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" }).format(amount);
}

// TCGdex variant/finish keys are lowercase-hyphenated ("reverse-holo", "1st-edition",
// "holofoil") — title-case them word by word for display.
function formatVariantLabel(key: string): string {
  return key
    .split("-")
    .map((word) => (word.length ? word[0].toUpperCase() + word.slice(1) : word))
    .join(" ");
}

function VariantPricing({ cardId }: { cardId: string }) {
  const [variants, setVariants] = useState<CardVariantPricing | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchCardVariants(cardId)
      .then(setVariants)
      .catch(() => setVariants(null))
      .finally(() => setLoading(false));
  }, [cardId]);

  if (loading) {
    return <p className="text-sm text-[var(--color-text-muted)]">Loading variant pricing…</p>;
  }

  const eurEntries = Object.entries(variants?.cardmarket_eur ?? {});
  const tcgplayerEntries = Object.entries(variants?.tcgplayer_eur ?? {});

  if (eurEntries.length === 0 && tcgplayerEntries.length === 0) {
    return null;
  }

  return (
    <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="mb-3 text-sm font-semibold text-[var(--color-text-muted)]">
        Pricing by variant (holo, reverse holo, 1st edition, etc)
      </h2>
      {/* Both columns are EUR — TCGplayer reports in USD upstream, converted server-side so
          the two marketplaces can be compared directly without doing currency math by eye. */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {eurEntries.length > 0 && (
          <div>
            <p className="mb-1 text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Cardmarket (EUR)</p>
            <ul className="divide-y divide-[var(--color-border)]">
              {eurEntries.map(([variant, price]) => (
                <li key={variant} className="flex items-center justify-between py-1.5 text-sm">
                  <span>{formatVariantLabel(variant)}</span>
                  <span className="font-medium">{formatEur(price)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {tcgplayerEntries.length > 0 && (
          <div>
            <p className="mb-1 text-xs uppercase tracking-wide text-[var(--color-text-muted)]">TCGplayer (EUR)</p>
            <ul className="divide-y divide-[var(--color-border)]">
              {tcgplayerEntries.map(([variant, price]) => (
                <li key={variant} className="flex items-center justify-between py-1.5 text-sm">
                  <span>{formatVariantLabel(variant)}</span>
                  <span className="font-medium">{formatEur(price)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}

function PriceChart({ points }: { points: CardPricePoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: { background: { color: "transparent" }, textColor: "#9aa2ad" },
      grid: {
        vertLines: { color: "#262b33" },
        horzLines: { color: "#262b33" },
      },
      timeScale: { timeVisible: true, borderColor: "#262b33" },
      rightPriceScale: { borderColor: "#262b33" },
    });
    const series = chart.addSeries(LineSeries, { color: "#5b8cff", lineWidth: 2 });
    chartRef.current = chart;
    seriesRef.current = series;
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current) return;
    // A line series needs strictly ascending, de-duplicated timestamps — multiple sources
    // polled within the same second would otherwise violate that, so the later one wins.
    const byTime = new Map<number, number>();
    for (const p of points) {
      const t = Math.floor(new Date(p.observed_at).getTime() / 1000);
      byTime.set(t, p.price_eur);
    }
    const data = Array.from(byTime.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([time, value]) => ({ time: time as UTCTimestamp, value }));
    seriesRef.current.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [points]);

  return <div ref={containerRef} className="h-80 w-full" />;
}

export function CardDetailScreen({ cardId, onBack }: { cardId: string; onBack: () => void }) {
  const [card, setCard] = useState<CardDetailType | null>(null);
  const [prices, setPrices] = useState<CardPricePoint[]>([]);
  const [timeRange, setTimeRange] = useState<TimeRange>("30D");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCard(cardId)
      .then(setCard)
      .catch((err: Error) => setError(err.message));
  }, [cardId]);

  useEffect(() => {
    fetchCardPrices(cardId, timeRange)
      .then(setPrices)
      .catch((err: Error) => setError(err.message));
  }, [cardId, timeRange]);

  const latest = prices.at(-1);

  return (
    <div className="flex h-full flex-col p-6">
      <button
        type="button"
        onClick={onBack}
        className="mb-4 w-fit text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
      >
        ← Back
      </button>

      {error && <p className="text-[var(--color-loss)]">Couldn't reach the backend: {error}</p>}

      {card && (
        <div className="mb-6 flex gap-4">
          <div className="h-40 w-28 shrink-0 overflow-hidden rounded bg-[var(--color-surface-raised)]">
            <CardImage src={card.image_source_url} alt={card.name} className="h-full w-full object-cover" />
          </div>
          <div>
            <h1 className="text-xl font-semibold">{card.name}</h1>
            <p className="text-[var(--color-text-muted)]">
              {card.set_name} · #{card.number} · {card.language}
            </p>
            {card.rarity && <p className="text-sm text-[var(--color-text-muted)]">{card.rarity}</p>}
            <p className="mt-2 text-2xl font-semibold">{latest ? formatEur(latest.price_eur) : "No price data yet"}</p>
          </div>
        </div>
      )}

      <div className="mb-3 flex rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-0.5 w-fit">
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

      <div className="mb-6 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
        {prices.length > 0 ? (
          <PriceChart points={prices} />
        ) : (
          <div className="flex h-80 items-center justify-center text-center text-[var(--color-text-muted)]">
            No price observations in this range yet. Background collection (Settings) builds
            this up over time.
          </div>
        )}
      </div>

      <VariantPricing cardId={cardId} />
    </div>
  );
}
