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

const STROKES = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
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
        className="flex items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground"
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
      <LineChart data={rows} margin={{ top: 6, right: 10, bottom: 0, left: -18 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" vertical={false} />
        <XAxis
          dataKey="t"
          tickFormatter={clock}
          stroke="var(--color-muted-foreground)"
          fontSize={11}
          tickLine={false}
          minTickGap={48}
        />
        <YAxis
          stroke="var(--color-muted-foreground)"
          fontSize={11}
          tickLine={false}
          axisLine={false}
          allowDecimals={!step}
          width={46}
        />
        <Tooltip
          labelFormatter={(t) => clock(Number(t))}
          formatter={(value, name) => [`${value ?? "—"}${unit}`, String(name)]}
          contentStyle={{
            background: "var(--color-popover)",
            border: "1px solid var(--color-border)",
            borderRadius: 8,
            fontSize: 12,
            color: "var(--color-popover-foreground)",
          }}
        />
        {/* Past a handful of series a legend costs more height than it explains;
            the tooltip still names every line on hover. */}
        {names.length > 1 && names.length <= 6 && <Legend wrapperStyle={{ fontSize: 11 }} />}
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
