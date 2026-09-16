// Nav for the core screens (Section 11). Only "Top 100" is wired to a real screen in Phase 2 —
// the rest are stubs so the shell already reflects the app's final shape, per-phase build-out
// happens screen by screen (Section 13).
const SCREENS = [
  { id: "top100", label: "Top 100 Hottest" },
  { id: "dashboard", label: "Dashboard" },
  { id: "search", label: "Search" },
  { id: "charts", label: "Charts" },
  { id: "sales", label: "Sales Table" },
  { id: "watchlist", label: "Watchlist" },
  { id: "compare", label: "Compare" },
  { id: "sources", label: "Source Status" },
  { id: "review", label: "Review Queue" },
  { id: "settings", label: "Settings" },
] as const;

export type ScreenId = (typeof SCREENS)[number]["id"];

export function Sidebar({
  active,
  onSelect,
}: {
  active: ScreenId;
  onSelect: (id: ScreenId) => void;
}) {
  return (
    <nav className="w-56 shrink-0 border-r border-[var(--color-border)] bg-[var(--color-surface)] p-3">
      <div className="mb-4 px-2 text-sm font-semibold tracking-wide text-[var(--color-text)]">
        Pokémon Card Tracker
      </div>
      <ul className="space-y-1">
        {SCREENS.map((screen) => (
          <li key={screen.id}>
            <button
              type="button"
              onClick={() => onSelect(screen.id)}
              className={`w-full rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
                active === screen.id
                  ? "bg-[var(--color-accent)] text-white"
                  : "text-[var(--color-text-muted)] hover:bg-[var(--color-surface-raised)] hover:text-[var(--color-text)]"
              }`}
            >
              {screen.label}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
