import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { clusterWorkloads, listTenants } from "@/lib/kestrel";
import { queryInstantBy } from "@/lib/prom";
import { RISK_TIER_LABEL, gpuSeconds, riskTone } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function TenantsPage() {
  // Held GPUs come from the control plane; runway and spend come from the metrics
  // it exposes — one query for every tenant, rather than an /explain per row.
  const [tenants, workloads, tiers, spend] = await Promise.all([
    listTenants(),
    clusterWorkloads(),
    queryInstantBy("kestrel_tenant_risk_tier", "tenant"),
    queryInstantBy("kestrel_tenant_gpu_seconds_total", "tenant"),
  ]);

  const rows = tenants.map((t) => {
    const mine = workloads.filter((w) => w.tenant_id === t.id);
    const running = mine.filter((w) => w.status === "running");
    const held = running.reduce(
      (n, w) =>
        n + (w.kind === "endpoint" ? w.gpus_requested * (w.replicas ?? 0) : w.gpus_requested),
      0,
    );
    const queued = mine.filter((w) => w.status === "queued" || w.status === "admitted").length;
    return {
      tenant: t,
      held,
      queued,
      running: running.length,
      tier: tiers[t.slug],
      used: spend[t.slug],
    };
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Tenants</h1>
          <p className="text-sm text-muted-foreground">
            Every tenant with quota on this cluster. Pick one to submit work and read its meter.
          </p>
        </div>
        <AutoRefresh seconds={8} />
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {rows.map(({ tenant, held, queued, running, tier, used }) => {
          const pct = tenant.max_gpus > 0 ? Math.min(100, (held / tenant.max_gpus) * 100) : 0;
          const budgeted = tenant.gpu_second_budget !== null;
          return (
            <Link key={tenant.id} href={`/tenants/${tenant.id}`} className="group">
              <Card className="h-full transition-colors group-hover:border-primary/50">
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-baseline justify-between gap-2 text-base">
                    <span className="truncate font-mono text-sm">{tenant.slug}</span>
                    <span className="tabular shrink-0 text-xs font-normal text-muted-foreground">
                      {held}/{tenant.max_gpus} GPU
                    </span>
                  </CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div
                    className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
                    role="img"
                    aria-label={`${held} of ${tenant.max_gpus} GPUs held`}
                  >
                    <div
                      className={
                        pct >= 100
                          ? "h-full bg-red-500"
                          : pct >= 75
                            ? "h-full bg-amber-500"
                            : "h-full bg-emerald-500"
                      }
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <dl className="grid grid-cols-3 gap-2 text-xs">
                    <Cell label="running" value={String(running)} />
                    <Cell label="queued" value={String(queued)} />
                    <Cell label="metered" value={used === undefined ? "—" : gpuSeconds(used)} />
                  </dl>
                  <div className="flex items-center justify-between border-t pt-2 text-xs">
                    <span className="text-muted-foreground">
                      {budgeted ? `budget ${tenant.gpu_second_budget}s` : "no budget"}
                    </span>
                    {budgeted && tier !== undefined && (
                      <span className={riskTone(tier)}>
                        runway {RISK_TIER_LABEL[tier] ?? "—"}
                      </span>
                    )}
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>

      {tenants.length === 0 && (
        <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No tenants yet. Create one with{" "}
          <code className="font-mono text-xs">POST /admin/tenants</code>.
        </p>
      )}
    </div>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-[0.1em] text-muted-foreground">{label}</dt>
      <dd className="tabular mt-0.5 text-sm">{value}</dd>
    </div>
  );
}
