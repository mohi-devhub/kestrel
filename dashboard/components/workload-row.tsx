"use client";

import { useState, useTransition } from "react";

import { stopWorkloadAction } from "@/app/actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { TableCell, TableRow } from "@/components/ui/table";
import type { Explain, Workload } from "@/lib/kestrel";
import { RISK_TIER_LABEL, ago, riskTone, runway, statusTone } from "@/lib/format";

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
      <TableRow>
        <TableCell className="font-mono text-xs">{workload.k8s_name}</TableCell>
        <TableCell>
          <Badge variant="outline" className={statusTone(workload.status)}>
            {workload.status}
          </Badge>
        </TableCell>
        <TableCell className="tabular text-xs">
          {held}
          {workload.kind === "endpoint" && workload.replicas !== null && (
            <span className="text-muted-foreground"> ({workload.replicas}×)</span>
          )}
        </TableCell>
        <TableCell className="font-mono text-xs text-muted-foreground">
          {workload.node_name ?? "—"}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {workload.placement_policy ?? "—"}
        </TableCell>
        <TableCell className="text-xs text-muted-foreground">
          {ago(workload.created_at)}
        </TableCell>
        <TableCell className="text-right">
          <div className="flex justify-end gap-1">
            <Button variant="ghost" size="sm" onClick={toggle} aria-expanded={open}>
              {open ? "Hide" : "Why?"}
            </Button>
            {!TERMINAL.has(workload.status) && (
              <Button
                variant="ghost"
                size="sm"
                disabled={pending}
                onClick={() =>
                  startTransition(async () => {
                    await stopWorkloadAction(tenantId, workload.id, workload.kind);
                  })
                }
              >
                Stop
              </Button>
            )}
          </div>
        </TableCell>
      </TableRow>

      {open && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={7} className="bg-muted/40 p-4">
            {loading && <p className="text-xs text-muted-foreground">Reading the decision…</p>}
            {detail && "error" in detail && (
              <p className="text-xs text-red-600 dark:text-red-400">{detail.error}</p>
            )}
            {detail && !("error" in detail) && <ExplainDetail explain={detail} />}
          </TableCell>
        </TableRow>
      )}
    </>
  );
}

/** Renders GET /workloads/{id}/explain — the same dry run the scheduler would do. */
function ExplainDetail({ explain }: { explain: Explain }) {
  const { quota, ordering, runway: r, kueue_admitted } = explain;
  return (
    <div className="grid gap-4 text-xs sm:grid-cols-3">
      <div className="space-y-1">
        <h4 className="font-medium">Admission</h4>
        <Line label="quota" value={quota.passes ? "passes" : "blocked"} tone={!quota.passes} />
        {quota.reason && <p className="text-muted-foreground">{quota.reason}</p>}
        <Line
          label="kueue"
          value={
            kueue_admitted === null ? "n/a (endpoint)" : kueue_admitted ? "admitted" : "waiting"
          }
        />
      </div>

      <div className="space-y-1">
        <h4 className="font-medium">Placement</h4>
        {ordering ? (
          <>
            <Line label="rank" value={`${ordering.rank + 1} of ${ordering.total_admitted}`} />
            <Line label="would place on" value={ordering.would_place_on ?? "—"} />
            {ordering.blocked_reason && (
              <p className="text-muted-foreground">{ordering.blocked_reason}</p>
            )}
          </>
        ) : (
          <p className="text-muted-foreground">
            Already decided — the row records the real outcome.
          </p>
        )}
      </div>

      <div className="space-y-1">
        <h4 className="font-medium">Runway</h4>
        <Line label="burn rate" value={`${r.burn_rate_gpus} GPU/s`} />
        <Line label="remaining" value={r.remaining_gpu_seconds ?? "∞"} />
        <Line label="runway" value={runway(r.runway_seconds)} />
        <div className="flex justify-between gap-2">
          <span className="text-muted-foreground">risk tier</span>
          <span className={riskTone(r.risk_tier)}>
            {r.risk_tier} · {RISK_TIER_LABEL[r.risk_tier] ?? "—"}
          </span>
        </div>
      </div>
    </div>
  );
}

function Line({ label, value, tone }: { label: string; value: string; tone?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-muted-foreground">{label}</span>
      <span className={`tabular ${tone ? "text-red-600 dark:text-red-400" : ""}`}>{value}</span>
    </div>
  );
}
