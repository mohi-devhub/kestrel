"use client";

import { useState, useTransition } from "react";

import { setPolicyAction } from "@/app/actions";
import { cn } from "cn";

/**
 * The demo lever: change the active placement policy and the next reconcile tick
 * lands work differently. An explicit list rather than a dropdown, because which
 * policies exist is part of what the console is showing. Optimistic on click and
 * reverted if the control plane refuses, so it responds at press speed.
 */
const POLICIES = [
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
    <div className="flex flex-col gap-1">
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
              "rounded-sm border px-3 py-2 text-left disabled:opacity-60",
              isActive
                ? "border-accent-line bg-accent-weak"
                : "border-transparent hover:bg-s2",
            )}
          >
            <span
              className={cn(
                "t-mono block text-[12px] leading-tight",
                isActive ? "text-accent" : "text-ink-2",
              )}
            >
              {p.name}
            </span>
            <span className="mt-0.5 block text-[11px] leading-tight text-ink-4">{p.blurb}</span>
          </button>
        );
      })}
      {message && <p className="px-3 pt-1 text-[11px] text-crit">{message}</p>}
    </div>
  );
}
