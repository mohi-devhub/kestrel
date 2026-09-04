import Link from "next/link";

import { AutoRefresh } from "@/components/auto-refresh";
import { GpuMap } from "@/components/gpu-map";
import { Reading, ReadingRow, Section, Status } from "@/components/panel";
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
  const recent = [...workloads].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).slice(0, 6);

  return (
    <div className="space-y-7">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-[15px] font-semibold tracking-tight">Cluster</h1>
          <p className="text-[12px] text-fg-dim">
            Simulated GPU fleet, from the control plane&rsquo;s own accounting.
          </p>
        </div>
        <AutoRefresh seconds={5} />
      </div>

      <ReadingRow>
        <Reading
          label="GPUs held"
          value={
            <>
              {gpuUsed}
              <span className="text-fg-dim">/{gpuTotal}</span>
            </>
          }
          sub={`across ${nodes.length} nodes`}
        />
        <Reading label="Running" value={running.length} sub="workloads on nodes" />
        <Reading
          label="Queued"
          value={queued.length}
          sub="awaiting capacity"
          tone={queued.length > 0 ? "warn" : undefined}
        />
        <Reading label="Tenants" value={tenants.length} sub="with quota here" />
      </ReadingRow>

      <div className="grid gap-7 lg:grid-cols-[minmax(0,1fr)_268px]">
        <Section title="GPU map">
          <GpuMap nodes={nodes} workloads={workloads} />
        </Section>

        <div className="space-y-7">
          <Section title="Placement policy">
            <PolicySwitcher active={policy.name} />
          </Section>

          <Section title="Recent">
            {recent.length > 0 ? (
              <ul className="divide-y divide-line-soft border-y border-line-soft">
                {recent.map((w) => (
                  <li key={w.id} className="flex items-center justify-between gap-2 py-1.5">
                    <span className="num truncate text-[11.5px]">{w.k8s_name}</span>
                    <span className="flex shrink-0 items-center gap-2">
                      <span className="num text-[11px] text-fg-dim">{ago(w.created_at)}</span>
                      <Status status={w.status} />
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-fg-dim">
                Nothing submitted yet. Pick a tenant on{" "}
                <Link href="/tenants" className="text-accent underline underline-offset-2">
                  Tenants
                </Link>{" "}
                to submit work.
              </p>
            )}
          </Section>
        </div>
      </div>

      <Section
        title="Last 15 minutes"
        aside={
          promUp ? undefined : (
            <span className="text-[11px] text-fg-dim">Prometheus unreachable</span>
          )
        }
      >
        <div className="grid gap-6 lg:grid-cols-3">
          <Chart title="Endpoint replicas" caption="Autoscaler decisions, per endpoint">
            <TimeSeries series={replicaSeries} labelKey="endpoint" step />
          </Chart>
          <Chart title="Queue depth" caption="Submitted but not running, per tenant">
            <TimeSeries
              series={queueSeries}
              labelKey="tenant"
              step
              emptyMessage="Nothing has queued in this window."
            />
          </Chart>
          <Chart title="GPUs in use" caption="Per node, control-plane accounting">
            <TimeSeries series={nodeSeries} labelKey="node" step />
          </Chart>
        </div>
      </Section>
    </div>
  );
}

function Chart({
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
      <div className="text-[12.5px] text-fg">{title}</div>
      <div className="mb-2 text-[11px] text-fg-dim">{caption}</div>
      {children}
    </div>
  );
}
