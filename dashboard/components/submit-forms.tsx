"use client";

import { useState, useTransition } from "react";

import { submitEndpointAction, submitJobAction } from "@/app/actions";
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
      <div className="flex gap-1 rounded-full bg-sunk p-1" role="tablist">
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
              "flex-1 rounded-full py-1.5 text-[12.5px] font-medium capitalize",
              kind === k ? "bg-card text-ink shadow-card" : "text-ink-3 hover:text-ink",
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
              <Field name="gpus" label="GPUs per replica" type="number" defaultValue="1" min={0} />
              <Field name="port" label="Port" type="number" defaultValue="80" min={1} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field name="min_replicas" label="Min replicas" type="number" defaultValue="1" min={0} />
              <Field name="max_replicas" label="Max replicas" type="number" defaultValue="3" min={1} />
            </div>
            <p className="text-[11.5px] leading-snug text-ink-3">
              Min 0 opts into scale-to-zero: it starts cold and wakes on first reported load.
            </p>
          </>
        )}

        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-sm bg-accent px-3 py-2.5 text-[13px] font-semibold text-accent-ink shadow-card hover:brightness-110 disabled:opacity-60"
        >
          {pending ? "Submitting" : kind === "job" ? "Submit job" : "Provision endpoint"}
        </button>
      </form>

      {result && (
        <p
          className={cn(
            "rounded-sm px-3 py-2 text-[12px] font-medium",
            result.ok ? "bg-ok-soft text-ok" : "bg-crit-soft text-crit",
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
      <label htmlFor={name} className="t-label block text-[11.5px] font-medium">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        defaultValue={defaultValue}
        min={min}
        className="t-mono w-full rounded-sm border border-line-2 bg-card px-3 py-2 text-[12.5px] text-ink transition-colors placeholder:text-ink-4 hover:border-ink-4 focus-visible:border-accent"
      />
    </div>
  );
}
