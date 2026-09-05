"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Series } from "@/lib/prom";

// Accent first, then cool neutrals. Series colour is identity, not decoration,
// so the palette stays inside the console's own range.
const STROKES = [
  "var(--color-accent)",
  "var(--color-ok)",
  "var(--color-warn)",
  "var(--color-crit)",
  "var(--color-ink-3)",
];

function clock(t: number): string {
  return new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * A Prometheus range result, drawn directly.
 *
 * Series are keyed by whichever label distinguishes them (tenant, endpoint, node),
 * and the rows are aligned on timestamp so one <LineChart> can hold all of them.
 * Step lines for replica counts and queue depth: those are integers that hold a
 * value until something changes them, and interpolating between them would draw
 * fractional replicas that never existed.
 */
export function TimeSeries({
  series,
  labelKey,
  step = false,
  height = 200,
  unit = "",
  emptyMessage = "No samples in this window yet.",
}: {
  series: Series[];
  labelKey: string;
  step?: boolean;
  height?: number;
  unit?: string;
  emptyMessage?: string;
}) {
  if (series.length === 0) {
    return (
      <div
        style={{ height }}
        className="flex items-center justify-center rounded-sm border border-dashed border-line-2 bg-sunk/40 px-4 text-center text-[12.5px] text-ink-3"
      >
        {emptyMessage}
      </div>
    );
  }

  const names = series.map((s, i) => s.metric[labelKey] ?? `series ${i + 1}`);
  const byTime = new Map<number, Record<string, number>>();
  series.forEach((s, i) => {
    for (const [t, v] of s.values) {
      const row = byTime.get(t) ?? { t };
      row[names[i]] = v;
      byTime.set(t, row);
    }
  });
  const rows = [...byTime.values()].sort((a, b) => a.t - b.t);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={rows} margin={{ top: 8, right: 10, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--color-line)" vertical={false} />
        <XAxis
          dataKey="t"
          tickFormatter={clock}
          stroke="var(--color-ink-3)"
          fontSize={10}
          tickLine={false}
          axisLine={{ stroke: "var(--color-line)" }}
          minTickGap={44}
          style={{ fontFamily: "var(--font-mono)" }}
        />
        <YAxis
          stroke="var(--color-ink-3)"
          fontSize={10}
          tickLine={false}
          axisLine={false}
          allowDecimals={!step}
          domain={[0, "auto"]}
          width={30}
          style={{ fontFamily: "var(--font-mono)" }}
        />
        <Tooltip
          labelFormatter={(t) => clock(Number(t))}
          formatter={(value, name) => [`${value ?? "-"}${unit}`, String(name)]}
          contentStyle={{
            background: "var(--color-card)",
            border: "1px solid var(--color-line)",
            borderRadius: 10,
            boxShadow: "var(--shadow-float)",
            fontSize: 11,
            fontFamily: "var(--font-mono)",
            color: "var(--color-ink)",
          }}
        />
        {/* Past a handful of series a legend costs more height than it explains;
            the tooltip still names every line on hover. */}
        {names.length > 1 && names.length <= 6 && (
          <Legend wrapperStyle={{ fontSize: 10, fontFamily: "var(--font-mono)" }} iconSize={8} />
        )}
        {names.map((name, i) => (
          <Line
            key={name}
            type={step ? "stepAfter" : "monotone"}
            dataKey={name}
            stroke={STROKES[i % STROKES.length]}
            strokeWidth={2}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
