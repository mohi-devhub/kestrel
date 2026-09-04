"use client";

import { useState, useTransition } from "react";

import { submitEndpointAction, submitJobAction } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "cn";

type Kind = "job" | "endpoint";

export function SubmitForms({ tenantId }: { tenantId: string }) {
  const [kind, setKind] = useState<Kind>("job");
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);

  function onSubmit(form: FormData) {
    setResult(null);
    startTransition(async () => {
      const action = kind === "job" ? submitJobAction : submitEndpointAction;
      setResult(await action(tenantId, form));
    });
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-1 rounded-md bg-muted p-1" role="tablist">
        {(["job", "endpoint"] as Kind[]).map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={kind === k}
            onClick={() => {
              setKind(k);
              setResult(null);
            }}
            className={cn(
              "flex-1 rounded px-3 py-1 text-sm capitalize transition-colors",
              "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
              kind === k
                ? "bg-background font-medium shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {k}
          </button>
        ))}
      </div>

      <form action={onSubmit} className="space-y-3" key={kind}>
        {kind === "job" ? (
          <>
            <Field name="image" label="Image" defaultValue="busybox" />
            <Field name="command" label="Command" defaultValue="sleep 60" />
            <div className="grid grid-cols-2 gap-3">
              <Field name="gpus" label="GPUs" type="number" defaultValue="1" min={0} />
              <Field name="priority" label="Priority" type="number" defaultValue="0" min={0} />
            </div>
          </>
        ) : (
          <>
            <Field name="image" label="Image" defaultValue="nginx" />
            <div className="grid grid-cols-2 gap-3">
              <Field name="gpus" label="GPUs / replica" type="number" defaultValue="1" min={0} />
              <Field name="port" label="Port" type="number" defaultValue="80" min={1} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field name="min_replicas" label="Min replicas" type="number" defaultValue="1" min={0} />
              <Field name="max_replicas" label="Max replicas" type="number" defaultValue="3" min={1} />
            </div>
            <p className="text-[11px] text-muted-foreground">
              min 0 opts into scale-to-zero: it starts cold and wakes on first reported load.
            </p>
          </>
        )}

        <Button type="submit" disabled={pending} className="w-full">
          {pending ? "Submitting…" : kind === "job" ? "Submit job" : "Provision endpoint"}
        </Button>
      </form>

      {result && (
        <p
          className={cn(
            "rounded-md border px-3 py-2 text-xs",
            result.ok
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
              : "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300",
          )}
        >
          {result.message}
        </p>
      )}
    </div>
  );
}

function Field({
  name,
  label,
  type = "text",
  defaultValue,
  min,
}: {
  name: string;
  label: string;
  type?: string;
  defaultValue: string;
  min?: number;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={name} className="text-xs">
        {label}
      </Label>
      <Input id={name} name={name} type={type} defaultValue={defaultValue} min={min} />
    </div>
  );
}
