import { useEffect, useState } from "react";
import { fetchSettings, putSettings, type LocalSettings } from "../api/client";

export function SettingsScreen() {
  const [settings, setSettings] = useState<LocalSettings>({});
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings()
      .then(setSettings)
      .catch((err: Error) => setError(err.message));
  }, []);

  const save = async (patch: LocalSettings) => {
    const next = { ...settings, ...patch };
    setSettings(next);
    try {
      await putSettings(patch);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="max-w-xl p-6">
      <h1 className="mb-4 text-xl font-semibold">Settings</h1>
      {error && <p className="mb-4 text-[var(--color-loss)]">Couldn't reach the backend: {error}</p>}

      <div className="mb-6 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <label className="flex items-center justify-between">
          <div>
            <div className="font-medium">Background collection</div>
            <div className="text-sm text-[var(--color-text-muted)]">
              Keep polling connectors and recomputing Top 100 while the app runs (Section 7).
              Off by default.
            </div>
          </div>
          <input
            type="checkbox"
            checked={!!settings.scheduler_enabled}
            onChange={(e) => save({ scheduler_enabled: e.target.checked })}
            className="h-5 w-5"
          />
        </label>
      </div>

      <div className="mb-6 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <label className="block">
          <div className="mb-1 font-medium">Pokémon TCG API key (optional)</div>
          <div className="mb-2 text-sm text-[var(--color-text-muted)]">
            Raises the pokemontcg.io free rate limit from 1,000 to 20,000 requests/day. Get one
            at pokemontcg.io — see DATA_SOURCES.md §5.
          </div>
          <input
            type="password"
            defaultValue={settings.pokemontcg_io_api_key ?? ""}
            onBlur={(e) => save({ pokemontcg_io_api_key: e.target.value })}
            className="w-full rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1"
          />
        </label>
      </div>

      <div className="mb-6 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <div className="mb-2 font-medium">Top 100 qualification (Section 2)</div>
        <label className="mb-3 block">
          <span className="mb-1 block text-sm text-[var(--color-text-muted)]">
            Minimum price observations required in the period
          </span>
          <input
            type="number"
            min={1}
            defaultValue={settings.top100_min_observations ?? 3}
            onBlur={(e) => save({ top100_min_observations: Number(e.target.value) })}
            className="w-32 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm text-[var(--color-text-muted)]">Minimum price (EUR)</span>
          <input
            type="number"
            min={0}
            defaultValue={settings.top100_min_price_eur ?? 0}
            onBlur={(e) => save({ top100_min_price_eur: Number(e.target.value) })}
            className="w-32 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1"
          />
        </label>
      </div>

      {saved && <p className="text-sm text-[var(--color-gain)]">Saved.</p>}
    </div>
  );
}
