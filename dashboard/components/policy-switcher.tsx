"use client";

import { useState, useTransition } from "react";
import { Check } from "lucide-react";

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
    <div className="flex flex-col gap-1.5">
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
              "flex items-center gap-3 rounded-sm border px-3 py-2.5 text-left disabled:opacity-60",
              isActive
                ? "border-accent-line bg-accent-soft"
                : "border-line bg-card hover:border-line-2 hover:bg-sunk",
            )}
          >
            <span
              className={cn(
                "grid size-5 shrink-0 place-content-center rounded-full border",
                isActive ? "border-accent bg-accent text-white" : "border-line-2 bg-card",
              )}
            >
              {isActive && <Check size={12} strokeWidth={3} />}
            </span>
            <span className="min-w-0">
              <span
                className={cn(
                  "t-mono block text-[12.5px] leading-tight",
                  isActive ? "text-accent" : "text-ink",
                )}
              >
                {p.name}
              </span>
              <span className="mt-0.5 block text-[11.5px] leading-tight text-ink-3">
                {p.blurb}
              </span>
            </span>
          </button>
        );
      })}
      {message && <p className="px-1 pt-1 text-[12px] text-crit">{message}</p>}
    </div>
  );
}
