import type { NodeUsage, Workload } from "@/lib/kestrel";
import { cn } from "cn";

/**
 * The fleet: one row per node, one cell per GPU.
 *
 * Discrete cells rather than a utilisation percentage, because fragmentation is
 * what the placement policies exist to manage and four free GPUs spread across
 * four nodes looks nothing like four free on one node. A percentage hides
 * exactly that. Held cells carry the accent, so the ink on screen is the amount
 * of cluster in use.
 */
export function GpuMap({ nodes, workloads }: { nodes: NodeUsage[]; workloads: Workload[] }) {
  const running = workloads.filter((w) => w.status === "running" && w.node_name);

  if (nodes.length === 0) {
    return (
      <p className="px-4 py-10 text-center text-[12.5px] text-ink-4">
        No GPU nodes reported. Is the kind cluster up?
      </p>
    );
  }

  return (
    <div className="divide-y divide-hair">
      {nodes.map((node) => {
        const here = running.filter((w) => w.node_name === node.name);
        const cells: (Workload | null)[] = [];
        for (const w of here) {
          const held =
            w.kind === "endpoint" ? w.gpus_requested * (w.replicas ?? 0) : w.gpus_requested;
          for (let i = 0; i < held; i++) cells.push(w);
        }
        while (cells.length < node.gpu_total) cells.push(null);
        const full = node.gpu_used >= node.gpu_total && node.gpu_total > 0;

        return (
          <div key={node.name} className="px-4 py-3.5">
            <div className="mb-2 flex items-baseline gap-2">
              <span className="t-mono text-[12.5px] text-ink-2">{node.name}</span>
              <span
                className={cn(
                  "t-mono text-[11.5px]",
                  full ? "text-accent" : node.gpu_used > 0 ? "text-ink-3" : "text-ink-4",
                )}
              >
                {node.gpu_used}/{node.gpu_total}
              </span>
            </div>

            {/* One column per GPU so cells fill the row and stay aligned between
                nodes, which is what makes the map scannable down a column. */}
            <div
              className="grid gap-1.5"
              style={{ gridTemplateColumns: `repeat(${node.gpu_total}, minmax(0, 1fr))` }}
            >
              {cells.slice(0, node.gpu_total).map((w, i) => (
                <div
                  key={i}
                  title={w ? `${w.k8s_name} (${w.kind})` : "free"}
                  className={cn(
                    "flex h-11 flex-col justify-center overflow-hidden rounded-sm px-2.5",
                    w
                      ? "border border-accent-line bg-accent-weak"
                      : "border border-dashed border-hair-2 bg-s2",
                  )}
                >
                  {w ? (
                    <>
                      <span className="t-mono truncate text-[11px] leading-tight text-ink">
                        {w.k8s_name.replace(/^(job|endpoint)-/, "")}
                      </span>
                      <span className="text-[10px] leading-tight text-ink-4">
                        {w.kind === "endpoint" ? "endpoint" : "job"}
                      </span>
                    </>
                  ) : (
                    <span className="t-mono text-[11px] leading-tight text-ink-4">free</span>
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
