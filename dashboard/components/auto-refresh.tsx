"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Re-runs the server components on an interval.
 *
 * The dashboard has no client-side data layer: every panel is a server component
 * reading the control plane directly. Refreshing the route is therefore the whole
 * live-update mechanism, and it keeps a single source of truth for every number on
 * the page. Pauses while the tab is hidden so a backgrounded console stops
 * scraping the control plane.
 */
export function AutoRefresh({ seconds = 5 }: { seconds?: number }) {
  const router = useRouter();
  const [live, setLive] = useState(true);

  useEffect(() => {
    if (!live) return;
    const tick = () => {
      if (document.visibilityState === "visible") router.refresh();
    };
    const id = setInterval(tick, seconds * 1000);
    return () => clearInterval(id);
  }, [router, seconds, live]);

  return (
    <button
      type="button"
      onClick={() => setLive((v) => !v)}
      className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring rounded"
      aria-pressed={live}
    >
      <span
        aria-hidden
        className={
          live
            ? "size-1.5 rounded-full bg-emerald-500 motion-safe:animate-pulse"
            : "size-1.5 rounded-full bg-muted-foreground"
        }
      />
      {live ? `live · ${seconds}s` : "paused"}
    </button>
  );
}
