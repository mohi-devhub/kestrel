"use client";

import { useState, useTransition } from "react";

import { setPolicyAction } from "@/app/actions";
import { cn } from "cn";

/**
 * The demo lever: swap the active placement policy and the next reconcile tick
 * lands work differently.
 *
 * Rendered as an explicit list rather than a dropdown because which policies
 * exist is part of what the console is showing. Optimistic on click, reverted if
 * the control plane refuses, so the selection responds at press speed rather
 * than after a round trip.
 */
const POLICIES: { name: string; blurb: string }[] = [
  { name: "first_fit", blurb: "First node with room" },
  { name: "bin_packing", blurb: "Tightest fit, keeps whole nodes free" },
  { name: "priority", blurb: "Highest priority claims capacity first" },
  { name: "runway_fair", blurb: "Healthier budget runway drains first" },
];

export function PolicySwitcher({ active }: { active: string }) {
  const [pending, startTransition] = useTransition();
  const [message, setMessage] = useState<string | null>(null);
  const [optimistic, setOptimistic] = useState(active);

  function choose(name: string) {
    if (name === optimistic) return;
    setOptimistic(name);
    setMessage(null);
    startTransition(async () => {
      const result = await setPolicyAction(name);
      if (!result.ok) {
        setOptimistic(active);
        setMessage(result.message);
      }
    });
  }

  return (
    <div>
      <div className="divide-y divide-line-soft border-y border-line-soft">
        {POLICIES.map((p) => {
          const isActive = p.name === optimistic;
          return (
            <button
              key={p.name}
              type="button"
              disabled={pending}
              onClick={() => choose(p.name)}
              aria-pressed={isActive}
              className={cn(
                "flex w-full items-center gap-2.5 py-2 pl-2 pr-1 text-left disabled:opacity-60",
                isActive ? "bg-accent-weak" : "hover:bg-bg-sunk",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "h-6 w-[2px] shrink-0",
                  isActive ? "bg-accent" : "bg-transparent",
                )}
              />
              <span className="min-w-0">
                <span
                  className={cn(
                    "num block text-[12px] leading-tight",
                    isActive ? "text-fg" : "text-fg-muted",
                  )}
                >
                  {p.name}
                </span>
                <span className="block text-[11px] leading-tight text-fg-dim">{p.blurb}</span>
              </span>
            </button>
          );
        })}
      </div>
      {message && <p className="mt-2 text-[11px] text-crit">{message}</p>}
    </div>
  );
}
