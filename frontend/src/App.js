import React, { useEffect, useState, useCallback } from "react";
import { Toaster } from "sonner";
import ScenesSidebar from "@/components/ScenesSidebar";
import SceneReader from "@/components/SceneReader";
import LaundryListPanel from "@/components/LaundryListPanel";
import UploadDropzone from "@/components/UploadDropzone";
import {
  listScenes,
  getScene,
  fetchSoundCategories,
} from "@/lib/api";
import "@/App.css";

export default function App() {
  const [scenes, setScenes] = useState([]);
  const [activeScene, setActiveScene] = useState(null);
  const [categories, setCategories] = useState([]);
  const [highlightSet, setHighlightSet] = useState(new Set());
  const [loading, setLoading] = useState(true);

  const refreshScenes = useCallback(async () => {
    try {
      const data = await listScenes();
      setScenes(data);
      return data;
    } catch (e) {
      return [];
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [list, cats] = await Promise.all([
          listScenes(),
          fetchSoundCategories(),
        ]);
        setScenes(list);
        setCategories(cats);
        if (list.length > 0) {
          const full = await getScene(list[0].id);
          setActiveScene(full);
        }
      } catch (e) {
        // Backend might not be reachable on first load — empty state will render.
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
      /* noop */
    }
  };

  const handleNewScene = async (scene) => {
    setActiveScene(scene);
    await refreshScenes();
  };

  const handleDeleted = async (id) => {
    if (activeScene?.id === id) setActiveScene(null);
    const next = await refreshScenes();
    if (!activeScene && next.length > 0) {
      const full = await getScene(next[0].id);
      setActiveScene(full);
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
      <Header />
      <div className="flex flex-1 min-h-0">
        <ScenesSidebar
          scenes={scenes}
          activeId={activeScene?.id}
          onSelect={handleSelect}
          onNewScene={handleNewScene}
          onDeleted={handleDeleted}
        />

        <main className="flex-1 flex min-w-0">
          {loading ? (
            <div className="flex-1 flex items-center justify-center font-mono text-xs text-muted2">
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
            <EmptyState onUploaded={handleNewScene} />
          )}
        </main>
      </div>
    </div>
  );
}

function Header() {
  return (
    <header
      className="border-b thin-rule bg-surface px-8 py-4 flex items-center justify-between"
      data-testid="app-header"
    >
      <div className="flex items-baseline gap-4">
        <div className="font-display text-2xl text-ink leading-none">
          The Accent Workbench
        </div>
        <div className="hidden md:block font-mono text-[10px] uppercase tracking-[0.28em] text-muted2">
          A studio for American English
        </div>
      </div>
      <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2">
        IPA · ARPABET · ElevenLabs
      </div>
    </header>
  );
}

function EmptyState({ onUploaded }) {
  return (
    <div className="flex-1 overflow-auto bg-paper">
      <div className="max-w-4xl mx-auto px-8 py-16 lg:py-24">
        <div className="mb-12">
          <div className="font-mono text-[10px] uppercase tracking-[0.28em] text-muted2 mb-4">
            For coaches & their actors
          </div>
          <h1 className="font-display text-6xl lg:text-7xl text-ink leading-[0.95]">
            Every word.
            <br />
            <em className="not-italic text-rust">In the right sound.</em>
          </h1>
          <p className="mt-6 text-xl text-muted2 font-serif leading-relaxed max-w-2xl">
            Drop a PDF of an audition scene. Read every line in American IPA,
            click any word to hear it, and isolate sounds — dark L, flap T,
            schwa, the rhotic R — into focused practice lists.
          </p>
        </div>
        <UploadDropzone onUploaded={onUploaded} />
        <div className="mt-16 grid md:grid-cols-3 gap-px bg-rule">
          {[
            {
              n: "01",
              t: "Read",
              d: "Each word sits beside its IPA. Click to hear the General American pronunciation.",
            },
            {
              n: "02",
              t: "Hear",
              d: "Studio-grade ElevenLabs voices give actors a model to imitate.",
            },
            {
              n: "03",
              t: "Drill",
              d: "Pull a list of every word with the dark L (or schwa, or flap T) and practice it cleanly.",
            },
          ].map((c) => (
            <div key={c.n} className="bg-surface p-8">
              <div className="font-mono text-[10px] uppercase tracking-[0.25em] text-muted2">
                {c.n}
              </div>
              <div className="font-display text-3xl text-ink mt-2">{c.t}</div>
              <p className="mt-2 text-sm text-muted2 font-serif leading-relaxed">
                {c.d}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
