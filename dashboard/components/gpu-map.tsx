import type { NodeUsage, Workload } from "@/lib/kestrel";
import { cn } from "cn";

/**
 * The fleet: one row per node, one cell per GPU.
 *
 * Discrete cells rather than a utilisation percentage, because fragmentation is
 * what the placement policies exist to manage and four free GPUs spread across
 * four nodes looks nothing like four free on one node. Held cells carry colour,
 * free cells stay empty, so the amount of colour on screen is the amount of the
 * cluster in use.
 */
export function GpuMap({ nodes, workloads }: { nodes: NodeUsage[]; workloads: Workload[] }) {
  const running = workloads.filter((w) => w.status === "running" && w.node_name);

  if (nodes.length === 0) {
    return (
      <p className="px-5 py-12 text-center text-[13px] text-ink-3">
        No GPU nodes reported. Is the kind cluster up?
      </p>
    );
  }

  return (
    <div className="divide-y divide-line">
      {nodes.map((node) => {
        const here = running.filter((w) => w.node_name === node.name);
        const cells: (Workload | null)[] = [];
        for (const w of here) {
          const held =
            w.kind === "endpoint" ? w.gpus_requested * (w.replicas ?? 0) : w.gpus_requested;
          for (let i = 0; i < held; i++) cells.push(w);
        }
        while (cells.length < node.gpu_total) cells.push(null);
        const pct = node.gpu_total ? (node.gpu_used / node.gpu_total) * 100 : 0;

        return (
          <div key={node.name} className="px-5 py-4">
            <div className="mb-2.5 flex items-center gap-2.5">
              <span className="t-mono text-[13px] text-ink">{node.name}</span>
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[11.5px] font-medium",
                  pct >= 100
                    ? "bg-accent-soft text-accent"
                    : node.gpu_used > 0
                      ? "bg-sunk text-ink-2"
                      : "bg-idle-soft text-ink-4",
                )}
              >
                {node.gpu_used}/{node.gpu_total} held
              </span>
            </div>

            {/* One column per GPU so cells fill the row and stay aligned between
                nodes, which is what makes the map scannable down a column. */}
            <div
              className="grid gap-2"
              style={{ gridTemplateColumns: `repeat(${node.gpu_total}, minmax(0, 1fr))` }}
            >
              {cells.slice(0, node.gpu_total).map((w, i) => (
                <div
                  key={i}
                  title={w ? `${w.k8s_name} (${w.kind})` : "free"}
                  className={cn(
                    "flex h-[52px] flex-col justify-center overflow-hidden rounded-sm px-3",
                    w
                      ? "border border-accent-line bg-accent-soft"
                      : "border border-dashed border-line-2 bg-sunk/50",
                  )}
                >
                  {w ? (
                    <>
                      <span className="t-mono truncate text-[11.5px] leading-tight text-ink">
                        {w.k8s_name.replace(/^(job|endpoint)-/, "")}
                      </span>
                      <span className="text-[11px] leading-tight text-accent">
                        {w.kind === "endpoint" ? "endpoint" : "job"}
                      </span>
                    </>
                  ) : (
                    <span className="text-[11.5px] leading-tight text-ink-4">free</span>
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
