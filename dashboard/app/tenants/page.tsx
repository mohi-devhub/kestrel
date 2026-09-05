import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { AutoRefresh } from "@/components/auto-refresh";
import { Bar, PageHead, Status } from "@/components/shell";
import { clusterWorkloads, listTenants } from "@/lib/kestrel";
import { queryInstantBy } from "@/lib/prom";
import { RISK_TIER_LABEL, gpuSeconds } from "@/lib/format";
import { cn } from "cn";

export const dynamic = "force-dynamic";

const RISK_STYLE = [
  "bg-ok-soft text-ok",
  "bg-sunk text-ink-2",
  "bg-warn-soft text-warn",
  "bg-crit-soft text-crit",
];

export default async function TenantsPage() {
  // Held GPUs come from the control plane; runway and spend come from the metrics
  // it exposes, which is one query for all tenants rather than a call per row.
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
    return {
      tenant: t,
      held,
      queued: mine.filter((w) => w.status === "queued" || w.status === "admitted").length,
      running: running.length,
      tier: tiers[t.slug],
      used: spend[t.slug],
    };
  });

  return (
    <div>
      <PageHead
        title="Tenants"
        sub="Every tenant with quota on this cluster. Pick one to submit work and read its meter."
        aside={<AutoRefresh seconds={8} />}
      />

      {tenants.length === 0 ? (
        <p className="rounded-md border border-dashed border-line-2 bg-card px-5 py-14 text-center text-[13px] text-ink-3">
          No tenants yet. Create one with{" "}
          <code className="t-mono text-[12.5px] text-ink-2">POST /admin/tenants</code>.
        </p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {rows.map(({ tenant, held, queued, running, tier, used }) => {
            const budgeted = tenant.gpu_second_budget !== null;
            return (
              <Link
                key={tenant.id}
                href={`/tenants/${tenant.id}`}
                className="group flex flex-col gap-4 rounded-md border border-line bg-card p-5 shadow-card transition-all hover:-translate-y-px hover:border-accent-line hover:shadow-float"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="t-h2 truncate text-[16px] text-ink">{tenant.name}</div>
                    <div className="t-mono mt-0.5 truncate text-[12px] text-ink-3">
                      {tenant.slug}
                    </div>
                  </div>
                  <ArrowUpRight
                    size={16}
                    className="shrink-0 text-ink-4 transition-colors group-hover:text-accent"
                  />
                </div>

                <div>
                  <div className="mb-1.5 flex items-baseline justify-between">
                    <span className="t-label">GPUs held</span>
                    <span className="t-num text-[17px] text-ink">
                      {held}
                      <span className="text-ink-4">/{tenant.max_gpus}</span>
                    </span>
                  </div>
                  <Bar used={held} total={tenant.max_gpus} />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {running > 0 && <Status status="running" />}
                  {queued > 0 && <Status status="queued" />}
                  {running === 0 && queued === 0 && (
                    <span className="rounded-full bg-idle-soft px-2.5 py-1 text-[11.5px] font-medium text-ink-3">
                      idle
                    </span>
                  )}
                  {budgeted && tier !== undefined && (
                    <span
                      className={cn(
                        "rounded-full px-2.5 py-1 text-[11.5px] font-medium",
                        RISK_STYLE[tier] ?? "bg-sunk text-ink-2",
                      )}
                    >
                      runway {RISK_TIER_LABEL[tier]}
                    </span>
                  )}
                </div>

                <div className="flex items-baseline justify-between border-t border-line pt-3">
                  <span className="t-label">Metered</span>
                  <span className="text-[13px] font-medium text-ink-2">
                    {used === undefined ? "-" : gpuSeconds(used)}
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
