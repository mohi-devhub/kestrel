import Link from "next/link";
import { notFound } from "next/navigation";

import { AutoRefresh } from "@/components/auto-refresh";
import { Capacity, Reading, ReadingRow, Section } from "@/components/panel";
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

  // Runway for the tenant as a whole is read off a live workload's explain rather
  // than recomputed here, so this page cannot disagree with the scheduler.
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
    <div className="space-y-7">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Link href="/tenants" className="text-[11px] text-fg-dim hover:text-fg">
            Tenants
          </Link>
          <h1 className="reading mt-1 text-[24px] leading-none">{tenant.slug}</h1>
          <p className="text-[12px] text-fg-dim">
            ${tenant.price_per_gpu_hour} per GPU-hour
          </p>
        </div>
        <AutoRefresh seconds={5} />
      </div>

      <ReadingRow>
        <Reading
          label="Concurrent GPUs"
          value={
            <>
              {held}
              <span className="text-fg-dim">/{tenant.max_gpus}</span>
            </>
          }
          sub={<Capacity used={held} total={tenant.max_gpus} className="mt-0.5 max-w-[120px]" />}
        />
        <Reading
          label="Budget"
          value={
            tenant.gpu_second_budget === null ? (
              <span className="text-fg-muted">none</span>
            ) : (
              <>
                {budgetUsed.toFixed(0)}
                <span className="text-fg-dim">/{tenant.gpu_second_budget}s</span>
              </>
            )
          }
          sub={
            tenant.gpu_second_budget === null ? (
              "no cap configured"
            ) : (
              <Capacity
                used={budgetUsed}
                total={tenant.gpu_second_budget}
                className="mt-0.5 max-w-[120px]"
              />
            )
          }
        />
        <Reading
          label="Runway"
          value={
            tenantRunway ? (
              <span className={riskTone(tenantRunway.risk_tier)}>
                {runway(tenantRunway.runway_seconds)}
              </span>
            ) : (
              <span className="text-fg-dim">-</span>
            )
          }
          sub={
            tenantRunway
              ? `${RISK_TIER_LABEL[tenantRunway.risk_tier]}, burning ${tenantRunway.burn_rate_gpus} GPU/s`
              : "submit a workload to read it"
          }
        />
        <Reading
          label="Cost this period"
          value={money(usage.estimated_cost)}
          sub={gpuSeconds(usage.total_gpu_seconds)}
        />
      </ReadingRow>

      <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_282px]">
        <div className="space-y-7">
          <Section title="Workloads">
            {workloads.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[680px] border-collapse">
                  <thead>
                    <tr className="border-b border-line-strong">
                      <th className="label pb-1.5 pr-3 text-left font-normal">Name</th>
                      <th className="label w-[92px] pb-1.5 pr-3 text-left font-normal">Status</th>
                      <th className="label w-[84px] pb-1.5 pr-3 text-right font-normal">GPUs</th>
                      <th className="label w-[150px] pb-1.5 pr-3 text-left font-normal">Node</th>
                      <th className="label w-[112px] pb-1.5 pr-3 text-left font-normal">Policy</th>
                      <th className="label w-[52px] pb-1.5 pr-3 text-right font-normal">Age</th>
                      <th className="w-[104px]" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line-soft">
                    {workloads.map((w) => (
                      <WorkloadRow key={w.id} workload={w} tenantId={id} explain={explain} />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="py-6 text-center text-[12px] text-fg-dim">Nothing submitted yet.</p>
            )}
          </Section>

          <Section title="Endpoint replicas, last 15 minutes">
            <TimeSeries
              series={replicaSeries}
              labelKey="endpoint"
              step
              emptyMessage="No endpoints scaling in this window."
            />
          </Section>
        </div>

        <div className="space-y-7">
          <Section title="Submit work">
            <SubmitForms tenantId={id} />
          </Section>

          <Section title="Metered this period">
            {usage.workloads.length > 0 ? (
              <ul className="divide-y divide-line-soft border-y border-line-soft">
                {usage.workloads.slice(0, 10).map((w) => (
                  <li key={w.workload_id} className="flex justify-between gap-2 py-1.5">
                    <span className="num truncate text-[11.5px] text-fg-muted">
                      {w.workload_id.slice(0, 8)} {w.kind}
                    </span>
                    <span className="num shrink-0 text-[11.5px]">{money(w.cost)}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-fg-dim">Nothing metered this period.</p>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}
