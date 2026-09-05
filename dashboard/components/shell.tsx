import type { LucideIcon } from "lucide-react";

import { cn } from "cn";

/**
 * Card primitives.
 *
 * A card here is a real object: pure white on the warm canvas, generous padding,
 * 12px radius, one hairline and a shadow barely strong enough to lift it. The
 * ground and the surface are different materials, which is what makes a panel
 * read as something worth reading.
 */

export function Card({
  title,
  icon: Icon,
  aside,
  children,
  className,
  bodyClassName,
  flush,
}: {
  title?: string;
  icon?: LucideIcon;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  flush?: boolean;
}) {
  return (
    <section
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-md border border-line bg-card shadow-card",
        className,
      )}
    >
      {title && (
        <header className="flex items-center gap-2.5 px-5 pb-3 pt-4">
          {Icon && (
            <span className="grid size-7 shrink-0 place-content-center rounded-sm border border-line bg-sunk text-ink-2">
              <Icon size={14} strokeWidth={2} />
            </span>
          )}
          <h2 className="t-h2 text-[14.5px] text-ink">{title}</h2>
          {aside && <div className="ml-auto shrink-0">{aside}</div>}
        </header>
      )}
      <div className={cn(flush ? "" : "px-5 pb-5", title ? "" : "pt-5", "min-w-0 flex-1", bodyClassName)}>
        {children}
      </div>
    </section>
  );
}

/**
 * A headline reading. The number is the point, so it gets the display face at
 * size and weight; the denominator and the caption recede to grey.
 */
export function Stat({
  label,
  value,
  denom,
  sub,
  tone = "ink",
}: {
  label: string;
  value: React.ReactNode;
  denom?: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "ink" | "accent" | "ok" | "warn" | "crit";
}) {
  return (
    <div className="flex min-w-0 flex-col gap-3 rounded-md border border-line bg-card p-5 shadow-card">
      <div className="t-label">{label}</div>
      <div className="flex items-baseline gap-1">
        <span
          className={cn(
            "t-num text-[34px]",
            tone === "accent" && "text-accent",
            tone === "ok" && "text-ok",
            tone === "warn" && "text-warn",
            tone === "crit" && "text-crit",
            tone === "ink" && "text-ink",
          )}
        >
          {value}
        </span>
        {denom !== undefined && (
          <span className="t-num text-[20px] text-ink-4">/{denom}</span>
        )}
      </div>
      {sub && <div className="text-[12.5px] leading-tight text-ink-3">{sub}</div>}
    </div>
  );
}

/** Progress with a real filled track, the way the reference dashboards draw it. */
export function Bar({
  used,
  total,
  tone,
  className,
}: {
  used: number;
  total: number;
  tone?: "accent" | "ok" | "warn" | "crit";
  className?: string;
}) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const auto = pct >= 90 ? "crit" : pct >= 70 ? "warn" : "accent";
  const fill = { accent: "bg-accent", ok: "bg-ok", warn: "bg-warn", crit: "bg-crit" }[
    tone ?? auto
  ];
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-sunk", className)}>
      <div className={cn("h-full rounded-full", fill)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Status({ status }: { status: string }) {
  const s = {
    running: ["text-ok", "bg-ok-soft"],
    queued: ["text-warn", "bg-warn-soft"],
    admitted: ["text-warn", "bg-warn-soft"],
    failed: ["text-crit", "bg-crit-soft"],
  }[status] ?? ["text-ink-3", "bg-idle-soft"];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-medium",
        s[0],
        s[1],
      )}
    >
      <span className={cn("size-1.5 rounded-full", s[0].replace("text-", "bg-"))} />
      {status}
    </span>
  );
}

/** Centred page header, following the reference: title, then one line of what it is. */
export function PageHead({
  title,
  sub,
  aside,
}: {
  title: string;
  sub: string;
  aside?: React.ReactNode;
}) {
  return (
    <div className="relative mb-8 text-center">
      <h1 className="t-h1 text-[38px] text-ink">{title}</h1>
      <p className="mx-auto mt-2 max-w-[52ch] text-[14.5px] text-ink-3">{sub}</p>
      {aside && (
        <div className="mt-4 flex justify-center sm:absolute sm:right-0 sm:top-1 sm:mt-0">
          {aside}
        </div>
      )}
    </div>
  );
}

/** Pill segmented control, used for the policy lever and form kind switch. */
export function Segment({
  options,
  value,
  onSelect,
  disabled,
}: {
  options: { value: string; label: string }[];
  value: string;
  onSelect: (v: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex gap-1 rounded-full bg-sunk p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(o.value)}
          aria-pressed={value === o.value}
          className={cn(
            "rounded-full px-3.5 py-1 text-[12.5px] font-medium disabled:opacity-60",
            value === o.value
              ? "bg-card text-ink shadow-card"
              : "text-ink-3 hover:text-ink",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
