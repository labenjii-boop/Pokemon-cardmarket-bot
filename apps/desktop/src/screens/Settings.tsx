import { useEffect, useState } from "react";
import { fetchSettings, putSettings, type LocalSettings, type LocalSettingsPatch } from "../api/client";

export function SettingsScreen() {
  const [settings, setSettings] = useState<LocalSettings>({});
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reloadSettings = () => fetchSettings().then(setSettings).catch((err: Error) => setError(err.message));

  useEffect(() => {
    reloadSettings();
  }, []);

  const save = async (patch: LocalSettingsPatch) => {
    try {
      const next = await putSettings(patch);
      setSettings(next);
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const saveApiKey = async () => {
    if (!apiKeyInput) return; // blank input on blur means "didn't type anything," not "clear it"
    await save({ pokemontcg_io_api_key: apiKeyInput });
    setApiKeyInput("");
  };

  const clearApiKey = async () => {
    await save({ pokemontcg_io_api_key: "" });
    setApiKeyInput("");
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
        <div className="mb-1 font-medium">Pokémon TCG API key (optional)</div>
        <div className="mb-2 text-sm text-[var(--color-text-muted)]">
          Raises the pokemontcg.io free rate limit from 1,000 to 20,000 requests/day. Get one at
          pokemontcg.io — see DATA_SOURCES.md §5. Stored in the macOS Keychain, not in a file —
          this screen never shows the key back once saved.
        </div>
        <div className="flex items-center gap-2">
          <input
            type="password"
            value={apiKeyInput}
            onChange={(e) => setApiKeyInput(e.target.value)}
            onBlur={saveApiKey}
            placeholder={settings.pokemontcg_io_api_key_set ? "•••••••••••••• (set)" : "not set"}
            className="flex-1 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] px-2 py-1"
          />
          {settings.pokemontcg_io_api_key_set && (
            <button
              type="button"
              onClick={clearApiKey}
              className="rounded-md border border-[var(--color-border)] px-3 py-1 text-sm text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            >
              Clear
            </button>
          )}
        </div>
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
