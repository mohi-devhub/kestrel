import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { GpuMap } from "@/components/gpu-map";
import { PageHead, Panel, Stat, StatRow, Status } from "@/components/shell";
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
  const recent = [...workloads].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).slice(0, 7);

  return (
    <div className="flex flex-col gap-5">
      <PageHead
        title="Cluster"
        sub="Simulated GPU fleet, from the control plane's own accounting."
        aside={<AutoRefresh seconds={5} />}
      />

      <StatRow>
        <Stat
          label="GPUs held"
          value={
            <>
              {gpuUsed}
              <span className="text-ink-4">/{gpuTotal}</span>
            </>
          }
          sub={`${nodes.length} nodes, ${gpuTotal - gpuUsed} free`}
          tone={gpuUsed > 0 ? "accent" : undefined}
        />
        <Stat label="Running" value={running.length} sub="workloads on nodes" tone="ok" />
        <Stat
          label="Queued"
          value={queued.length}
          sub="awaiting capacity"
          tone={queued.length > 0 ? "queue" : undefined}
        />
        <Stat label="Tenants" value={tenants.length} sub="with quota on this cluster" />
      </StatRow>

      {/* Charts sit directly under the stats rather than at the page foot. The
          previous layout put a short map beside a tall column and left a third
          of the viewport empty below it. */}
      <div className="grid gap-5 xl:grid-cols-3">
        <Panel
          title="GPUs in use"
          aside={
            promUp ? (
              <span className="t-mono text-[10.5px] text-ink-4">15m</span>
            ) : (
              <span className="text-[10.5px] text-ink-4">Prometheus down</span>
            )
          }
        >
          <TimeSeries series={nodeSeries} labelKey="__total" step height={132} unit=" GPU" />
        </Panel>
        <Panel title="Endpoint replicas">
          <TimeSeries
            series={replicaSeries}
            labelKey="endpoint"
            step
            height={132}
            emptyMessage="No endpoints scaling in this window."
          />
        </Panel>
        <Panel title="Queue depth">
          <TimeSeries
            series={queueSeries}
            labelKey="tenant"
            step
            height={132}
            emptyMessage="Nothing has queued in this window."
          />
        </Panel>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <Panel title="GPU map" flush>
          <GpuMap nodes={nodes} workloads={workloads} />
        </Panel>

        <div className="flex flex-col gap-5">
          <Panel title="Placement policy" bodyClassName="p-2">
            <PolicySwitcher active={policy.name} />
          </Panel>

          <Panel title="Recent" flush>
            {recent.length > 0 ? (
              <ul className="divide-y divide-hair">
                {recent.map((w) => (
                  <li key={w.id} className="flex items-center justify-between gap-2 px-4 py-2">
                    <span className="t-mono truncate text-[11.5px] text-ink-2">{w.k8s_name}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="t-mono text-[11px] text-ink-4">{ago(w.created_at)}</span>
                      <Status status={w.status} />
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-4 py-6 text-[12.5px] text-ink-4">
                Nothing submitted yet. Pick a tenant on{" "}
                <Link href="/tenants" className="text-accent underline underline-offset-2">
                  Tenants
                </Link>
                .
              </p>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
