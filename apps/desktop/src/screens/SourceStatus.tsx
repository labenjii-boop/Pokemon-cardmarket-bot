import { useEffect, useState } from "react";
import { fetchSourceStatus, type SourceStatus } from "../api/client";

export function SourceStatusScreen() {
  const [sources, setSources] = useState<SourceStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSourceStatus()
      .then(setSources)
      .catch((err: Error) => setError(err.message));
  }, []);

  return (
    <div className="p-6">
      <h1 className="mb-4 text-xl font-semibold">Source Status</h1>
      {error && <p className="text-[var(--color-loss)]">Couldn't reach the backend: {error}</p>}
      <div className="grid gap-3">
        {sources.map((s) => (
          <div
            key={s.id}
            className="flex items-center justify-between rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] p-3"
          >
            <div>
              <div className="font-medium">{s.name}</div>
              <div className="text-sm text-[var(--color-text-muted)]">{s.kind}</div>
            </div>
            <div className="text-sm text-[var(--color-text-muted)]">
              {s.last_status ?? "never run"}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
