import { cn } from "cn";

/**
 * Console layout primitives.
 *
 * These replace the card grid the first version shipped with. At instrument
 * density a card is the wrong container: a border and a shadow both say
 * "separate object", and when every region says that, nothing reads as more
 * important than anything else. Regions are separated by a rule and a label
 * instead, so weight and position carry the hierarchy.
 */

export function Section({
  title,
  aside,
  children,
  className,
}: {
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("min-w-0", className)}>
      <header className="flex items-center justify-between gap-3 border-b border-line-strong pb-1.5">
        <h2 className="label text-fg-muted">{title}</h2>
        {aside}
      </header>
      <div className="pt-3">{children}</div>
    </section>
  );
}

/**
 * A single reading. Label above, value below, no box.
 * `tone` is semantic status, never the accent.
 */
export function Reading({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "ok" | "warn" | "crit";
}) {
  return (
    <div className="px-4 py-3 first:pl-0">
      <div className="label">{label}</div>
      <div
        className={cn(
          "num mt-1.5 text-[26px] leading-none",
          tone === "ok" && "text-ok",
          tone === "warn" && "text-warn",
          tone === "crit" && "text-crit",
        )}
      >
        {value}
      </div>
      {sub && <div className="mt-1.5 text-[11px] leading-tight text-fg-dim">{sub}</div>}
    </div>
  );
}

/** A row of readings, divided by hairlines rather than boxed into tiles. */
export function ReadingRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 divide-x divide-line border-y border-line sm:grid-cols-4 sm:divide-y-0 [&>*:nth-child(-n+2)]:border-b [&>*:nth-child(-n+2)]:border-line sm:[&>*]:border-b-0">
      {children}
    </div>
  );
}

/**
 * A capacity bar with no filled background track.
 * The track is a hairline outline; only the used portion carries ink, so a
 * near-empty tenant reads as near-empty at a glance instead of as a big grey bar.
 */
export function Capacity({
  used,
  total,
  className,
}: {
  used: number;
  total: number;
  className?: string;
}) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const tone = pct >= 100 ? "bg-crit" : pct >= 75 ? "bg-warn" : "bg-accent";
  return (
    <div
      className={cn("h-1 w-full border border-line-soft", className)}
      role="img"
      aria-label={`${used} of ${total}`}
    >
      <div className={cn("h-full", tone)} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Status as a tinted keyword, not a pill with its own border radius debate. */
export function Status({ status }: { status: string }) {
  const tone =
    status === "running"
      ? "text-ok bg-ok-weak"
      : status === "queued" || status === "admitted"
        ? "text-warn bg-warn-weak"
        : status === "failed"
          ? "text-crit bg-crit-weak"
          : "text-fg-dim bg-bg-sunk";
  return (
    <span className={cn("num inline-block px-1.5 py-0.5 text-[11px] leading-tight", tone)}>
      {status}
    </span>
  );
}
