import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { Meter, PageHead, Panel } from "@/components/shell";
import { clusterWorkloads, listTenants } from "@/lib/kestrel";
import { queryInstantBy } from "@/lib/prom";
import { RISK_TIER_LABEL, gpuSeconds, riskTone } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * Tenants as a register, not a card grid: every row carries the same readings in
 * the same columns, so the eye scans down one column to compare tenants. Cards
 * would put each tenant's numbers somewhere different and make that impossible.
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
    <div className="flex flex-col gap-5">
      <PageHead
        title="Tenants"
        sub="Pick one to submit work and read its meter."
        aside={<AutoRefresh seconds={8} />}
      />

      <Panel flush>
        {tenants.length === 0 ? (
          <p className="px-4 py-10 text-center text-[12.5px] text-ink-4">
            No tenants yet. Create one with{" "}
            <code className="t-mono text-[12px] text-ink-3">POST /admin/tenants</code>.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse">
              <thead>
                <tr className="border-b border-hair">
                  <Th className="pl-4 text-left">Tenant</Th>
                  <Th className="w-[190px] text-left">GPUs held</Th>
                  <Th className="w-[86px] text-right">Running</Th>
                  <Th className="w-[86px] text-right">Queued</Th>
                  <Th className="w-[124px] text-right">Metered</Th>
                  <Th className="w-[132px] pr-4 text-right">Runway</Th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hair">
                {rows.map(({ tenant, held, queued, running, tier, used }) => {
                  const budgeted = tenant.gpu_second_budget !== null;
                  return (
                    <tr key={tenant.id} className="group transition-colors hover:bg-s2">
                      <td className="py-2.5 pl-4 pr-3">
                        <Link href={`/tenants/${tenant.id}`} className="block">
                          <span className="t-mono block text-[12.5px] text-ink group-hover:text-accent">
                            {tenant.slug}
                          </span>
                          <span className="block text-[11px] leading-tight text-ink-4">
                            {tenant.name}
                          </span>
                        </Link>
                      </td>
                      <td className="py-2.5 pr-3">
                        <div className="flex items-center gap-2.5">
                          <Meter used={held} total={tenant.max_gpus} className="w-24" />
                          <span className="t-mono text-[12px] text-ink-2">
                            {held}
                            <span className="text-ink-4">/{tenant.max_gpus}</span>
                          </span>
                        </div>
                      </td>
                      <td className="t-mono py-2.5 pr-3 text-right text-[12.5px] text-ink-2">
                        {running || <span className="text-ink-4">0</span>}
                      </td>
                      <td className="t-mono py-2.5 pr-3 text-right text-[12.5px]">
                        {queued > 0 ? (
                          <span className="text-queue">{queued}</span>
                        ) : (
                          <span className="text-ink-4">0</span>
                        )}
                      </td>
                      <td className="t-mono py-2.5 pr-3 text-right text-[12px] text-ink-3">
                        {used === undefined ? "-" : gpuSeconds(used)}
                      </td>
                      <td className="py-2.5 pr-4 text-right">
                        {budgeted && tier !== undefined ? (
                          <span className={`t-mono text-[12px] ${riskTone(tier)}`}>
                            {RISK_TIER_LABEL[tier]}
                          </span>
                        ) : (
                          <span className="t-mono text-[12px] text-ink-4">no budget</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <th className={`t-label py-2 font-medium ${className}`}>{children}</th>;
}
