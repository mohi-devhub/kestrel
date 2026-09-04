import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { Capacity } from "@/components/panel";
import { clusterWorkloads, listTenants } from "@/lib/kestrel";
import { queryInstantBy } from "@/lib/prom";
import { RISK_TIER_LABEL, gpuSeconds, riskTone } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * Tenants as a register, not a card grid.
 *
 * Every row carries the same five readings in the same columns, so the eye scans
 * down one column to compare tenants. Cards would put each tenant's numbers in a
 * different place on screen and make exactly that comparison impossible.
 */
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
    <div className="space-y-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-[19px] font-semibold">Tenants</h1>
          <p className="text-[12.5px] text-fg-dim">
            Pick one to submit work and read its meter.
          </p>
        </div>
        <AutoRefresh seconds={8} />
      </div>

      {tenants.length === 0 ? (
        <p className="border border-dashed border-line px-4 py-8 text-center text-sm text-fg-dim">
          No tenants yet. Create one with{" "}
          <code className="num text-[12px]">POST /admin/tenants</code>.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse">
            <thead>
              <tr className="border-b border-line-strong">
                <Th className="text-left">Tenant</Th>
                <Th className="w-[168px] text-left">GPUs held</Th>
                <Th className="w-[76px] text-right">Running</Th>
                <Th className="w-[76px] text-right">Queued</Th>
                <Th className="w-[112px] text-right">Metered</Th>
                <Th className="w-[132px] text-right">Runway</Th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-soft">
              {rows.map(({ tenant, held, queued, running, tier, used }) => {
                const budgeted = tenant.gpu_second_budget !== null;
                return (
                  <tr key={tenant.id} className="group hover:bg-bg-sunk">
                    <td className="py-2 pr-3">
                      <Link
                        href={`/tenants/${tenant.id}`}
                        className="num text-[13px] group-hover:text-accent"
                      >
                        {tenant.slug}
                      </Link>
                    </td>
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-2">
                        <Capacity used={held} total={tenant.max_gpus} className="w-20" />
                        <span className="num text-[12px] text-fg-muted">
                          {held}
                          <span className="text-fg-dim">/{tenant.max_gpus}</span>
                        </span>
                      </div>
                    </td>
                    <td className="num py-2 pr-3 text-right text-[12px]">{running}</td>
                    <td
                      className={`num py-2 pr-3 text-right text-[12px] ${
                        queued > 0 ? "text-warn" : "text-fg-dim"
                      }`}
                    >
                      {queued}
                    </td>
                    <td className="num py-2 pr-3 text-right text-[12px] text-fg-muted">
                      {used === undefined ? "-" : gpuSeconds(used)}
                    </td>
                    <td className="py-2 text-right">
                      {budgeted && tier !== undefined ? (
                        <span className={`num text-[12px] ${riskTone(tier)}`}>
                          {RISK_TIER_LABEL[tier]}
                        </span>
                      ) : (
                        <span className="num text-[12px] text-fg-dim">no budget</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <th className={`label pb-1.5 font-normal ${className}`}>{children}</th>;
}
