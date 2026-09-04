"use client";

import { useState, useTransition } from "react";

import { setPolicyAction } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { cn } from "cn";

/**
 * The demo lever: swap the active placement policy and watch the next reconcile
 * tick land workloads differently. Rendered as an explicit row of choices rather
 * than a dropdown because which policies exist *is* the point being shown.
 */
const POLICIES: { name: string; blurb: string }[] = [
  { name: "first_fit", blurb: "First node with room" },
  { name: "bin_packing", blurb: "Tightest fit; keeps whole nodes free" },
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
      setMessage(result.message);
      if (!result.ok) setOptimistic(active);
    });
  }

  return (
    <div>
      <div className="grid gap-2 sm:grid-cols-2">
        {POLICIES.map((p) => {
          const isActive = p.name === optimistic;
          return (
            <Button
              key={p.name}
              type="button"
              variant="outline"
              disabled={pending}
              onClick={() => choose(p.name)}
              aria-pressed={isActive}
              className={cn(
                "h-auto flex-col items-start gap-0.5 whitespace-normal px-3 py-2 text-left",
                isActive && "border-primary bg-secondary",
              )}
            >
              <span className="font-mono text-xs">{p.name}</span>
              <span className="text-[11px] font-normal text-muted-foreground">{p.blurb}</span>
            </Button>
          );
        })}
      </div>
      {message && <p className="mt-2 text-xs text-muted-foreground">{message}</p>}
    </div>
  );
}
