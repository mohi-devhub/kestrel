/** Formatting shared by both views. Kept together so a GPU-second reads the same
 *  everywhere on the dashboard. */

export function gpuSeconds(value: string | number | null): string {
  if (value === null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 3600) return `${(n / 3600).toFixed(2)} GPU-h`;
  return `${n.toFixed(1)} GPU-s`;
}

export function money(value: string | number | null): string {
  if (value === null) return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  return `$${n.toFixed(2)}`;
}

/** Runway is a duration, and `null` genuinely means "infinite", not "unknown". */
export function runway(seconds: string | number | null): string {
  if (seconds === null) return "∞";
  const n = Number(seconds);
  if (!Number.isFinite(n)) return "∞";
  if (n <= 0) return "exhausted";
  if (n >= 86400) return `${(n / 86400).toFixed(1)}d`;
  if (n >= 3600) return `${(n / 3600).toFixed(1)}h`;
  if (n >= 60) return `${(n / 60).toFixed(1)}m`;
  return `${Math.round(n)}s`;
}

/** Matches DEFAULT_RISK_THRESHOLDS in control-plane/economics/runway.py. */
export const RISK_TIER_LABEL = ["safe", "6h", "30m", "<5m"] as const;

export function riskTone(tier: number): string {
  return (
    [
      "text-emerald-600 dark:text-emerald-400",
      "text-yellow-600 dark:text-yellow-400",
      "text-orange-600 dark:text-orange-400",
      "text-red-600 dark:text-red-400",
    ][tier] ?? "text-muted-foreground"
  );
}

export function statusTone(status: string): string {
  switch (status) {
    case "running":
      return "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border-emerald-500/30";
    case "queued":
    case "admitted":
      return "bg-amber-500/15 text-amber-700 dark:text-amber-300 border-amber-500/30";
    case "succeeded":
      return "bg-sky-500/15 text-sky-700 dark:text-sky-300 border-sky-500/30";
    case "failed":
      return "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}

export function ago(iso: string | null): string {
  if (!iso) return "—";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return `${Math.max(0, Math.round(secs))}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}
