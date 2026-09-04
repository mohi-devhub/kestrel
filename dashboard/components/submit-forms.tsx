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
      <div className="flex gap-1 rounded-sm border border-hair bg-s2 p-1" role="tablist">
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
              "t-mono flex-1 rounded-[4px] py-1 text-[12px] capitalize",
              kind === k ? "bg-s1 text-ink" : "text-ink-4 hover:text-ink-2",
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
            <p className="text-[11px] leading-snug text-ink-4">
              Min 0 opts into scale-to-zero: it starts cold and wakes on first reported load.
            </p>
          </>
        )}

        <button
          type="submit"
          disabled={pending}
          className="w-full rounded-sm bg-accent px-3 py-2 text-[12.5px] font-medium text-accent-ink hover:brightness-110 disabled:opacity-60"
        >
          {pending ? "Submitting" : kind === "job" ? "Submit job" : "Provision endpoint"}
        </button>
      </form>

      {result && (
        <p
          className={cn(
            "rounded-sm px-2.5 py-1.5 text-[11.5px]",
            result.ok ? "bg-ok-weak text-ok" : "bg-crit-weak text-crit",
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
      <label htmlFor={name} className="t-label block">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        defaultValue={defaultValue}
        min={min}
        className="t-mono w-full rounded-sm border border-hair-2 bg-s2 px-2.5 py-1.5 text-[12px] text-ink transition-colors placeholder:text-ink-4 hover:border-hair-3 focus-visible:border-accent"
      />
    </div>
  );
}
