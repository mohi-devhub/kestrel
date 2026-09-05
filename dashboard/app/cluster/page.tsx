import Link from "next/link";
import { Activity, Cpu, Layers, ListChecks, SlidersHorizontal } from "lucide-react";

import { AutoRefresh } from "@/components/auto-refresh";
import { GpuMap } from "@/components/gpu-map";
import { Card, PageHead, Stat, Status } from "@/components/shell";
import { PolicySwitcher } from "@/components/policy-switcher";
import { TimeSeries } from "@/components/timeseries";
import { activePolicy, clusterNodes, clusterWorkloads, listTenants } from "@/lib/kestrel";
import { isPrometheusUp, queryRange } from "@/lib/prom";
import { ago } from "@/lib/format";

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
    // Only tenants that actually queued in the window; otherwise every tenant
    // contributes a flat-zero line and the legend buries its own chart.
    queryRange("sum by (tenant) (kestrel_queue_depth) > 0"),
    queryRange("sum(kestrel_node_gpu_used)"),
  ]);

  const gpuTotal = nodes.reduce((n, x) => n + x.gpu_total, 0);
  const gpuUsed = nodes.reduce((n, x) => n + x.gpu_used, 0);
  const queued = workloads.filter((w) => w.status === "queued" || w.status === "admitted");
  const running = workloads.filter((w) => w.status === "running");
  const recent = [...workloads].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).slice(0, 6);

  return (
    <div>
      <PageHead
        title="Cluster"
        sub="Simulated GPU fleet, live from the control plane's own accounting."
        aside={<AutoRefresh seconds={5} />}
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="GPUs held"
          value={gpuUsed}
          denom={gpuTotal}
          tone={gpuUsed > 0 ? "accent" : "ink"}
          sub={`${gpuTotal - gpuUsed} free across ${nodes.length} nodes`}
        />
        <Stat
          label="Running"
          value={running.length}
          tone={running.length > 0 ? "ok" : "ink"}
          sub="workloads placed on nodes"
        />
        <Stat
          label="Queued"
          value={queued.length}
          tone={queued.length > 0 ? "warn" : "ink"}
          sub="admitted, awaiting capacity"
        />
        <Stat label="Tenants" value={tenants.length} sub="with quota on this cluster" />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card
          title="GPUs in use"
          icon={Cpu}
          aside={
            <span className="text-[11.5px] text-ink-4">{promUp ? "15m" : "no Prometheus"}</span>
          }
        >
          <TimeSeries series={nodeSeries} labelKey="__total" step height={130} unit=" GPU" />
        </Card>
        <Card title="Endpoint replicas" icon={Activity}>
          <TimeSeries
            series={replicaSeries}
            labelKey="endpoint"
            step
            height={130}
            emptyMessage="No endpoints scaling in this window."
          />
        </Card>
        <Card title="Queue depth" icon={Layers}>
          <TimeSeries
            series={queueSeries}
            labelKey="tenant"
            step
            height={130}
            emptyMessage="Nothing has queued in this window."
          />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
        <Card title="GPU map" icon={Cpu} flush>
          <GpuMap nodes={nodes} workloads={workloads} />
        </Card>

        <div className="flex flex-col gap-4">
          <Card title="Placement policy" icon={SlidersHorizontal}>
            <PolicySwitcher active={policy.name} />
          </Card>

          <Card title="Recent" icon={ListChecks} flush>
            {recent.length > 0 ? (
              <ul className="divide-y divide-line">
                {recent.map((w) => (
                  <li key={w.id} className="flex items-center justify-between gap-2 px-5 py-2.5">
                    <span className="t-mono truncate text-[12px] text-ink-2">{w.k8s_name}</span>
                    <span className="flex shrink-0 items-center gap-2.5">
                      <span className="text-[11.5px] text-ink-4">{ago(w.created_at)}</span>
                      <Status status={w.status} />
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-5 pb-5 text-[13px] text-ink-3">
                Nothing submitted yet. Pick a tenant on{" "}
                <Link href="/tenants" className="font-medium text-accent hover:underline">
                  Tenants
                </Link>
                .
              </p>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
