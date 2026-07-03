# Fello — WhatsApp Gateway & Backend Integration Work Log

Summary of the work done to build and deploy the real WhatsApp integration:
QR-code number pairing (per-project *and* org-wide), a backend proxy service
that is the sole trust boundary in front of the Baileys gateway, the
message-ingestion → Cloud SQL → AI-routing pipeline, and the actual GCE/Cloud
SQL deployment. Written so a future session can read this file and pick up
context without re-deriving it from the diffs.

---

## 1. Architecture at a glance

```
Browser (dashboard)
   │  Firebase ID token only — never a secret
   ▼
Next.js API routes (app/api/whatsapp/*)         [fello-frontend]
   │  forwards Authorization header, adds nothing secret
   ▼
fello-backend/backend  (Express, GCE VM :8080)  [fello-backend]
   │  verifies ID token + custom claims (org/project access)
   │  adds BAILEYS_API_SECRET
   ▼
fello-backend/gateway  (Express + Baileys, GCE VM :3000, localhost only)
   │  one Baileys session per "channel" (projectId, or org_<orgId>)
   ▼
WhatsApp (via Baileys)

Incoming WhatsApp message
   ▼
gateway forwards to backend  ──►  POST /internal/whatsapp/message
   (GATEWAY_WEBHOOK_SECRET, different secret from BAILEYS_API_SECRET)
   │
   ├─► INSERT INTO whatsapp_messages (Cloud SQL)
   │
   └─► if message needs AI (mentions "fello" or starts with "/")
         → Vertex AI Agent Engine (same deployed ADK agent as the dashboard)
         → reply posted back through the gateway's /send route
```

**The gateway is never reachable from outside the VM.** Only the backend
calls it (enforced by firewall — gateway's port 3000 has no ingress rule —
and by `BAILEYS_API_SECRET`). The frontend never talks to the gateway
directly and never holds `BAILEYS_API_SECRET`; it only ever sends a Firebase
ID token to the backend's public port 8080.

---

## 2. Key design decisions

### 2.1 QR-code pairing, not pairing-codes
The gateway originally used Baileys' `requestPairingCode` (type a code into
WhatsApp). Replaced with QR-code pairing (scan with the phone) because that's
the flow users expect from "link a WhatsApp number" — `POST
/sessions/:id/start` no longer takes a phone number up front; Baileys reports
the real linked E.164 number once pairing completes (`sock.user.id`).

### 2.2 One gateway, two kinds of sessions
- **Per-project number**: `fello-backend/gateway` sessions keyed by the raw
  Firestore `projectId`. Route: `/projects/:projectId/whatsapp/*`.
- **Org-wide shared number**: same gateway, sessions keyed by `org_<orgId>` —
  a distinct prefix so it can never collide with a projectId. Route:
  `/orgs/:orgId/whatsapp/*`. Configured from the org Settings page, not a
  project page — this is the number the *whole organization* coordinates
  through, separate from any one project's dedicated number.
- The message webhook (`fello-backend/backend/src/message-webhook.js`)
  resolves whichever kind of channel key the gateway forwards
  (`resolveChannelScope`) back to `{ orgId, tenantId, eventId }`. Org-wide
  messages get the `"org-wide"` sentinel `event_id` (the column is `NOT
  NULL`, so there's no bare-null option without a schema migration — not
  worth it for a sentinel).

### 2.3 Disconnect detection (phone-side unlink)
Baileys reports a logged-out disconnect (`DisconnectReason.loggedOut`) when
the user removes the linked device from their phone. Originally the gateway
just deleted the in-memory session on logout, so `/status` and `/qr` 404'd —
indistinguishable from "never connected", and the dashboard kept showing a
stale "Connected" forever. Fixed by:
- Keeping the session entry with a new `status: "disconnected"` (instead of
  deleting it) so the frontend can tell "never linked" apart from "was
  linked, then unlinked".
- Wiping the now-invalid saved credentials (`sessions/<id>/` auth folder) on
  logout — otherwise Baileys keeps retrying the same dead identity and never
  produces a fresh QR on the next `/start`.
