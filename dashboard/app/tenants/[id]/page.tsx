import Link from "next/link";
import { notFound } from "next/navigation";

import { AutoRefresh } from "@/components/auto-refresh";
import { SubmitForms } from "@/components/submit-forms";
import { TimeSeries } from "@/components/timeseries";
import { WorkloadRow } from "@/components/workload-row";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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

  const workloads = [...jobs, ...endpoints].sort((a, b) =>
    a.created_at < b.created_at ? 1 : -1,
  );
  const running = workloads.filter((w) => w.status === "running");
  const held = running.reduce(
    (n, w) =>
      n + (w.kind === "endpoint" ? w.gpus_requested * (w.replicas ?? 0) : w.gpus_requested),
    0,
  );

  // Runway for the tenant as a whole: read off any live workload's explain rather
  // than recomputed here, so the page can't disagree with the scheduler.
  let tenantRunway: Explain["runway"] | null = null;
  const probe = running[0] ?? workloads[0];
  if (probe) {
    try {
      tenantRunway = (await explainWorkload(id, probe.id)).runway;
    } catch {
      tenantRunway = null;
    }
  }

  const gpuPct = tenant.max_gpus > 0 ? Math.min(100, (held / tenant.max_gpus) * 100) : 0;
  const budgetUsed = Number(usage.total_gpu_seconds);
  const budgetPct =
    tenant.gpu_second_budget && tenant.gpu_second_budget > 0
      ? Math.min(100, (budgetUsed / tenant.gpu_second_budget) * 100)
      : null;

  async function explain(workloadId: string): Promise<Explain | { error: string }> {
    "use server";
    try {
      return await explainWorkload(id, workloadId);
    } catch (err) {
      return { error: err instanceof Error ? err.message : "explain failed" };
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link
            href="/tenants"
            className="text-xs text-muted-foreground underline-offset-2 hover:underline"
          >
            ← Tenants
          </Link>
          <h1 className="mt-1 font-mono text-xl font-semibold tracking-tight">{tenant.slug}</h1>
          <p className="text-sm text-muted-foreground">
            {tenant.name} · ${tenant.price_per_gpu_hour}/GPU-hour
          </p>
        </div>
        <AutoRefresh seconds={5} />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <div className="grid gap-3 sm:grid-cols-3">
            <Meter
              label="Concurrent GPUs"
              value={`${held}/${tenant.max_gpus}`}
              pct={gpuPct}
              hint="enforced at placement"
            />
            <Meter
              label="Budget"
              value={
                tenant.gpu_second_budget === null
                  ? "unlimited"
                  : `${gpuSeconds(budgetUsed)} / ${tenant.gpu_second_budget}s`
              }
              pct={budgetPct}
              hint={
                tenant.gpu_second_budget === null
                  ? "no cap configured"
                  : "blocks new submissions at 100%"
              }
            />
            <div className="rounded-lg border bg-card p-4">
              <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
                Runway
              </div>
              {tenantRunway ? (
                <>
                  <div className={`tabular mt-1 text-2xl font-semibold ${riskTone(tenantRunway.risk_tier)}`}>
                    {runway(tenantRunway.runway_seconds)}
                  </div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    tier {tenantRunway.risk_tier} · {RISK_TIER_LABEL[tenantRunway.risk_tier]} ·
                    burning {tenantRunway.burn_rate_gpus} GPU/s
                  </div>
                </>
              ) : (
                <>
                  <div className="tabular mt-1 text-2xl font-semibold text-muted-foreground">
                    —
                  </div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    submit a workload to read it
                  </div>
                </>
              )}
            </div>
          </div>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Workloads</CardTitle>
            </CardHeader>
            <CardContent className="px-0">
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Name</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>GPUs</TableHead>
                      <TableHead>Node</TableHead>
                      <TableHead>Policy</TableHead>
                      <TableHead>Age</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {workloads.map((w) => (
                      <WorkloadRow
                        key={w.id}
                        workload={w}
                        tenantId={id}
                        explain={explain}
                      />
                    ))}
                  </TableBody>
                </Table>
              </div>
              {workloads.length === 0 && (
                <p className="px-6 py-8 text-center text-sm text-muted-foreground">
                  Nothing submitted yet.
                </p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Endpoint replicas, last 15 minutes</CardTitle>
            </CardHeader>
            <CardContent>
              <TimeSeries
                series={replicaSeries}
                labelKey="endpoint"
                step
                emptyMessage="No endpoints scaling in this window."
              />
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Submit work</CardTitle>
            </CardHeader>
            <CardContent>
              <SubmitForms tenantId={id} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">This period</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-baseline justify-between">
                <span className="text-sm text-muted-foreground">Metered</span>
                <span className="tabular text-sm">{gpuSeconds(usage.total_gpu_seconds)}</span>
              </div>
              <div className="flex items-baseline justify-between border-b pb-3">
                <span className="text-sm text-muted-foreground">Cost</span>
                <span className="tabular text-lg font-semibold">
                  {money(usage.estimated_cost)}
                </span>
              </div>
              <div className="space-y-1.5">
                {usage.workloads.slice(0, 8).map((w) => (
                  <div key={w.workload_id} className="flex justify-between gap-2 text-xs">
                    <span className="truncate font-mono text-muted-foreground">
                      {w.workload_id.slice(0, 8)} · {w.kind}
                    </span>
                    <span className="tabular shrink-0">{money(w.cost)}</span>
                  </div>
                ))}
                {usage.workloads.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    Nothing metered this period.
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function Meter({
  label,
  value,
  pct,
  hint,
}: {
  label: string;
  value: string;
  pct: number | null;
  hint: string;
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      <div className="tabular mt-1 text-lg font-semibold">{value}</div>
      {pct !== null && (
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
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
      )}
      <div className="mt-1.5 text-xs text-muted-foreground">{hint}</div>
    </div>
  );
}
