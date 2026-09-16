import { useState } from "react";
import { Sidebar, type ScreenId } from "./components/Sidebar";
import { CardDetailScreen } from "./screens/CardDetail";
import { PlaceholderScreen } from "./screens/Placeholder";
import { ReviewQueueScreen } from "./screens/ReviewQueue";
import { SearchScreen } from "./screens/Search";
import { SettingsScreen } from "./screens/Settings";
import { SourceStatusScreen } from "./screens/SourceStatus";
import { Top100Screen } from "./screens/Top100";

const WIRED_SCREENS: ScreenId[] = ["top100", "sources", "review", "settings", "search"];

const PLACEHOLDER_PHASE: Partial<Record<ScreenId, string>> = {
  dashboard: "Phase 10",
  charts: "Phase 7",
  sales: "Phase 10",
  watchlist: "Phase 10",
  compare: "Phase 10",
};

function App() {
  const [screen, setScreen] = useState<ScreenId>("top100");
  // A selected card overlays whichever screen is active (Section 2/11.3: "Click → opens the
  // full card detail page") rather than being its own sidebar entry — it's reached from Top 100
  // or Search, not navigated to directly.
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);

  const selectScreen = (id: ScreenId) => {
    setSelectedCardId(null);
    setScreen(id);
  };

  return (
    <div className="flex h-screen bg-[var(--color-bg)] text-[var(--color-text)]">
      <Sidebar active={screen} onSelect={selectScreen} />
      <main className="flex-1 overflow-auto">
        {selectedCardId ? (
          <CardDetailScreen cardId={selectedCardId} onBack={() => setSelectedCardId(null)} />
        ) : (
          <>
            {screen === "top100" && <Top100Screen onSelectCard={setSelectedCardId} />}
            {screen === "sources" && <SourceStatusScreen />}
            {screen === "review" && <ReviewQueueScreen />}
            {screen === "settings" && <SettingsScreen />}
            {screen === "search" && <SearchScreen onSelectCard={setSelectedCardId} />}
            {!WIRED_SCREENS.includes(screen) && (
              <PlaceholderScreen
                title={screen[0].toUpperCase() + screen.slice(1)}
                phase={PLACEHOLDER_PHASE[screen] ?? "a later phase"}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}

export default App;