- `/start` now actually restarts a session when the existing one is
  `disconnected` (previously it short-circuited and returned the stale entry).
- Backend persists `disconnected` (not just `connected`) to Firestore
  (`whatsappStatus` on the project/org doc), and the frontend does one live
  status check on page load — not just trusting the cached Firestore field —
  since the phone-side unlink can happen while nobody has the page open.
- Frontend shows **"Disconnected — was +xxx"** and a **"Connect again"**
  button, distinct from "Not connected" / "Connect WhatsApp".

### 2.4 Backend is the only trust boundary
All Firebase ID token verification and org/project access-scope resolution
happens in `fello-backend/backend/src/firebase.js` — a deliberate small port
of `fello-frontend/lib/firebase-admin.ts`'s `verifyActor` /
`resolveOrgScope` / `resolveProjectScope`, since the backend is a separate
Express service (not Next.js) and can't import that file directly. Keep
these two in sync if the claims shape changes.

### 2.5 AI-trigger heuristic
`needsAi(body)` in `message-webhook.js` is intentionally simple: trigger if
the message mentions "fello" (word-boundary, case-insensitive) or starts with
`/`. Every message is still stored in Postgres regardless — only the
AI-routing decision is gated by this heuristic. Not an ML classifier by
design; this is a coordination bot in a group chat, not a general assistant
that should reply to everything.

