import { cn } from "cn";

/**
 * Console layout primitives, built on the surface ladder.
 *
 * The previous pass used hairlines on a flat ground and nothing else. That reads
 * as unfinished, because with no elevation anywhere the eye has nothing to rank.
 * Here a Panel is a real surface (one step off the canvas, hairline border, 8px
 * radius) and hierarchy comes from which rung a thing sits on, never from a
 * shadow.
 */

export function Panel({
  title,
  aside,
  children,
  className,
  bodyClassName,
  flush,
}: {
  title?: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Body runs to the panel edges. For tables and maps that supply their own rows. */
  flush?: boolean;
}) {
  return (
    <section
      className={cn(
        "flex min-w-0 flex-col overflow-hidden rounded-md border border-hair bg-s1",
        className,
      )}
    >
      {title && (
        <header className="flex items-center justify-between gap-3 border-b border-hair px-4 py-2.5">
          <h2 className="t-label">{title}</h2>
          {aside}
        </header>
      )}
      <div className={cn(flush ? "" : "p-4", "min-w-0 flex-1", bodyClassName)}>{children}</div>
    </section>
  );
}

/**
 * A headline reading. Big, mono, tightly tracked.
 * `tone` is semantic state and never the accent.
 */
export function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: "ok" | "queue" | "crit" | "accent";
}) {
  return (
    <div className="flex min-w-0 flex-col justify-between gap-3 p-4">
      <div className="t-label">{label}</div>
      <div>
        <div
          className={cn(
            "t-display text-[30px] leading-none",
            tone === "ok" && "text-ok",
            tone === "queue" && "text-queue",
            tone === "crit" && "text-crit",
            tone === "accent" && "text-accent",
          )}
        >
          {value}
        </div>
        {sub && <div className="mt-2 text-[11.5px] leading-tight text-ink-4">{sub}</div>}
      </div>
    </div>
  );
}

/** Stats sit in one panel divided by hairlines, not four separate boxes. */
export function StatRow({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 divide-hair overflow-hidden rounded-md border border-hair bg-s1 sm:grid-cols-4 sm:divide-x [&>*:nth-child(-n+2)]:border-b [&>*:nth-child(-n+2)]:border-hair [&>*:nth-child(odd)]:border-r sm:[&>*]:border-b-0 sm:[&>*:nth-child(odd)]:border-r-0">
      {children}
    </div>
  );
}

/** Capacity meter: outlined track, ink only on the used portion. */
export function Meter({
  used,
  total,
  className,
}: {
  used: number;
  total: number;
  className?: string;
}) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const tone = pct >= 100 ? "bg-crit" : pct >= 80 ? "bg-crit" : "bg-accent";
  return (
    <div
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-s3", className)}
      role="img"
      aria-label={`${used} of ${total}`}
    >
      <div className={cn("h-full rounded-full", tone)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Status({ status }: { status: string }) {
  const tone =
    status === "running"
      ? "text-ok bg-ok-weak"
      : status === "queued" || status === "admitted"
        ? "text-queue bg-queue-weak"
        : status === "failed"
          ? "text-crit bg-crit-weak"
          : "text-ink-4 bg-s3";
  return (
    <span
      className={cn(
        "t-mono inline-flex items-center rounded-sm px-1.5 py-0.5 text-[11px] leading-[1.4]",
        tone,
      )}
    >
      {status}
    </span>
  );
}

export function PageHead({
  title,
  sub,
  aside,
  back,
}: {
  title: React.ReactNode;
  sub?: React.ReactNode;
  aside?: React.ReactNode;
  back?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {back}
        <h1 className="t-title text-[21px] leading-tight">{title}</h1>
        {sub && <p className="mt-0.5 text-[12.5px] text-ink-3">{sub}</p>}
      </div>
      {aside}
    </div>
  );
}
