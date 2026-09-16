import { createChart, LineSeries, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { fetchCard, fetchCardPrices, type CardDetail as CardDetailType, type CardPricePoint, type TimeRange } from "../api/client";
import { CardImage } from "../components/CardImage";

const TIME_RANGES: TimeRange[] = ["1D", "7D", "30D", "6M", "1Y"];

function formatEur(amount: number): string {
  return new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" }).format(amount);
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

      <div className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
        {prices.length > 0 ? (
          <PriceChart points={prices} />
        ) : (
          <div className="flex h-80 items-center justify-center text-center text-[var(--color-text-muted)]">
            No price observations in this range yet. Background collection (Settings) builds
            this up over time.
          </div>
        )}
      </div>
    </div>
  );
}
