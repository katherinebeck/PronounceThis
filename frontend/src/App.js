import React, { useEffect, useState, useCallback } from "react";
import Logo from "@/components/Logo";
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
import PaymentSuccessPage from "@/components/PaymentSuccessPage";
import LandingPage from "@/components/landing/LandingPage";
import ResetPasswordPage from "@/components/ResetPasswordPage";
import PaymentCancelPage from "@/components/PaymentCancelPage";
import LoginPage from "@/components/LoginPage";
import GuidedTrialBar from "@/components/GuidedTrialBar";
import { GuidedPopup } from "@/components/GuidedNextStep";
import { AuthProvider, useAuth } from "@/lib/auth";
import { api, listScenes, getScene, getSampleScene, fetchSoundCategories } from "@/lib/api";
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
            background: "#1A1B20",
            color: "#F1F2F6",
            border: "1px solid #2D303B",
            borderRadius: 0,
            fontFamily: "Open Sans, sans-serif",
            fontSize: "13px",
            letterSpacing: "0.02em",
          },
        }}
      />
      <LoginModal />
      <PaywallModal />
      <WelcomeModal />
      {path.startsWith("/auth/verify") ? (
        <VerifyPage />
      ) : path.startsWith("/auth/reset") ? (
        <ResetPasswordPage />
      ) : path.startsWith("/login") ? (
        <LoginPage />
      ) : path.startsWith("/payment/success") ? (
        <PaymentSuccessPage />
      ) : path.startsWith("/payment/cancel") ? (
        <PaymentCancelPage />
      ) : path.startsWith("/admin") ? (
        <AdminPage />
      ) : path.startsWith("/app") ? (
        <App />
      ) : (
        <HomeGate />
      )}
    </AuthProvider>
  );
}

// "/" → sales page for visitors; signed-in members go straight to the app.
function HomeGate() {
  const { loading, isAuthenticated } = useAuth();
  useEffect(() => {
    if (!loading && isAuthenticated) window.history.replaceState({}, "", "/app");
  }, [loading, isAuthenticated]);
  if (loading) return <div className="min-h-screen bg-stage" data-testid="home-loading" />;
  return isAuthenticated ? <App /> : <LandingPage />;
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
          if (err?.config?.skipPaywall) return Promise.reject(err);
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

  // Always land on Word; the Scene tab is one tap away.
  const [tab, setTab] = useState("pronounce");
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

  // The server is the authority on which scenes belong to the signed-in
  // user (scoped by owner_email). localStorage is only a display cache.
  // Guided-trial accounts can't upload, so their library is the sample scene.
  const refreshScenes = useCallback(async () => {
    try {
      const mine = await listScenes();
      let list = mine;
      if (auth.isGuidedTrial) {
        try {
          const sample = await getSampleScene();
          list = [{ id: sample.id, title: sample.title, created_at: sample.created_at, is_sample: true,
                    word_count: (sample.tokens || []).filter((t) => t.is_word).length }, ...mine];
        } catch (e) {
          console.warn("No sample scene set", e);
        }
      }
      writeMyScenes(list);
      setScenes(list);
      return list;
    } catch {
      setScenes([]);
      return [];
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.isGuidedTrial]);

  useEffect(() => {
    (async () => {
      try {
        const cats = await fetchSoundCategories();
        setCategories(cats);
      } catch (e) {
        console.warn("Initial data load failed", e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (auth.loading) return;
    if (!auth.isAuthenticated) {
      setScenes([]);
      setActiveScene(null);
      return;
    }
    (async () => {
      const mine = await refreshScenes();
      if (mine.length > 0) {
        try {
          setActiveScene(await getScene(mine[0].id));
        } catch (e) {
          console.warn("Could not load first scene", e);
        }
      } else {
        setActiveScene(null);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth.loading, auth.isAuthenticated, auth.me?.email, auth.isGuidedTrial]);

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
      <GuidedTrialBar tab={tab} onGoToWord={() => switchTab("pronounce")} onGoToScenes={() => switchTab("scenes")} />

      {tab === "pronounce" ? (
        <PronouncePage onGoToScenes={() => switchTab("scenes")} />
      ) : (
        <div className="flex flex-col flex-1 min-h-0" data-testid="scenes-page">
          {auth.isGuidedTrial ? (
            <SampleSceneIntro hasSample={scenes.some((s) => s.is_sample)} />
          ) : (
          <div className="bg-paper border-b thin-rule">
            <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6 sm:py-8">
              <UploadDropzone onUploaded={handleNewScene} />
            </div>
          </div>
          )}
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
              <ScenesEmptyState guided={auth.isGuidedTrial} />
            )}
          </main>
          </div>
          <GuidedPopup mode="unlock" active={auth.isGuidedTrial && scenes.some((s) => s.is_sample)} delayMs={60000} />
        </div>
      )}
    </div>
  );
}

function TabNav({ tab, onSwitchTab, className = "" }) {
  return (
    <nav
      className={"flex items-center gap-1 p-1 rounded-full bg-surface border thin-rule " + className}
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
              "flex-1 sm:flex-none font-mono text-[11px] uppercase tracking-[0.18em] sm:tracking-[0.22em] px-3 sm:px-5 py-2 rounded-full transition-colors " +
              (active
                ? "bg-ink text-stage font-semibold"
                : "bg-transparent text-muted2 hover:text-ink")
            }
            data-testid={`tab-${t.id}`}
            onClick={() => onSwitchTab(t.id)}
          >
            {t.label}
          </button>
        );
      })}
    </nav>
  );
}

