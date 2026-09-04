/**
 * Server-side client for the Kestrel control plane.
 *
 * This module must never be imported into a client component. It holds the admin
 * token, and it is the reason the browser never sees a credential: every call the
 * dashboard makes goes out from the Next.js server, not from the page.
 *
 * Two credentials are in play, and the split is deliberate:
 *
 *   - The admin token reaches admin-only surfaces: listing tenants, the cluster
 *     view, switching the active placement policy.
 *   - Tenant-scoped data (workloads, usage, runway, explain) is read with a real
 *     per-tenant API key, minted on demand through POST /admin/tenants/{id}/api-keys
 *     and cached in this process. The console could have been given a master-key
 *     bypass instead; using a genuine key means the dashboard exercises exactly the
 *     path a customer's own client would, and the tenant auth boundary that Phase 1
 *     built stays intact rather than being special-cased for the demo.
 */

const BASE = process.env.KESTREL_API_URL ?? "http://127.0.0.1:8000";
const ADMIN_TOKEN = process.env.KESTREL_ADMIN_TOKEN ?? "dev-admin-token";

export type Tenant = {
  id: string;
  slug: string;
  name: string;
  max_gpus: number;
  max_workloads: number;
  gpu_second_budget: number | null;
  price_per_gpu_hour: number;
  created_at: string;
};

export type Workload = {
  id: string;
  tenant_id: string;
  kind: "job" | "endpoint";
  status: string;
  spec: Record<string, unknown>;
  gpus_requested: number;
  priority: number;
  namespace: string;
  k8s_name: string;
  node_name: string | null;
  placement_policy: string | null;
  replicas: number | null;
  created_at: string;
  admitted_at: string | null;
  started_at: string | null;
  ended_at: string | null;
};

export type NodeUsage = {
  name: string;
  ready: boolean;
  gpu_total: number;
  gpu_used: number;
  gpu_free: number;
  cpu_capacity: string;
  memory_capacity: string;
};

export type WorkloadUsage = {
  workload_id: string;
  kind: string;
  gpu_seconds: string;
  cost: string;
};

export type Usage = {
  tenant_id: string;
  period_start: string;
  period_end: string;
  total_gpu_seconds: string;
  estimated_cost: string;
  workloads: WorkloadUsage[];
};

export type Explain = {
  workload_id: string;
  status: string;
  quota: { passes: boolean; reason: string | null };
  kueue_admitted: boolean | null;
  ordering: {
    rank: number;
    total_admitted: number;
    would_place_on: string | null;
    blocked_reason: string | null;
  } | null;
  runway: {
    burn_rate_gpus: number;
    remaining_gpu_seconds: string | null;
    runway_seconds: string | null;
    risk_tier: number;
    is_exhausted: boolean;
  };
};

export class KestrelError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

async function call<T>(path: string, headers: HeadersInit, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...headers, ...(init?.headers ?? {}) },
    // Every view is a live read of platform state; a cached answer would be a lie.
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try {
      detail = (JSON.parse(body).detail as string) ?? body;
    } catch {
      /* a non-JSON error body is still worth surfacing verbatim */
    }
    throw new KestrelError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const admin = { "x-kestrel-admin-token": ADMIN_TOKEN };

export function asAdmin<T>(path: string, init?: RequestInit): Promise<T> {
  return call<T>(path, admin, init);
}

/**
 * Per-tenant API keys, minted once per tenant per server process.
 *
 * Keys are hashed at rest and never expire, so re-minting after a dev-server
 * restart costs one extra row and nothing else. Kept in memory rather than a
 * cookie or the database: the console is a local operator tool, and a key that
 * outlives the process it was minted for would be a credential nobody is tracking.
 */
const keyCache = new Map<string, string>();

async function keyFor(tenantId: string): Promise<string> {
  const cached = keyCache.get(tenantId);
  if (cached) return cached;
  const issued = await asAdmin<{ key: string }>(`/admin/tenants/${tenantId}/api-keys`, {
    method: "POST",
  });
  keyCache.set(tenantId, issued.key);
  return issued.key;
}

export async function asTenant<T>(
  tenantId: string,
  path: string,
  init?: RequestInit,
): Promise<T> {
  const key = await keyFor(tenantId);
  try {
    return await call<T>(path, { "x-kestrel-key": key }, init);
  } catch (err) {
    // A cached key can outlive the database it was minted against. A reset or a
    // re-seeded volume leaves this process holding a key the control plane has
    // never seen. Mint once more before giving up.
    if (err instanceof KestrelError && err.status === 401) {
      keyCache.delete(tenantId);
      const fresh = await keyFor(tenantId);
      return call<T>(path, { "x-kestrel-key": fresh }, init);
    }
    throw err;
  }
}

export const listTenants = () => asAdmin<Tenant[]>("/admin/tenants");
export const clusterNodes = () => asAdmin<NodeUsage[]>("/cluster/nodes");
export const clusterWorkloads = () => asAdmin<Workload[]>("/cluster/workloads");
export const activePolicy = () => asAdmin<{ name: string }>("/admin/policy");
export const setPolicy = (name: string) =>
  asAdmin<{ name: string }>("/admin/policy", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const tenantJobs = (t: string) => asTenant<Workload[]>(t, "/jobs");
export const tenantEndpoints = (t: string) => asTenant<Workload[]>(t, "/endpoints");
export const tenantUsage = (t: string) => asTenant<Usage>(t, `/tenants/${t}/usage`);
export const explainWorkload = (t: string, id: string) =>
  asTenant<Explain>(t, `/workloads/${id}/explain`);

export const submitJob = (
  t: string,
  body: { image: string; command: string[]; gpus: number; priority: number },
) => asTenant<Workload>(t, "/jobs", { method: "POST", body: JSON.stringify(body) });

export const submitEndpoint = (
  t: string,
  body: {
    image: string;
    gpus: number;
    min_replicas: number;
    max_replicas: number;
    port: number;
  },
) => asTenant<Workload>(t, "/endpoints", { method: "POST", body: JSON.stringify(body) });

export const cancelJob = (t: string, id: string) =>
  asTenant<void>(t, `/jobs/${id}`, { method: "DELETE" });
export const teardownEndpoint = (t: string, id: string) =>
  asTenant<void>(t, `/endpoints/${id}`, { method: "DELETE" });
