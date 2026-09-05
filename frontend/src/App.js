import React, { useEffect, useState, useCallback } from "react";
import { Toaster } from "sonner";
import ScenesSidebar from "@/components/ScenesSidebar";
import SceneReader from "@/components/SceneReader";
import LaundryListPanel from "@/components/LaundryListPanel";
import UploadDropzone from "@/components/UploadDropzone";
import PronouncePage from "@/components/PronouncePage";
import {
  getScene,
  fetchSoundCategories,
} from "@/lib/api";
import "@/App.css";

const TABS = [
  { id: "pronounce", label: "Word" },
  { id: "scenes", label: "Scenes" },
];

const MY_SCENES_KEY = "myScenes";

// Read the ids of scenes uploaded from THIS browser. Scenes on the server
// are visible to whoever knows the id, but the sidebar only ever lists the
// ones this browser has seen — so people don't see what someone else
// searched or uploaded.
function readMyScenes() {
  try {
    const raw = window.localStorage.getItem(MY_SCENES_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}
function writeMyScenes(list) {
  try {
    window.localStorage.setItem(MY_SCENES_KEY, JSON.stringify(list));
  } catch {
    // localStorage unavailable — silently drop persistence
  }
}

export default function App() {
  const [tab, setTab] = useState(() => {
    try {
      return window.localStorage.getItem("activeTab") || "pronounce";
    } catch {
      return "pronounce";
    }
  });
  const [scenes, setScenes] = useState([]);
  const [activeScene, setActiveScene] = useState(null);
  const [categories, setCategories] = useState([]);
  const [highlightSet, setHighlightSet] = useState(new Set());
  const [loading, setLoading] = useState(true);

  const switchTab = (t) => {
    setTab(t);
    try {
      window.localStorage.setItem("activeTab", t);
    } catch {
      // localStorage not available (private mode) — ignore.
    }
  };

  const refreshScenes = useCallback(async () => {
    // Only list scenes this browser has uploaded. `listScenes()` on the
    // server returns every scene — we no longer call it, so users don't see
    // each other's uploads.
    const mine = readMyScenes();
    setScenes(mine);
    return mine;
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const cats = await fetchSoundCategories();
        setCategories(cats);
        const mine = readMyScenes();
        setScenes(mine);
        if (mine.length > 0) {
          try {
            const full = await getScene(mine[0].id);
            setActiveScene(full);
          } catch {
            // Scene was deleted server-side — drop it from the local index.
            const filtered = mine.slice(1);
            writeMyScenes(filtered);
            setScenes(filtered);
          }
        }
      } catch (e) {
        // Backend unreachable on first load — the Pronounce tab still works
        // for cached tokens or once the network recovers.
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSelect = async (id) => {
    try {
      const full = await getScene(id);
      setActiveScene(full);
    } catch {
      // ignore — sidebar highlight will simply not change
    }
  };

  const handleNewScene = async (scene) => {
    setActiveScene(scene);
    // Prepend the newly uploaded scene to this browser's private index.
    const summary = {
      id: scene.id,
      title: scene.title,
      created_at: scene.created_at,
      word_count: (scene.tokens || []).filter((t) => t.is_word).length,
    };
    const mine = readMyScenes().filter((s) => s.id !== scene.id);
    const next = [summary, ...mine];
    writeMyScenes(next);
    setScenes(next);
    switchTab("scenes");
  };

  const handleDeleted = async (id) => {
    if (activeScene?.id === id) setActiveScene(null);
    const next = readMyScenes().filter((s) => s.id !== id);
    writeMyScenes(next);
    setScenes(next);
    if (!activeScene && next.length > 0) {
      try {
        const full = await getScene(next[0].id);
        setActiveScene(full);
      } catch {
        // ignore
      }
    }
  };

  return (
    <div className="App min-h-screen flex flex-col">
      <Toaster
        position="top-center"
        toastOptions={{
          style: {
            background: "#1C1B1A",
            color: "#FDFDFB",
            borderRadius: 0,
            fontFamily: "IBM Plex Mono, monospace",
            fontSize: "12px",
            letterSpacing: "0.05em",
          },
        }}
      />
      <Header tab={tab} onSwitchTab={switchTab} />

      {tab === "pronounce" ? (
        <PronouncePage onGoToScenes={() => switchTab("scenes")} />
      ) : (
        <div className="flex flex-col md:flex-row flex-1 min-h-0">
          <ScenesSidebar
            scenes={scenes}
            activeId={activeScene?.id}
            onSelect={handleSelect}
            onNewScene={handleNewScene}
            onDeleted={handleDeleted}
          />

          <main className="flex-1 flex flex-col lg:flex-row min-w-0 min-h-0">
            {loading ? (
              <div className="flex-1 flex items-center justify-center font-mono text-xs text-muted2 py-12">
                Preparing the workbench…
              </div>
            ) : activeScene ? (
              <>
                <SceneReader
                  scene={activeScene}
                  highlightSet={highlightSet}
                />
                <LaundryListPanel
                  scene={activeScene}
                  categories={categories}
                  onHighlightChange={setHighlightSet}
                />
              </>
            ) : (
              <ScenesEmptyState onUploaded={handleNewScene} />
            )}
          </main>
        </div>
      )}
    </div>
  );
}

function Header({ tab, onSwitchTab }) {
  return (
    <header
      className="border-b thin-rule bg-surface px-4 sm:px-8 py-3 sm:py-4 flex items-center justify-between gap-3 sm:gap-6 flex-wrap"
      data-testid="app-header"
    >
      <div className="flex items-baseline gap-4">
        <div className="font-display text-xl sm:text-2xl text-ink leading-none">
          Pronounce it.
        </div>
      </div>
      <nav
        className="flex items-center border thin-rule"
        data-testid="tab-nav"
        role="tablist"
      >
        {TABS.map((t) => {
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={active}
              className={
                "font-mono text-[10px] sm:text-[11px] uppercase tracking-[0.18em] sm:tracking-[0.22em] px-3 sm:px-5 py-2 sm:py-2.5 border-r thin-rule last:border-r-0 transition-colors " +
                (active
                  ? "bg-ink text-surface"
                  : "bg-transparent text-ink hover:bg-paper")
              }
              data-testid={`tab-${t.id}`}
              onClick={() => onSwitchTab(t.id)}
            >
              {t.label}
            </button>
          );
        })}
      </nav>
      <div className="hidden lg:block font-mono text-[10px] uppercase tracking-[0.25em] text-muted2">
        IPA · ElevenLabs
      </div>
    </header>
  );
}

function ScenesEmptyState({ onUploaded }) {
  return (
    <div className="flex-1 overflow-auto bg-paper">
      <div className="max-w-4xl mx-auto px-5 sm:px-8 py-8 sm:py-16 lg:py-24">
        <div className="mb-8 sm:mb-12">
          <h1 className="font-display text-4xl sm:text-6xl lg:text-7xl text-ink leading-[0.95]">
            Every word.
            <br />
            <em className="not-italic text-rust">In the right sound.</em>
          </h1>
          <p className="mt-4 sm:mt-6 text-lg sm:text-xl text-muted2 font-serif leading-relaxed max-w-2xl">
            Drop a PDF of an audition scene. Read every line in American IPA,
            click any word to hear it, and isolate sounds into focused
            practice lists.
          </p>
        </div>
        <UploadDropzone onUploaded={onUploaded} />
      </div>
    </div>
  );
}
