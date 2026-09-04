/** Formatting shared by both views, so a GPU-second reads the same everywhere.
 *
 *  Empty values render as a plain hyphen. Not an em-dash: the console uses one
 *  dash character throughout, and a wider glyph in a mono column breaks the
 *  vertical alignment that makes a table scannable. */

const NONE = "-";

export function gpuSeconds(value: string | number | null): string {
  if (value === null) return NONE;
  const n = Number(value);
  if (!Number.isFinite(n)) return NONE;
  if (Math.abs(n) >= 3600) return `${(n / 3600).toFixed(2)} GPU-h`;
  return `${n.toFixed(1)} GPU-s`;
}

export function money(value: string | number | null): string {
  if (value === null) return NONE;
  const n = Number(value);
  if (!Number.isFinite(n)) return NONE;
  return `$${n.toFixed(2)}`;
}

/** Runway is a duration, and `null` genuinely means infinite, not unknown. */
export function runway(seconds: string | number | null): string {
  if (seconds === null) return "∞";
  const n = Number(seconds);
  if (!Number.isFinite(n)) return "∞";
  if (n <= 0) return "spent";
  if (n >= 86400) return `${(n / 86400).toFixed(1)}d`;
  if (n >= 3600) return `${(n / 3600).toFixed(1)}h`;
  if (n >= 60) return `${(n / 60).toFixed(1)}m`;
  return `${Math.round(n)}s`;
}

/** Matches DEFAULT_RISK_THRESHOLDS in control-plane/economics/runway.py. */
export const RISK_TIER_LABEL = ["safe", "under 6h", "under 30m", "under 5m"] as const;

export function riskTone(tier: number): string {
  return ["text-ok", "text-warn", "text-warn", "text-crit"][tier] ?? "text-fg-dim";
}

export function ago(iso: string | null): string {
  if (!iso) return NONE;
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 60) return `${Math.max(0, Math.round(secs))}s`;
  if (secs < 3600) return `${Math.round(secs / 60)}m`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h`;
  return `${Math.round(secs / 86400)}d`;
}

export { NONE };
