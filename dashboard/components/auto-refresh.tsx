"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { cn } from "cn";

/**
 * Re-runs the server components on an interval.
 *
 * There is no client-side data layer: every panel is a server component reading
 * the control plane directly, so refreshing the route IS the live-update
 * mechanism and every number keeps one source of truth. Pauses on a hidden tab.
 */
export function AutoRefresh({ seconds = 5 }: { seconds?: number }) {
  const router = useRouter();
  const [live, setLive] = useState(true);

  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, seconds * 1000);
    return () => clearInterval(id);
  }, [router, seconds, live]);

  return (
    <button
      type="button"
      onClick={() => setLive((v) => !v)}
      aria-pressed={live}
      className="t-mono flex items-center gap-1.5 rounded-sm border border-hair bg-s2 px-2 py-1 text-[11px] text-ink-3 hover:border-hair-2 hover:text-ink"
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full",
          live ? "bg-ok motion-safe:animate-pulse" : "bg-ink-4",
        )}
      />
      {live ? `live ${seconds}s` : "paused"}
    </button>
  );
}
