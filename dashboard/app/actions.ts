"use server";

/**
 * Server actions are the dashboard's whole write path.
 *
 * Using actions rather than client-side fetches means the admin token and the
 * minted tenant keys stay in the Next.js process: the browser posts a form to its
 * own origin, and the credentialed call to the control plane happens server-side.
 * That also means no CORS configuration on the control plane, which would
 * otherwise have to allow a browser origin just for this.
 */

import { revalidatePath } from "next/cache";

import {
  KestrelError,
  cancelJob,
  setPolicy,
  submitEndpoint,
  submitJob,
  teardownEndpoint,
} from "@/lib/kestrel";

export type ActionResult = { ok: true; message: string } | { ok: false; message: string };

function failed(err: unknown): ActionResult {
  if (err instanceof KestrelError) {
    // A 429 here is the quota enforcer talking, so surface its reason verbatim
    // rather than a generic failure, because that reason is the interesting part.
    return { ok: false, message: err.detail };
  }
  return { ok: false, message: err instanceof Error ? err.message : "request failed" };
}

export async function submitJobAction(
  tenantId: string,
  form: FormData,
): Promise<ActionResult> {
  const image = String(form.get("image") ?? "").trim();
  const commandRaw = String(form.get("command") ?? "").trim();
  const gpus = Number(form.get("gpus") ?? 1);
  const priority = Number(form.get("priority") ?? 0);

  if (!image) return { ok: false, message: "An image is required." };
  const command = commandRaw ? commandRaw.split(/\s+/) : ["sleep", "30"];

  try {
    const job = await submitJob(tenantId, { image, command, gpus, priority });
    revalidatePath("/tenants/[id]", "page");
    return { ok: true, message: `Submitted ${job.k8s_name}.` };
  } catch (err) {
    return failed(err);
  }
}

export async function submitEndpointAction(
  tenantId: string,
  form: FormData,
): Promise<ActionResult> {
  const image = String(form.get("image") ?? "").trim();
  const gpus = Number(form.get("gpus") ?? 1);
  const min_replicas = Number(form.get("min_replicas") ?? 1);
  const max_replicas = Number(form.get("max_replicas") ?? 3);
  const port = Number(form.get("port") ?? 80);

  if (!image) return { ok: false, message: "An image is required." };
  if (max_replicas < min_replicas) {
    return { ok: false, message: "max_replicas must be at least min_replicas." };
  }

  try {
    const endpoint = await submitEndpoint(tenantId, {
      image,
      gpus,
      min_replicas,
      max_replicas,
      port,
    });
    revalidatePath("/tenants/[id]", "page");
    return { ok: true, message: `Provisioned ${endpoint.k8s_name}.` };
  } catch (err) {
    return failed(err);
  }
}

export async function stopWorkloadAction(
  tenantId: string,
  workloadId: string,
  kind: "job" | "endpoint",
): Promise<ActionResult> {
  try {
    if (kind === "job") await cancelJob(tenantId, workloadId);
    else await teardownEndpoint(tenantId, workloadId);
    revalidatePath("/tenants/[id]", "page");
    return { ok: true, message: "Stopped." };
  } catch (err) {
    return failed(err);
  }
}

export async function setPolicyAction(name: string): Promise<ActionResult> {
  try {
    const active = await setPolicy(name);
    revalidatePath("/cluster");
    return { ok: true, message: `Placement policy is now ${active.name}.` };
  } catch (err) {
    return failed(err);
  }
}
