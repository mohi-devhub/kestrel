"use client";

import { useState, useTransition } from "react";

import { stopWorkloadAction } from "@/app/actions";
import { Status } from "@/components/panel";
import type { Explain, Workload } from "@/lib/kestrel";
import { RISK_TIER_LABEL, ago, riskTone, runway } from "@/lib/format";
import { cn } from "cn";

const TERMINAL = new Set(["succeeded", "failed", "stopped"]);

export function WorkloadRow({
  workload,
  tenantId,
  explain,
}: {
  workload: Workload;
  tenantId: string;
  explain: (workloadId: string) => Promise<Explain | { error: string }>;
}) {
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Explain | { error: string } | null>(null);
  const [loading, setLoading] = useState(false);

  const held =
    workload.kind === "endpoint"
      ? workload.gpus_requested * (workload.replicas ?? 0)
      : workload.gpus_requested;

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next && !detail) {
      setLoading(true);
      setDetail(await explain(workload.id));
      setLoading(false);
    }
  }

  return (
    <>
      <tr className={cn("hover:bg-bg-sunk", open && "bg-bg-sunk")}>
        <td className="num py-1.5 pr-3 text-[12px]">{workload.k8s_name}</td>
        <td className="py-1.5 pr-3">
          <Status status={workload.status} />
        </td>
        <td className="num py-1.5 pr-3 text-right text-[12px]">
          {held}
          {workload.kind === "endpoint" && workload.replicas !== null && (
            <span className="text-fg-dim"> {workload.replicas}x</span>
          )}
        </td>
        <td className="num py-1.5 pr-3 text-[12px] text-fg-muted">
          {workload.node_name ?? "-"}
        </td>
        <td className="num py-1.5 pr-3 text-[11.5px] text-fg-dim">
          {workload.placement_policy ?? "-"}
        </td>
        <td className="num py-1.5 text-right text-[11.5px] text-fg-dim">
          {ago(workload.created_at)}
        </td>
        <td className="py-1.5 text-right">
          <div className="flex justify-end gap-3 pl-2">
            <button
              type="button"
              onClick={toggle}
              aria-expanded={open}
              className="text-[11.5px] text-fg-muted hover:text-accent"
            >
              {open ? "hide" : "why"}
            </button>
            {!TERMINAL.has(workload.status) && (
              <button
                type="button"
                disabled={pending}
                onClick={() =>
                  startTransition(async () => {
                    await stopWorkloadAction(tenantId, workload.id, workload.kind);
                  })
                }
                className="text-[11.5px] text-fg-muted hover:text-crit disabled:opacity-50"
              >
                stop
              </button>
            )}
          </div>
        </td>
      </tr>

      {open && (
        <tr className="bg-bg-sunk">
          <td colSpan={7} className="px-0 pb-4 pt-1">
            {loading && <p className="text-[11.5px] text-fg-dim">Reading the decision.</p>}
            {detail && "error" in detail && (
              <p className="text-[11.5px] text-crit">{detail.error}</p>
            )}
            {detail && !("error" in detail) && <ExplainDetail explain={detail} />}
          </td>
        </tr>
      )}
    </>
  );
}

/** GET /workloads/{id}/explain, which is the same dry run the scheduler performs. */
function ExplainDetail({ explain }: { explain: Explain }) {
  const { quota, ordering, runway: r, kueue_admitted } = explain;
  return (
    <div className="grid gap-x-8 gap-y-4 border-l-2 border-accent pl-4 sm:grid-cols-3">
      <Group title="Admission">
        <Line label="quota" value={quota.passes ? "passes" : "blocked"} tone={!quota.passes} />
        <Line
          label="kueue"
          value={
            kueue_admitted === null
              ? "n/a, endpoint"
              : kueue_admitted
                ? "admitted"
                : "waiting"
          }
        />
        {quota.reason && <p className="pt-1 text-[11px] text-fg-dim">{quota.reason}</p>}
      </Group>

      <Group title="Placement">
        {ordering ? (
          <>
            <Line label="rank" value={`${ordering.rank + 1} of ${ordering.total_admitted}`} />
            <Line label="would place on" value={ordering.would_place_on ?? "-"} />
            {ordering.blocked_reason && (
              <p className="pt-1 text-[11px] text-fg-dim">{ordering.blocked_reason}</p>
            )}
          </>
        ) : (
          <p className="text-[11px] text-fg-dim">
            Already decided. The row records the real outcome.
          </p>
        )}
      </Group>

      <Group title="Runway">
        <Line label="burn rate" value={`${r.burn_rate_gpus} GPU/s`} />
        <Line label="remaining" value={r.remaining_gpu_seconds ?? "∞"} />
        <Line label="runway" value={runway(r.runway_seconds)} />
        <div className="flex justify-between gap-2">
          <span className="text-[11.5px] text-fg-dim">risk tier</span>
          <span className={cn("num text-[11.5px]", riskTone(r.risk_tier))}>
            {r.risk_tier} {RISK_TIER_LABEL[r.risk_tier]}
          </span>
        </div>
      </Group>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="label mb-1.5">{title}</div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function Line({ label, value, tone }: { label: string; value: string; tone?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-[11.5px] text-fg-dim">{label}</span>
      <span className={cn("num text-[11.5px]", tone ? "text-crit" : "text-fg")}>{value}</span>
    </div>
  );
}
