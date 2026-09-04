# Kestrel operator console

Next.js dashboard for the Kestrel control plane. Two views: the cluster (GPU map,
placement policy, live charts) and per-tenant detail (quota, budget, runway,
workloads, submission, cost).

## How it talks to the platform

Every read and write happens in the Next.js **server**, never the browser:

- The **admin token** reaches admin-only surfaces — listing tenants, `/cluster/*`,
  switching the active placement policy.
- Tenant-scoped data uses a **real per-tenant API key**, minted on demand through
  `POST /admin/tenants/{id}/api-keys` and cached in the server process. The console
  could have been given a master-key bypass instead; using a genuine key means it
  exercises exactly the path a customer's own client would, and the tenant auth
  boundary stays intact rather than being special-cased for a demo.

Consequences worth knowing: the control plane needs no CORS rules, no credential is
present in any client bundle, and a dev-server restart mints one fresh key per
tenant it touches.

## Running

With the whole stack (recommended — this is what `docker compose up` brings up):

    cd ../deploy && docker compose up -d --build

Then open http://localhost:3000.

Standalone against an already-running control plane:

    cp .env.example .env.local   # adjust if your ports differ
    npm install
    npm run dev

Charts come from Prometheus (`../deploy/prometheus/prometheus.yml`); everything
else is read straight from the control-plane API. If Prometheus is down, the charts
render empty and the rest of the page still works.
