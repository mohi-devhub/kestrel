import type { NodeUsage, Workload } from "@/lib/kestrel";
import { cn } from "cn";

/**
 * The fleet, one row per node, one block per GPU.
 *
 * Drawn as discrete GPU blocks rather than a utilisation percentage because
 * fragmentation is the thing the placement policies exist to manage, and four
 * free GPUs spread across four nodes looks nothing like four free on one node.
 * A percentage hides exactly that difference.
 *
 * Held blocks carry the accent; free blocks are a hairline outline, so the
 * amount of ink on screen is the amount of the cluster in use.
 */
export function GpuMap({ nodes, workloads }: { nodes: NodeUsage[]; workloads: Workload[] }) {
  const running = workloads.filter((w) => w.status === "running" && w.node_name);

  if (nodes.length === 0) {
    return (
      <p className="border border-dashed border-line px-4 py-8 text-center text-sm text-fg-dim">
        No GPU nodes reported. Is the kind cluster up?
      </p>
    );
  }

  return (
    <div className="divide-y divide-line-soft border-y border-line-soft">
      {nodes.map((node) => {
        const here = running.filter((w) => w.node_name === node.name);
        const blocks: (Workload | null)[] = [];
        for (const w of here) {
          const held =
            w.kind === "endpoint" ? w.gpus_requested * (w.replicas ?? 0) : w.gpus_requested;
          for (let i = 0; i < held; i++) blocks.push(w);
        }
        while (blocks.length < node.gpu_total) blocks.push(null);

        return (
          <div
            key={node.name}
            className="grid grid-cols-[minmax(0,1fr)] gap-2 py-2.5 sm:grid-cols-[190px_minmax(0,1fr)] sm:items-center sm:gap-4"
          >
            <div className="flex items-baseline gap-2">
              <span className="num truncate text-[13px] text-fg">{node.name}</span>
              <span className="num text-[11px] text-fg-dim">
                {node.gpu_used}/{node.gpu_total}
              </span>
            </div>

            <div className="flex flex-wrap gap-1">
              {blocks.slice(0, node.gpu_total).map((w, i) => (
                <div
                  key={i}
                  title={w ? `${w.k8s_name} (${w.kind})` : "free"}
                  className={cn(
                    "flex h-8 min-w-[86px] flex-1 items-center px-2 sm:max-w-[132px]",
                    w
                      ? "border border-accent-line bg-accent-weak"
                      : "border border-dashed border-line",
                  )}
                >
                  {w ? (
                    <span className="num truncate text-[11px] leading-none text-fg">
                      {w.k8s_name.replace(/^(job|endpoint)-/, "")}
                      <span className="text-fg-dim">{w.kind === "endpoint" ? " ep" : " job"}</span>
                    </span>
                  ) : (
                    <span className="num text-[11px] leading-none text-fg-dim">free</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
