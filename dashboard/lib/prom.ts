/**
 * Server-side Prometheus reader.
 *
 * The dashboard renders its own charts rather than embedding Grafana, so all it
 * needs from Prometheus is the query API. Range queries back the time-series
 * panels; instant queries are only used where a value has no other source.
 */

const BASE = process.env.PROMETHEUS_URL ?? "http://127.0.0.1:9090";

export type Series = {
  metric: Record<string, string>;
  values: [number, number][];
};

type PromRangeResponse = {
  status: string;
  data?: { result: { metric: Record<string, string>; values: [number, string][] }[] };
  error?: string;
};

/**
 * A range query, already shaped for charting: numeric values, sorted by time.
 *
 * Returns an empty array rather than throwing when Prometheus is unreachable or
 * has no samples yet. A freshly started stack legitimately has no history, and a
 * chart with no line is the honest rendering of that.
 */
export async function queryRange(
  query: string,
  windowSeconds = 900,
  stepSeconds = 15,
): Promise<Series[]> {
  const end = Math.floor(Date.now() / 1000);
  const start = end - windowSeconds;
  const url =
    `${BASE}/api/v1/query_range?query=${encodeURIComponent(query)}` +
    `&start=${start}&end=${end}&step=${stepSeconds}`;

  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return [];
    const body = (await res.json()) as PromRangeResponse;
    if (body.status !== "success" || !body.data) return [];
    return body.data.result.map((r) => ({
      metric: r.metric,
      values: r.values
        .map(([t, v]) => [t, Number(v)] as [number, number])
        .filter(([, v]) => Number.isFinite(v)),
    }));
  } catch {
    return [];
  }
}

type PromInstantResponse = {
  status: string;
  data?: { result: { metric: Record<string, string>; value: [number, string] }[] };
};

/**
 * An instant query, flattened to {labelValue: number} on one label.
 *
 * Used where the control plane's REST API doesn't already carry the number and a
 * per-row API call would be worse, e.g. every tenant's risk tier on the tenant
 * list, which is one query here versus one /explain call per tenant.
 */
export async function queryInstantBy(
  query: string,
  labelKey: string,
): Promise<Record<string, number>> {
  try {
    const res = await fetch(`${BASE}/api/v1/query?query=${encodeURIComponent(query)}`, {
      cache: "no-store",
    });
    if (!res.ok) return {};
    const body = (await res.json()) as PromInstantResponse;
    if (body.status !== "success" || !body.data) return {};
    const out: Record<string, number> = {};
    for (const r of body.data.result) {
      const key = r.metric[labelKey];
      const value = Number(r.value[1]);
      if (key !== undefined && Number.isFinite(value)) out[key] = value;
    }
    return out;
  } catch {
    return {};
  }
}

export async function isPrometheusUp(): Promise<boolean> {
  try {
    const res = await fetch(`${BASE}/-/healthy`, { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}