### 2.6 Reused the dashboard's ADK agent (Vertex AI Agent Engine)
`fello-agent/` is deployed to **Vertex AI Agent Engine**, not the old
TypeScript "agent" service sketched in `BACKEND.md` (that doc is stale —
ignore its §4). The backend's `src/agent-client.js` is a Node port of
`fello-frontend/lib/agent-engine.ts`'s `createAgentSession` /
`streamAgentReply`, trimmed to a single non-streaming call (WhatsApp gets one
final reply, not the dashboard's live token streaming). Same
`AGENT_ENGINE_RESOURCE_NAME` env var, same `GoogleAuth`/ADC pattern.

---

## 3. The recurring bug: env vars only in `.env.local`

**This has bitten twice — read this before debugging a "not configured" /
"isn't reachable" error in production.**

`fello-frontend/.env.local` is gitignored (correctly — it's where local
secrets live) but that means **anything only set there never reaches the
deployed Firebase App Hosting / Cloud Run service.** Firebase App Hosting
reads runtime env vars from **`apphosting.yaml`** (tracked in git), not from
`.env.local`. Two real incidents from this:

1. `BACKEND_API_URL` — set locally, never deployed → "Couldn't connect /
   WhatsApp backend is not configured" in production. Fixed by adding it to
   `apphosting.yaml`'s `env:` list with `availability: [RUNTIME]`.
2. `AGENT_ENGINE_RESOURCE_NAME` — same trap → `agentEngineConfigured()` false
   in production → chat route fell through to the direct-NIM fallback, which
   then failed too since `NVIDIA_API_KEY` also isn't set → "The AI agent
   isn't reachable right now" surfaced to users. Fixed the same way.

**Rule going forward: any env var a server-only code path depends on must be
added to `apphosting.yaml`, not just `.env.local`.** `.env.local` is for local
`pnpm dev` only. Check `apphosting.yaml`'s current `env:` list before
assuming a var reaches production.

---

## 4. Deployment — what's actually live

Project: `fello-pt`. Real, billable GCP infrastructure (not a simulation).

### 4.1 GCE VM — `fello-gateway`
- Zone `us-central1-a`, machine type `e2-small`, Debian 12, 20GB disk.
- Runs both `fello-backend/gateway` (port 3000, localhost-only — no firewall
  ingress rule) and `fello-backend/backend` (port 8080, public) under `pm2`
  (`pm2 startup` + `pm2 save` so both survive a VM reboot).
- Attached service account: `fello-gateway-vm@fello-pt.iam.gserviceaccount.com`
  with roles `aiplatform.user` (Agent Engine calls via ADC, no key file),
  `cloudsql.client` (Cloud SQL Auth Proxy), `datastore.user` +
  `firebaseauth.admin` (Firestore reads + ID token verification via ADC).
- Firewall rule `fello-backend-http`: `tcp:8080` open to `0.0.0.0/0`, tagged
  `fello-backend`. Nothing else is open — gateway port 3000 is unreachable
  from outside the VM by construction (no rule admits it).
- `.env` files live directly on the VM at `~/app/gateway/.env` and
  `~/app/backend/.env` (loaded via `dotenv` — added as a dependency to both
  services specifically for this). **Not in git** — they hold
  `BAILEYS_API_SECRET`, `GATEWAY_WEBHOOK_SECRET`, and `DATABASE_URL`
  (Cloud SQL password included). Redeploying code does not touch these.

### 4.2 Cloud SQL — `fello-db`
- Postgres 15, tier `db-f1-micro` (cheapest tier that supports Postgres —
  `db-f1-micro`/shared-core is fine for demo-scale traffic), region
  `us-central1`, 10GB HDD.
- Database `fello`, schema applied from `fello-backend/db/schema.sql`
  (`whatsapp_messages`, `message_events`, `documents`).
- Reached from the VM via the **Cloud SQL Auth Proxy** running as a systemd
  service (`/etc/systemd/system/cloud-sql-proxy.service`), listening on
  `127.0.0.1:5432`, authenticated via ADC (the VM's service account) — no
  password-based network exposure, no public-IP allowlisting needed for the
  running service. `DATABASE_URL` in the backend's `.env` points at
  `postgresql://postgres:<password>@127.0.0.1:5432/fello`.
- The instance *does* have a public IP (used once, temporarily, to run the
  initial schema migration via `psql` from this dev box — the authorized
  network was added, schema applied, then immediately removed again). Normal
  operation never uses the public IP; only the proxy.

### 4.3 Redeploying code changes to the VM
There's no CI/CD for the VM yet — it's a manual `tar` + `scp` + `pm2
restart` cycle:
```bash
cd fello-backend
tar --exclude=node_modules --exclude=sessions -czf /tmp/gateway.tar.gz gateway
tar --exclude=node_modules -czf /tmp/backend.tar.gz backend
gcloud compute scp /tmp/gateway.tar.gz /tmp/backend.tar.gz fello-gateway:~/ \
  --project=fello-pt --zone=us-central1-a

gcloud compute ssh fello-gateway --project=fello-pt --zone=us-central1-a --command='
  tar -xzf gateway.tar.gz -C ~/app
  tar -xzf backend.tar.gz -C ~/app
  cd ~/app/gateway && npm install   # only if package.json changed
  cd ~/app/backend && npm install   # only if package.json changed
  pm2 restart gateway backend
'
```
`sessions/` (gateway's per-channel Baileys auth folders) and both `.env`
files are deliberately excluded/preserved — never overwritten by a redeploy.

### 4.4 Frontend deployment
`fello-frontend` deploys via **Firebase App Hosting**, which auto-builds
from pushes to `main` on Cloud Build (Cloud Native Buildpacks, not this dev
box) and runs on Cloud Run under the hood (service `fello`, region
`us-east4` — a different region from the backend VM/Cloud SQL, which are in
`us-central1`; this is fine, cross-region calls just add a little latency).
See `fello-frontend/FIREBASE_DEPLOYMENT.md` for the build-environment
gotchas (pnpm v11, Node 24, `strictDepBuilds`). See §3 above for the env var
gotcha specific to this integration.

---

## 5. Known gaps / not yet done

- No CI/CD for the VM — redeploys are manual (§4.3).
- No monitoring/alerting on the gateway or backend process (pm2 restarts on
  crash, but nothing pages anyone).
- `needsAi()` is a simple keyword heuristic (§2.6), not configurable per org.
- Cloud SQL is a single `db-f1-micro` instance, no read replica / backup
  schedule configured beyond Cloud SQL's defaults — fine for a demo, not for
  production load.
- The org-wide WhatsApp number and a project's own dedicated number are
  fully independent — there's no UI yet to see "which projects are using the
  org-wide number vs their own" in one place.
