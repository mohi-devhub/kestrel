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
      <div className="flex border-b border-line" role="tablist">
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
              "num relative px-3 py-1.5 text-[12px] capitalize",
              kind === k ? "text-fg" : "text-fg-dim hover:text-fg",
            )}
          >
            {k}
            {kind === k && (
              <span aria-hidden className="absolute inset-x-0 -bottom-px h-px bg-accent" />
            )}
          </button>
        ))}
      </div>

      <form action={onSubmit} className="space-y-2.5" key={kind}>
        {kind === "job" ? (
          <>
            <Field name="image" label="Image" defaultValue="busybox" />
            <Field name="command" label="Command" defaultValue="sleep 60" />
            <div className="grid grid-cols-2 gap-2.5">
              <Field name="gpus" label="GPUs" type="number" defaultValue="1" min={0} />
              <Field name="priority" label="Priority" type="number" defaultValue="0" min={0} />
            </div>
          </>
        ) : (
          <>
            <Field name="image" label="Image" defaultValue="nginx" />
            <div className="grid grid-cols-2 gap-2.5">
              <Field name="gpus" label="GPUs per replica" type="number" defaultValue="1" min={0} />
              <Field name="port" label="Port" type="number" defaultValue="80" min={1} />
            </div>
            <div className="grid grid-cols-2 gap-2.5">
              <Field name="min_replicas" label="Min replicas" type="number" defaultValue="1" min={0} />
              <Field name="max_replicas" label="Max replicas" type="number" defaultValue="3" min={1} />
            </div>
            <p className="text-[11px] leading-snug text-fg-dim">
              Min 0 opts into scale-to-zero: it starts cold and wakes on first reported load.
            </p>
          </>
        )}

        <button
          type="submit"
          disabled={pending}
          className="num w-full bg-accent px-3 py-1.5 text-[12px] text-accent-fg hover:opacity-90 disabled:opacity-60"
        >
          {pending ? "submitting" : kind === "job" ? "submit job" : "provision endpoint"}
        </button>
      </form>

      {result && (
        <p
          className={cn(
            "border-l-2 py-1 pl-2 text-[11.5px]",
            result.ok ? "border-ok text-ok" : "border-crit text-crit",
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
    <div className="space-y-1">
      <label htmlFor={name} className="label block">
        {label}
      </label>
      <input
        id={name}
        name={name}
        type={type}
        defaultValue={defaultValue}
        min={min}
        className="num w-full border border-input bg-bg px-2 py-1 text-[12px] text-fg placeholder:text-fg-dim focus-visible:border-accent"
      />
    </div>
  );
}
