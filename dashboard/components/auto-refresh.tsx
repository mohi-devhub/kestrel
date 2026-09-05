"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { cn } from "cn";

/**
 * Re-runs the server components on an interval. There is no client data layer:
 * every panel is a server component reading the control plane directly, so
 * refreshing the route IS the live-update mechanism and every number keeps one
 * source of truth. Pauses on a hidden tab.
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
      className="flex items-center gap-2 rounded-full border border-line bg-card px-3 py-1.5 text-[12.5px] font-medium text-ink-2 shadow-card hover:border-line-2 hover:text-ink"
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full",
          live ? "bg-ok motion-safe:animate-pulse" : "bg-ink-4",
        )}
      />
      {live ? `Live · ${seconds}s` : "Paused"}
    </button>
  );
}
