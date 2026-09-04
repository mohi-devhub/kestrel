import Link from "next/link";
import { notFound } from "next/navigation";

import { AutoRefresh } from "@/components/auto-refresh";
import { Meter, PageHead, Panel, Stat, StatRow } from "@/components/shell";
import { SubmitForms } from "@/components/submit-forms";
import { TimeSeries } from "@/components/timeseries";
import { WorkloadRow } from "@/components/workload-row";
import {
  type Explain,
  explainWorkload,
  listTenants,
  tenantEndpoints,
  tenantJobs,
  tenantUsage,
} from "@/lib/kestrel";
import { queryRange } from "@/lib/prom";
import { RISK_TIER_LABEL, gpuSeconds, money, riskTone, runway } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function TenantPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const tenants = await listTenants();
  const tenant = tenants.find((t) => t.id === id);
  if (!tenant) notFound();

  const [jobs, endpoints, usage, replicaSeries] = await Promise.all([
    tenantJobs(id),
    tenantEndpoints(id),
    tenantUsage(id),
    queryRange(`kestrel_autoscale_replicas{tenant="${tenant.slug}"}`),
  ]);

  const workloads = [...jobs, ...endpoints].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
  const running = workloads.filter((w) => w.status === "running");
  const held = running.reduce(
    (n, w) => n + (w.kind === "endpoint" ? w.gpus_requested * (w.replicas ?? 0) : w.gpus_requested),
    0,
  );

  // Runway is read off a live workload's explain rather than recomputed here, so
  // this page cannot disagree with the scheduler.
  let tenantRunway: Explain["runway"] | null = null;
  const probe = running[0] ?? workloads[0];
  if (probe) {
    try {
      tenantRunway = (await explainWorkload(id, probe.id)).runway;
    } catch {
      tenantRunway = null;
    }
  }

  const budgetUsed = Number(usage.total_gpu_seconds);

  async function explain(workloadId: string): Promise<Explain | { error: string }> {
    "use server";
    try {
      return await explainWorkload(id, workloadId);
    } catch (err) {
      return { error: err instanceof Error ? err.message : "explain failed" };
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHead
        back={
          <Link href="/tenants" className="mb-1 inline-block text-[11.5px] text-ink-4 hover:text-ink">
            Tenants
          </Link>
        }
        title={<span className="t-mono text-[20px]">{tenant.slug}</span>}
        sub={`${tenant.name} · $${tenant.price_per_gpu_hour} per GPU-hour`}
        aside={<AutoRefresh seconds={5} />}
      />

      <StatRow>
        <Stat
          label="Concurrent GPUs"
          value={
            <>
              {held}
              <span className="text-ink-4">/{tenant.max_gpus}</span>
            </>
          }
          sub={<Meter used={held} total={tenant.max_gpus} className="mt-1 max-w-[130px]" />}
          tone={held > 0 ? "accent" : undefined}
        />
        <Stat
          label="Budget"
          value={
            tenant.gpu_second_budget === null ? (
              <span className="text-ink-3">none</span>
            ) : (
              <>
                {budgetUsed.toFixed(0)}
                <span className="text-ink-4">/{tenant.gpu_second_budget}</span>
              </>
            )
          }
          sub={
            tenant.gpu_second_budget === null ? (
              "no cap configured"
            ) : (
              <Meter used={budgetUsed} total={tenant.gpu_second_budget} className="mt-1 max-w-[130px]" />
            )
          }
        />
        <Stat
          label="Runway"
          value={
            tenantRunway ? (
              <span className={riskTone(tenantRunway.risk_tier)}>
                {runway(tenantRunway.runway_seconds)}
              </span>
            ) : (
              <span className="text-ink-4">-</span>
            )
          }
          sub={
            tenantRunway
              ? `${RISK_TIER_LABEL[tenantRunway.risk_tier]}, burning ${tenantRunway.burn_rate_gpus} GPU/s`
              : "submit a workload to read it"
          }
        />
        <Stat
          label="Cost this period"
          value={money(usage.estimated_cost)}
          sub={gpuSeconds(usage.total_gpu_seconds)}
        />
      </StatRow>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_296px]">
        <div className="flex flex-col gap-5">
          <Panel title="Workloads" flush>
            {workloads.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[700px] border-collapse">
                  <thead>
                    <tr className="border-b border-hair">
                      <th className="t-label py-2 pl-4 pr-3 text-left font-medium">Name</th>
                      <th className="t-label w-[92px] py-2 pr-3 text-left font-medium">Status</th>
                      <th className="t-label w-[88px] py-2 pr-3 text-right font-medium">GPUs</th>
                      <th className="t-label w-[152px] py-2 pr-3 text-left font-medium">Node</th>
                      <th className="t-label w-[112px] py-2 pr-3 text-left font-medium">Policy</th>
                      <th className="t-label w-[56px] py-2 pr-3 text-right font-medium">Age</th>
                      <th className="w-[108px] pr-4" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-hair">
                    {workloads.map((w) => (
                      <WorkloadRow key={w.id} workload={w} tenantId={id} explain={explain} />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="px-4 py-10 text-center text-[12.5px] text-ink-4">
                Nothing submitted yet.
              </p>
            )}
          </Panel>

          <Panel
            title="Endpoint replicas"
            aside={<span className="t-mono text-[10.5px] text-ink-4">15m</span>}
          >
            <TimeSeries
              series={replicaSeries}
              labelKey="endpoint"
              step
              height={140}
              emptyMessage="No endpoints scaling in this window."
            />
          </Panel>
        </div>

        <div className="flex flex-col gap-5">
          <Panel title="Submit work">
            <SubmitForms tenantId={id} />
          </Panel>

          <Panel title="Metered this period" flush>
            {usage.workloads.length > 0 ? (
              <ul className="divide-y divide-hair">
                {usage.workloads.slice(0, 9).map((w) => (
                  <li key={w.workload_id} className="flex justify-between gap-2 px-4 py-2">
                    <span className="t-mono truncate text-[11.5px] text-ink-3">
                      {w.workload_id.slice(0, 8)} {w.kind}
                    </span>
                    <span className="t-mono shrink-0 text-[11.5px] text-ink-2">{money(w.cost)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-4 py-6 text-[12.5px] text-ink-4">Nothing metered this period.</p>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
