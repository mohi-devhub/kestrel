import type { NodeUsage, Workload } from "@/lib/kestrel";
import { cn } from "cn";

/**
 * The simulated fleet, one row per node, one cell per GPU.
 *
 * A GPU is the unit the whole platform is accounted in, so the map draws actual
 * GPUs rather than a utilisation percentage — fragmentation (four free GPUs split
 * across four nodes) looks completely different from four free on one node, and
 * that difference is exactly what the placement policies exist to manage.
 */
export function GpuMap({
  nodes,
  workloads,
}: {
  nodes: NodeUsage[];
  workloads: Workload[];
}) {
  const running = workloads.filter((w) => w.status === "running" && w.node_name);

  return (
    <div className="space-y-3">
      {nodes.map((node) => {
        const here = running.filter((w) => w.node_name === node.name);
        // Each running workload paints as many cells as it actually holds, so an
        // endpoint at three replicas occupies three.
        const cells: (Workload | null)[] = [];
        for (const w of here) {
          const held =
            w.kind === "endpoint" ? w.gpus_requested * (w.replicas ?? 0) : w.gpus_requested;
          for (let i = 0; i < held; i++) cells.push(w);
        }
        while (cells.length < node.gpu_total) cells.push(null);

        return (
          <div key={node.name} className="rounded-lg border bg-card p-3">
            <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
              <span className="font-mono text-sm">{node.name}</span>
              <span className="tabular text-xs text-muted-foreground">
                {node.gpu_used}/{node.gpu_total} GPUs held
              </span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {cells.slice(0, node.gpu_total).map((w, i) => (
                <div
                  key={i}
                  title={w ? `${w.k8s_name} · ${w.kind}` : "free"}
                  className={cn(
                    "flex h-11 w-24 flex-col justify-center rounded-md border px-2",
                    w
                      ? w.kind === "endpoint"
                        ? "border-violet-500/40 bg-violet-500/12"
                        : "border-sky-500/40 bg-sky-500/12"
                      : "border-dashed border-border bg-muted/40",
                  )}
                >
                  {w ? (
                    <>
                      <span className="truncate font-mono text-[10.5px] leading-tight">
                        {w.k8s_name.replace(/^(job|endpoint)-/, "")}
                      </span>
                      <span className="text-[10px] leading-tight text-muted-foreground">
                        {w.kind}
                      </span>
                    </>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">free</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
      {nodes.length === 0 && (
        <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
          No GPU nodes reported. Is the kind cluster up?
        </p>
      )}
    </div>
  );
}
