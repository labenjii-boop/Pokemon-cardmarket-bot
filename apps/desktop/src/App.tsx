import { useState } from "react";
import { Sidebar, type ScreenId } from "./components/Sidebar";
import { PlaceholderScreen } from "./screens/Placeholder";
import { ReviewQueueScreen } from "./screens/ReviewQueue";
import { SettingsScreen } from "./screens/Settings";
import { SourceStatusScreen } from "./screens/SourceStatus";
import { Top100Screen } from "./screens/Top100";

const WIRED_SCREENS: ScreenId[] = ["top100", "sources", "review", "settings"];

const PLACEHOLDER_PHASE: Partial<Record<ScreenId, string>> = {
  dashboard: "Phase 10",
  search: "Phase 10",
  charts: "Phase 7",
  sales: "Phase 10",
  watchlist: "Phase 10",
  compare: "Phase 10",
};

function App() {
  const [screen, setScreen] = useState<ScreenId>("top100");

  return (
    <div className="flex h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
      <Sidebar active={screen} onSelect={setScreen} />
      <main className="flex-1 overflow-auto">
        {screen === "top100" && <Top100Screen />}
        {screen === "sources" && <SourceStatusScreen />}
        {screen === "review" && <ReviewQueueScreen />}
        {screen === "settings" && <SettingsScreen />}
        {!WIRED_SCREENS.includes(screen) && (
          <PlaceholderScreen
            title={screen[0].toUpperCase() + screen.slice(1)}
            phase={PLACEHOLDER_PHASE[screen] ?? "a later phase"}
          />
        )}
      </main>
    </div>
  );
}

export default App;
