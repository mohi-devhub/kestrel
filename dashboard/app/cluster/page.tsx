import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { GpuMap } from "@/components/gpu-map";
import { PolicySwitcher } from "@/components/policy-switcher";
import { TimeSeries } from "@/components/timeseries";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { activePolicy, clusterNodes, clusterWorkloads, listTenants } from "@/lib/kestrel";
import { isPrometheusUp, queryRange } from "@/lib/prom";
import { ago, statusTone } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function ClusterPage() {
  const [allNodes, workloads, policy, tenants, promUp] = await Promise.all([
    clusterNodes(),
    clusterWorkloads(),
    activePolicy(),
    listTenants(),
    isPrometheusUp(),
  ]);

  // The same view of "the cluster" the scheduler and the collector take: a ready
  // node with GPU capacity. The kind control-plane node has none.
  const nodes = allNodes.filter((n) => n.ready && n.gpu_total > 0);

  const [replicaSeries, queueSeries, nodeSeries] = await Promise.all([
    queryRange("kestrel_autoscale_replicas"),
    // Only tenants that actually queued something in the window. Without the
    // filter every tenant contributes a flat-zero line and the legend buries the
    // chart it belongs to.
    queryRange("sum by (tenant) (kestrel_queue_depth) > 0"),
    queryRange("kestrel_node_gpu_used"),
  ]);

  const gpuTotal = nodes.reduce((n, x) => n + x.gpu_total, 0);
  const gpuUsed = nodes.reduce((n, x) => n + x.gpu_used, 0);
  const queued = workloads.filter((w) => w.status === "queued" || w.status === "admitted");
  const running = workloads.filter((w) => w.status === "running");
  const recent = [...workloads]
    .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
    .slice(0, 8);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Cluster</h1>
          <p className="text-sm text-muted-foreground">
            Simulated GPU fleet, live from the control plane&rsquo;s own accounting.
          </p>
        </div>
        <AutoRefresh seconds={5} />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="GPUs held" value={`${gpuUsed}/${gpuTotal}`} hint={`${nodes.length} nodes`} />
        <Stat label="Running" value={String(running.length)} hint="workloads on nodes" />
        <Stat
          label="Queued"
          value={String(queued.length)}
          hint="submitted, awaiting capacity"
          tone={queued.length > 0 ? "warn" : undefined}
        />
        <Stat label="Tenants" value={String(tenants.length)} hint="with quota on this cluster" />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">GPU map</CardTitle>
          </CardHeader>
          <CardContent>
            <GpuMap nodes={nodes} workloads={workloads} />
          </CardContent>
        </Card>

        <div className="space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Placement policy</CardTitle>
            </CardHeader>
            <CardContent>
              <PolicySwitcher active={policy.name} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Recent workloads</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {recent.map((w) => (
                <div key={w.id} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate font-mono text-xs">{w.k8s_name}</span>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="text-[11px] text-muted-foreground">
                      {ago(w.created_at)}
                    </span>
                    <Badge variant="outline" className={statusTone(w.status)}>
                      {w.status}
                    </Badge>
                  </div>
                </div>
              ))}
              {recent.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  Nothing submitted yet. Pick a tenant on{" "}
                  <Link href="/tenants" className="underline underline-offset-2">
                    Tenants
                  </Link>{" "}
                  to submit work.
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 pb-3">
          <CardTitle className="text-base">Last 15 minutes</CardTitle>
          {!promUp && (
            <span className="text-xs text-muted-foreground">
              Prometheus unreachable — charts stay empty
            </span>
          )}
        </CardHeader>
        <CardContent className="grid gap-6 lg:grid-cols-3">
          <ChartPanel title="Endpoint replicas" caption="Autoscaler decisions, per endpoint">
            <TimeSeries series={replicaSeries} labelKey="endpoint" step />
          </ChartPanel>
          <ChartPanel title="Queue depth" caption="Submitted but not yet running, per tenant">
            <TimeSeries
              series={queueSeries}
              labelKey="tenant"
              step
              emptyMessage="Nothing has queued in this window."
            />
          </ChartPanel>
          <ChartPanel title="GPUs in use" caption="Per node, control-plane accounting">
            <TimeSeries series={nodeSeries} labelKey="node" step />
          </ChartPanel>
        </CardContent>
      </Card>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  tone?: "warn";
}) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </div>
      <div
        className={`tabular mt-1 text-2xl font-semibold ${
          tone === "warn" ? "text-amber-600 dark:text-amber-400" : ""
        }`}
      >
        {value}
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">{hint}</div>
    </div>
  );
}

function ChartPanel({
  title,
  caption,
  children,
}: {
  title: string;
  caption: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-sm font-medium">{title}</div>
      <div className="mb-2 text-xs text-muted-foreground">{caption}</div>
      {children}
    </div>
  );
}
