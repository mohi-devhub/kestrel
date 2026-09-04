"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { cn } from "cn";

/**
 * Re-runs the server components on an interval.
 *
 * The console has no client-side data layer: every panel is a server component
 * reading the control plane directly, so refreshing the route IS the live-update
 * mechanism and every number on the page keeps one source of truth. Pauses while
 * the tab is hidden so a backgrounded console stops polling.
 *
 * The dot is the one animated thing on the page. It earns it by carrying real
 * state (polling versus paused) rather than decorating a nav item.
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
      className="num flex items-center gap-1.5 text-[11px] text-fg-dim hover:text-fg"
    >
      <span
        aria-hidden
        className={cn(
          "size-1.5 rounded-full",
          live ? "bg-ok motion-safe:animate-pulse" : "bg-fg-dim",
        )}
      />
      {live ? `live ${seconds}s` : "paused"}
    </button>
  );
}
