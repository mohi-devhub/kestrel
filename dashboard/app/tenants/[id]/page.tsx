import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, Activity, PlusCircle, Receipt, Table2 } from "lucide-react";

import { AutoRefresh } from "@/components/auto-refresh";
import { Bar, Card, Stat } from "@/components/shell";
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
import { RISK_TIER_LABEL, gpuSeconds, money, runway } from "@/lib/format";

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
  const runwayTone = (["ok", "ink", "warn", "crit"] as const)[tenantRunway?.risk_tier ?? 0];

  async function explain(workloadId: string): Promise<Explain | { error: string }> {
    "use server";
    try {
      return await explainWorkload(id, workloadId);
    } catch (err) {
      return { error: err instanceof Error ? err.message : "explain failed" };
    }
  }

  return (
    <div>
      <div className="relative mb-8 text-center">
        <Link
          href="/tenants"
          className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-line bg-card px-3 py-1 text-[12.5px] font-medium text-ink-2 shadow-card hover:border-line-2 hover:text-ink"
        >
          <ArrowLeft size={13} strokeWidth={2} />
          Tenants
        </Link>
        <h1 className="t-h1 text-[38px] text-ink">{tenant.name}</h1>
        <p className="mt-2 text-[14.5px] text-ink-3">
          <span className="t-mono text-ink-2">{tenant.slug}</span> · $
          {tenant.price_per_gpu_hour} per GPU-hour
        </p>
        <div className="mt-4 flex justify-center sm:absolute sm:right-0 sm:top-1 sm:mt-0">
          <AutoRefresh seconds={5} />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="Concurrent GPUs"
          value={held}
          denom={tenant.max_gpus}
          tone={held > 0 ? "accent" : "ink"}
          sub={<Bar used={held} total={tenant.max_gpus} className="mt-1.5" />}
        />
        <Stat
          label="Budget used"
          value={tenant.gpu_second_budget === null ? "None" : budgetUsed.toFixed(0)}
          denom={tenant.gpu_second_budget ?? undefined}
          sub={
            tenant.gpu_second_budget === null ? (
              "no cap configured"
            ) : (
              <Bar used={budgetUsed} total={tenant.gpu_second_budget} className="mt-1.5" />
            )
          }
        />
        <Stat
          label="Runway"
          value={tenantRunway ? runway(tenantRunway.runway_seconds) : "-"}
          tone={tenantRunway ? runwayTone : "ink"}
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
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_330px]">
        <div className="flex flex-col gap-4">
          <Card title="Workloads" icon={Table2} flush>
            {workloads.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[860px] border-collapse">
                  <thead>
                    <tr className="border-y border-line bg-sunk/60">
                      <Th className="pl-5 text-left">Name</Th>
                      <Th className="w-[110px] text-left">Status</Th>
                      <Th className="w-[92px] text-right">GPUs</Th>
                      <Th className="w-[160px] text-left">Node</Th>
                      <Th className="w-[116px] text-left">Policy</Th>
                      <Th className="w-[60px] text-right">Age</Th>
                      <th className="w-[116px] pr-5" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {workloads.map((w) => (
                      <WorkloadRow key={w.id} workload={w} tenantId={id} explain={explain} />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="px-5 pb-6 text-center text-[13px] text-ink-3">
                Nothing submitted yet.
              </p>
            )}
          </Card>

          <Card
            title="Endpoint replicas"
            icon={Activity}
            aside={<span className="text-[11.5px] text-ink-4">15m</span>}
          >
            <TimeSeries
              series={replicaSeries}
              labelKey="endpoint"
              step
              height={150}
              emptyMessage="No endpoints scaling in this window."
            />
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          <Card title="Submit work" icon={PlusCircle}>
            <SubmitForms tenantId={id} />
          </Card>

          <Card title="Metered this period" icon={Receipt} flush>
            {usage.workloads.length > 0 ? (
              <ul className="divide-y divide-line">
                {usage.workloads.slice(0, 8).map((w) => (
                  <li key={w.workload_id} className="flex justify-between gap-2 px-5 py-2.5">
                    <span className="t-mono truncate text-[12px] text-ink-3">
                      {w.workload_id.slice(0, 8)} {w.kind}
                    </span>
                    <span className="shrink-0 text-[12.5px] font-medium text-ink">
                      {money(w.cost)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-5 pb-5 text-[13px] text-ink-3">Nothing metered this period.</p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function Th({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <th className={`t-label py-2.5 pr-3 text-[11px] font-medium uppercase tracking-wide ${className}`}>
      {children}
    </th>
  );
}