function Header({ tab, onSwitchTab }) {
  return (
    <header
      className="sticky top-0 z-40 border-b thin-rule glass-bar"
      data-testid="app-header"
    >
      <div className="px-4 sm:px-8 py-3 sm:py-4 flex items-center justify-between gap-3 sm:gap-6">
        <a href="/" className="flex items-center leading-none" data-testid="header-logo" aria-label="Pronounce This home">
          <Logo className="h-5 sm:h-6" />
        </a>
        <TabNav tab={tab} onSwitchTab={onSwitchTab} className="hidden sm:flex" />
        <AccountChip />
      </div>
      <div className="sm:hidden px-4 pb-3" data-testid="mobile-tab-bar">
        <TabNav tab={tab} onSwitchTab={onSwitchTab} className="w-full" />
      </div>
    </header>
  );
}

function ScenesEmptyState({ guided = false }) {
  return (
    <div className="flex-1 flex items-center justify-center bg-paper px-6 py-16" data-testid="scenes-empty-state">
      <p className="font-serif text-base text-muted2 italic text-center max-w-md">
        {guided
          ? "The sample audition scene isn't available right now — please check back shortly."
          : "Your transcribed scenes will appear here. Upload a PDF above to get started."}
      </p>
    </div>
  );
}

// Guided trial, step 02: replaces the upload panel with a short brief for the sample scene.
function SampleSceneIntro({ hasSample }) {
  const { openPaywall } = useAuth();
  return (
    <div className="bg-paper border-b thin-rule" data-testid="sample-scene-intro">
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-6 sm:py-8 flex flex-col lg:flex-row lg:items-end gap-5 lg:gap-10">
        <div className="min-w-0 flex-1">
          <div className="font-mono text-[10px] font-bold uppercase tracking-[0.28em] text-rust">Step 02 · Sample audition scene</div>
          <h2 className="font-display text-2xl sm:text-3xl text-ink mt-2 leading-tight">
            {hasSample ? "Try Pronounce This Scene." : "Sample scene coming shortly."}
          </h2>
          <p className="font-serif text-base text-muted2 mt-2 leading-relaxed max-w-2xl">
            Choose your character, tap any word to hear it in a General American accent, play the lines, and pull the sound list for the scene.
          </p>
        </div>
        <button
          type="button"
          className="btn-secondary shrink-0 justify-center"
          onClick={() => openPaywall("unlock")}
          data-testid="sample-scene-upload-own"
        >
          Upload your own scene
        </button>
      </div>
    </div>
  );
}
