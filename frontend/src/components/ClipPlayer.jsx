import React, { useEffect, useRef } from "react";

let apiPromise = null;
function loadYouTubeApi() {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (apiPromise) return apiPromise;
  apiPromise = new Promise((resolve) => {
    const prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => { prev?.(); resolve(window.YT); };
    const s = document.createElement("script");
    s.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(s);
  });
  return apiPromise;
}

// YouTube player that reports clips which refuse to play (deleted, private,
// embedding disabled) so the caller can hide + skip them.
export function ClipPlayer({ videoId, start, title, onUnplayable }) {
  const hostRef = useRef(null);
  const playerRef = useRef(null);
  const cbRef = useRef(onUnplayable);
  cbRef.current = onUnplayable;

  useEffect(() => {
    let cancelled = false;
    loadYouTubeApi().then((YT) => {
      if (cancelled || !hostRef.current) return;
      if (playerRef.current) {
        playerRef.current.loadVideoById({ videoId, startSeconds: start });
        return;
      }
      playerRef.current = new YT.Player(hostRef.current, {
        host: "https://www.youtube-nocookie.com",
        videoId,
        playerVars: { start, autoplay: 1, rel: 0, modestbranding: 1, playsinline: 1 },
        events: {
          onError: (e) => cbRef.current?.(e.data),
        },
      });
    });
    return () => { cancelled = true; };
  }, [videoId, start]);

  useEffect(() => () => { playerRef.current?.destroy?.(); playerRef.current = null; }, []);

  return (
    <div className="w-full h-full" title={title} data-testid="caption-search-iframe">
      <div ref={hostRef} className="w-full h-full" />
    </div>
  );
}
