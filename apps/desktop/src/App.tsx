import { useState } from "react";
import { Sidebar, type ScreenId } from "./components/Sidebar";
import { PlaceholderScreen } from "./screens/Placeholder";
import { SourceStatusScreen } from "./screens/SourceStatus";
import { Top100Screen } from "./screens/Top100";

const PLACEHOLDER_PHASE: Record<Exclude<ScreenId, "top100" | "sources">, string> = {
  dashboard: "Phase 10",
  search: "Phase 10",
  charts: "Phase 7",
  sales: "Phase 10",
  watchlist: "Phase 10",
  compare: "Phase 10",
  review: "Phase 4",
  settings: "Phase 10",
};

function App() {
  const [screen, setScreen] = useState<ScreenId>("top100");

  return (
    <div className="flex h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
      <Sidebar active={screen} onSelect={setScreen} />
      <main className="flex-1 overflow-hidden">
        {screen === "top100" && <Top100Screen />}
        {screen === "sources" && <SourceStatusScreen />}
        {screen !== "top100" && screen !== "sources" && (
          <PlaceholderScreen
            title={screen[0].toUpperCase() + screen.slice(1)}
            phase={PLACEHOLDER_PHASE[screen]}
          />
        )}
      </main>
    </div>
  );
}

export default App;
