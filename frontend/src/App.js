import React, { useEffect, useState, useCallback } from "react";
import { Toaster } from "sonner";
import ScenesSidebar from "@/components/ScenesSidebar";
import SceneReader from "@/components/SceneReader";
import LaundryListPanel from "@/components/LaundryListPanel";
import UploadDropzone from "@/components/UploadDropzone";
import PronouncePage from "@/components/PronouncePage";
import LoginModal from "@/components/LoginModal";
import PaywallModal from "@/components/PaywallModal";
import WelcomeModal from "@/components/WelcomeModal";
import VerifyPage from "@/components/VerifyPage";
import AccountChip from "@/components/AccountChip";
import AdminPage from "@/components/AdminPage";
import { AuthProvider, useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import {
  getScene,
  fetchSoundCategories,
} from "@/lib/api";
import "@/App.css";

const TABS = [
  { id: "pronounce", label: "Word" },
  { id: "scenes", label: "Scene" },
];

const MY_SCENES_KEY = "myScenes";

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
  } catch (e) {
    console.warn("localStorage unavailable — scene index will not persist", e);
  }
}

export default function AppRoot() {
  // Show the magic-link verify page if we're on /auth/verify. Kept outside
  // the AuthProvider tree of the main app so the verify page can run its
  // own tiny lifecycle without interfering with the main data loads.
  const path = typeof window !== "undefined" ? window.location.pathname : "/";
  return (
    <AuthProvider>
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
      <LoginModal />
      <PaywallModal />
      <WelcomeModal />
      {path.startsWith("/auth/verify") ? (
        <VerifyPage />
      ) : path.startsWith("/admin") ? (
        <AdminPage />
      ) : (
        <App />
      )}
    </AuthProvider>
  );
}

function App() {
  const auth = useAuth();

  // Global 401 → open login, 402 → open paywall. Attached once per mount.
  useEffect(() => {
    const id = api.interceptors.response.use(
      (r) => r,
      (err) => {
        const status = err?.response?.status;
        if (status === 401) {
          auth.openLogin();
        } else if (status === 402) {
          const detail = err?.response?.data?.detail;
          const kind =
            (detail && typeof detail === "object" && detail.kind) ||
            "subscription";
          auth.openPaywall(kind);
        }
        return Promise.reject(err);
      }
    );
    return () => api.interceptors.response.eject(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
    } catch (e) {
      console.warn("localStorage unavailable — tab selection not persisted", e);
    }
  };

  const refreshScenes = useCallback(async () => {
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
            const filtered = mine.slice(1);
            writeMyScenes(filtered);
            setScenes(filtered);
          }
        }
      } catch (e) {
        // Backend unreachable on first load — the Pronounce tab still works.
        console.warn("Initial data load failed", e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSelect = async (id) => {
    try {
      const full = await getScene(id);
      setActiveScene(full);
    } catch (e) {
      console.warn("Could not load scene", id, e);
    }
  };

  const handleNewScene = async (scene) => {
    setActiveScene(scene);
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
    // Refresh trial counter after a successful upload.
    auth.refresh();
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
      } catch (e) {
        console.warn("Could not auto-load next scene after delete", e);
      }
    }
  };

  return (
    <div className="App min-h-screen flex flex-col">
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
      <AccountChip />
    </header>
  );
}

function ScenesEmptyState({ onUploaded }) {
  return (
    <div className="flex-1 overflow-auto bg-paper">
      <div className="max-w-4xl mx-auto px-5 sm:px-8 py-8 sm:py-16 lg:py-24">
        <UploadDropzone onUploaded={onUploaded} />
      </div>
    </div>
  );
}
