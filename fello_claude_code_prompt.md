# Fello — Claude Code Build Prompt

## What We're Building

Fello is an AI-powered organization management platform starting with university student branches — specifically IEEE student branches — and expanding to all volunteer-run organizations, clubs, and societies. The core insight is that organizational structure exists nowhere in encoded form, so everything gets rebuilt manually every event. Fello encodes that structure once, and AI handles the repetitive coordination work from there.

The platform won't replace WhatsApp — it sits on top of it. WhatsApp is where students already communicate. Fello's AI agent lives inside those groups, listens, understands context, and orchestrates everything in the background.

---

## The Problem We're Solving

From real user research with IEEE student branch members:

- WhatsApp groups rebuilt from scratch manually for every event — 8 groups, different people, exhausting
- Follow-up is the most draining part — replying to messages takes most of a coordinator's time
- Outreach tracked in spreadsheets — one person called 500+ companies and logged every response manually
- Tasks get lost — nobody knows who's doing what without asking
- Documents bounce between teams — "ask publicity, ask secretary, ask chair — deadline passes"
- Files scattered across personal drives, WhatsApp, email — nobody knows what exists or where
- Forms rebuilt manually every event — same fields, every time
- Automations are all manual and repeated — nobody has time to build them

---

## Tech Stack

- **Frontend**: Next.js latest version (App Router), TypeScript, Tailwind CSS
- **Auth**: Firebase Auth — Google OAuth + Microsoft OAuth + WhatsApp OTP verification
- **Primary database**: Firestore — org structure, events, tasks, outreach, automations, summaries
- **Secondary database**: Cloud SQL (PostgreSQL) — WhatsApp messages with FTS, documents index
- **Backend**: Cloud Run — API, auth middleware, ADK agents
- **AI**: Google ADK (Agent Development Kit) + Vertex AI (Gemini)
- **WhatsApp gateway**: Baileys running on GCE VM (persistent session)
- **File storage**: Google Drive API — org and event folder management
- **Forms**: Google Forms API + Apps Script triggers
- **Calendar**: Google Calendar API
- **Secrets**: Google Cloud Secret Manager
- **Hosting**: Firebase Hosting (frontend)

---

## Brand

**Name**: Fello

**Logo**: Three dots connected by two lines forming a half triangle — open at the top. Bottom dot slightly larger. Clean, minimal, ownable.

**Tone**: Warm, human, not corporate. Feels like a reliable colleague, not enterprise software.

---

## UI & Design System

### Setup commands

Run these in order when starting the project:

```bash
# Initialize shadcn with preset
pnpm dlx shadcn@latest init --preset b1VlIttI --template next

# Sign in page
npx shadcn@latest add login-05

# Sidebar layout
npx shadcn@latest add sidebar-08
```

### Reference repo — study this before writing any UI code

Clone and study this repo before building any UI:
https://github.com/kavinduUdhara/uni-log-kavindu/

Pay attention to:
- How the sidebar is structured and modified from the base shadcn sidebar
- The border radius pattern on grouped list items
- Spacing, layout, and component composition patterns

Replicate the same approach in Fello. Do not deviate from what's established there.

### Use shadcn components as much as possible

Never build custom UI components from scratch if a shadcn equivalent exists. Always reach for shadcn first.

### Sidebar layout

Use `sidebar-08` as the base. Modify it to match the layout pattern in the uni-log-kavindu repo exactly — same structure, same spacing, same behavior.

### Border radius pattern for grouped lists

This is a specific UI pattern that must be followed consistently everywhere a list of buttons or items is grouped together. Study the exact implementation in uni-log-kavindu and replicate it.

The pattern:
- **First item** — high border radius on top corners, low border radius on bottom corners
- **Middle items** — low border radius on all corners
- **Last item** — low border radius on top corners, high border radius on bottom corners
- **Single item** — high border radius on all corners


This applies to: navigation lists in sidebar, action button groups, menu items, any vertically stacked list of interactive elements.

### Colors

Do not hardcode any colors. Never use hex values or Tailwind color utilities like `bg-blue-500` directly. Use shadcn CSS variables throughout — `bg-background`, `text-foreground`, `text-muted-foreground`, `border`, etc. The preset `b1VlIttI` defines the entire color system — follow it exclusively.

---

## Architecture Overview

### Tenant and Org Identity (Multi-tenant)

Every user belongs to a tenant determined by their email domain (e.g., `my.sliit.lk`).
- **Tenant ID**: The full email domain.
- **Namespace**: Chosen by each institution (e.g., `sliit`), globally unique, used only in URLs.
- **Slug**: Org slug (e.g., `ieee`) unique within that tenant only.
- **URL Path**: namespace/slug (e.g., `sliit/ieee`) display alias.
- **Internal UUID**: Orgs have an internal UUID (`org_8f3k2a9x`) used in all documents, security rules, and membership checks. Slug and namespace are just display aliases.

### Firebase Auth with custom claims

After sign in, custom claims are written into the user's JWT:

```typescript
{
  tenantId: "my.sliit.lk",        // full domain
  orgs: {
    "org_8f3k2a9x": {
      access: "full",
      nodeId: "node_2m5k9x3a",
      capabilities: [
        "drive.read", "drive.write",
        "whatsapp.send", "whatsapp.manage",
        "members.manage", "tasks.manage",
        "events.manage", "analytics.view"
      ]
    },
    "org_3k9x2a1b": {
      access: "readonly",          // inherited from parent org
      nodeId: "node_1a2b3c4d",
      via: "org_8f3k2a9x",         // which direct membership gave this access
      capabilities: []
    }
  },
  events: {
    "evt_9k2m3x1a": {
      access: "event_only",
      orgId: "org_8f3k2a9x"
    }
  },
  whatsappVerified: true,
  claimsVersion: 3                 // compared against structureVersion for lazy refresh
}
```

Claims are computed once at sign in. Zero document reads on subsequent requests — pure token evaluation.

When roles change, update claims immediately and force token refresh on the client:
```javascript
await firebase.auth().currentUser.getIdToken(true);
```

### Firestore security rules

Rules check the JWT token only — zero document reads for permission checks.

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    function canAccess(orgId) {
      return orgId in request.auth.token.orgs;
    }

    function getAccess(orgId) {
      return request.auth.token.orgs[orgId].access;
    }

    function hasCapability(orgId, capability) {
      return capability in request.auth.token.orgs[orgId].capabilities;
    }

    function canWrite(orgId) {
      return canAccess(orgId)
        && getAccess(orgId) != 'readonly'
        && getAccess(orgId) != 'event_only';
    }

    function sameTenant(tenantId) {
      return request.auth.token.tenantId == tenantId;
    }

    match /institutions/{domain} {
      allow read: if request.auth.token.tenantId == domain;
      allow write: if false;
    }

    match /organizations/{orgId} {
      allow read: if canAccess(orgId) && sameTenant(resource.data.tenantId);
      allow write: if canAccess(orgId) && getAccess(orgId) == 'full' && sameTenant(resource.data.tenantId);
    }

    match /org_nodes/{nodeId} {
      allow read: if canAccess(resource.data.orgId) && sameTenant(resource.data.tenantId);
      allow write: if canAccess(resource.data.orgId) && getAccess(resource.data.orgId) == 'full' && sameTenant(resource.data.tenantId);
    }

    match /memberships/{membershipId} {
      allow read: if canAccess(resource.data.orgId) && sameTenant(resource.data.tenantId);
      allow write: if canAccess(resource.data.orgId) && getAccess(resource.data.orgId) == 'full' && sameTenant(resource.data.tenantId);
    }

    match /users/{userId} {
      allow read: if request.auth.uid == userId;
      allow write: if request.auth.uid == userId;
    }

    match /events/{eventId} {
      allow read: if canAccess(resource.data.orgId) && sameTenant(resource.data.tenantId);
      allow write: if canWrite(resource.data.orgId) && sameTenant(resource.data.tenantId);
    }

    match /tasks/{taskId} {
      allow read: if canAccess(resource.data.orgId) && sameTenant(resource.data.tenantId);
      allow write: if canWrite(resource.data.orgId) && sameTenant(resource.data.tenantId);
    }
  }
}
```

### Firestore collections

```
institutions/{domain}
  domain, namespace, displayName, verified, createdAt, structureVersion

organizations/{internalId}
  id, tenantId, slug, fullPath, name, logo, parentId, ancestors[], verified, verificationStatus, createdBy, createdAt, structureVersion

org_nodes/{internalId}
  id, orgId, tenantId, parentId, ancestors[], name, type, depth, createdAt

memberships/{userId}_{internalOrgId}
  userId, orgId, tenantId, nodeId, role, access, capabilities[], addedBy, addedAt

users/{uid}
  uid, email, tenantId, name, photo, whatsappNumber, whatsappVerified, lastOpenedOrg, createdAt, claimsVersion

events/{internalId}
  id, orgId, tenantId, nodeId, name, type (event/project), status (active/closed), date, driveAccountType, driveRootFolderId, whatsappGatewayNumber, createdBy, createdAt

tasks/{internalId}
  id, orgId, tenantId, eventId, title, assigneeId, deadline, status, createdBy, createdAt

outreach/{internalId}
  id, orgId, tenantId, eventId, contactName, company, email, phone, status, lastContactAt, nextFollowUp, notes

automations/{internalId}
  id, orgId, tenantId, eventId, name, trigger, config, status, createdBy, approvedBy, createdAt

event_summaries/{eventId}
  eventId, orgId, tenantId, eventName, dateRange, generatedAt, narrativeSummary, tasksCompleted, tasksMissed, totalMembers, topContributors, groupSummaries, keyDecisions, blockers, lessonsLearned

whatsapp_groups/{internalId}
  id, orgId, tenantId, eventId, jid, name, type, members[], createdAt

otp_verifications/{whatsappNumber}
  otp, expiresAt, verified, userId, attempts

waitlist/{email}
  email, domain, orgName, requestedAt
```

### Cloud SQL (PostgreSQL) schema

```sql
-- WhatsApp messages with full text search
CREATE TABLE whatsapp_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  group_jid TEXT NOT NULL,
  sender_id TEXT NOT NULL,
  sender_name TEXT NOT NULL,
  body TEXT NOT NULL,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', body)) STORED
);

CREATE INDEX idx_messages_org_event ON whatsapp_messages(org_id, event_id, timestamp DESC);
CREATE INDEX idx_messages_fts ON whatsapp_messages USING GIN(search_vector);
CREATE INDEX idx_messages_group ON whatsapp_messages(org_id, group_jid, timestamp DESC);

-- Structured extractions from messages
CREATE TABLE message_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  group_jid TEXT NOT NULL,
  sender_id TEXT NOT NULL,
  type TEXT NOT NULL,
  action TEXT,
  task_id TEXT,
  raw_message_id UUID REFERENCES whatsapp_messages(id),
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_message_events_org_event_type ON message_events(org_id, event_id, type, timestamp DESC);

-- Unified document index — all files from all sources
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  team_node_id TEXT NOT NULL,
  file_name TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  drive_file_id TEXT NOT NULL,
  source TEXT NOT NULL, -- 'whatsapp', 'drive_direct', 'form', 'generated'
  uploaded_by TEXT,
  group_jid TEXT,
  message_id UUID REFERENCES whatsapp_messages(id),
  search_vector TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', file_name)) STORED,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_docs_org_event ON documents(org_id, event_id, timestamp DESC);
CREATE INDEX idx_docs_fts ON documents USING GIN(search_vector);
CREATE INDEX idx_docs_team ON documents(org_id, team_node_id, timestamp DESC);
```

---

## User Types and Access

```
Org admin          → created the org, full control
Branch chair       → full visibility across branch and all sub-branches (read only on children)
Sub-branch chair   → org admin of their specific sub-branch
Team lead          → their specific team node only
Team member        → their specific team node only
Event volunteer    → one event only, WhatsApp only, no dashboard access
Event delegate     → one event only, announcements only
```

### Capability system

Roles are not hardcoded. Each membership has a capabilities array that determines what functions are available. Admin describes roles in plain English, Fello maps to capability set, admin confirms.

Base capability sets:

```javascript
const ROLE_CAPABILITIES = {
  chair: ['gmail.read', 'gmail.send', 'drive.read', 'drive.write', 'whatsapp.send', 'whatsapp.manage', 'members.view', 'members.manage', 'tasks.manage', 'events.manage', 'analytics.view', 'finance.view', 'forms.create', 'calendar.manage', 'social.post'],
  secretary: ['gmail.read', 'gmail.send', 'drive.read', 'drive.write', 'whatsapp.send', 'members.view', 'tasks.manage', 'forms.create', 'calendar.view'],
  treasurer: ['drive.read', 'drive.write', 'finance.view', 'finance.manage', 'members.view', 'tasks.view'],
  webmaster: ['drive.read', 'social.post', 'social.manage', 'members.view', 'tasks.view'],
  design_lead: ['drive.read', 'drive.write', 'whatsapp.send', 'tasks.manage', 'forms.view'],
  member: ['drive.read', 'tasks.view', 'whatsapp.send'],
  volunteer: ['tasks.view', 'whatsapp.send'],
  event_only: ['tasks.view']
}
```

Capabilities are appended or removed via natural language — "our secretary also manages Instagram" adds `social.post` and `social.manage` to their capabilities.

---

## Authentication Flow

### Sign in paths

1. Google OAuth — primary for dashboard access
2. Microsoft OAuth — for university Microsoft accounts
3. WhatsApp OTP — every user must also verify their WhatsApp number

### Domain logic (Enforced)

- Known institution domains (defined in `config/domains` Firestore doc, e.g. `google.com`, `my.sliit.lk`) -> allowed to enter app.
- Personal domains (e.g. `gmail.com`, `yahoo.com`) -> rejected with inline error, signed out, added to "general" waitlist.
- Unknown institutional domains -> Firebase Auth session kept active (low-level session), redirected to `/waitlist?domain=xxx`. Waitlist page displays their Google/Microsoft profile picture and name using their active session, and shows a leaderboard fetched via Firebase REST API. Org selector strictly blocks and bounces them back if they attempt to bypass.

### WhatsApp OTP verification

User enters their personal WhatsApp number → Fello sends 6-digit OTP via Baileys → user receives in WhatsApp → enters OTP on Fello → number linked to Firebase account → JWT updated.

This links their WhatsApp identity to their Fello account so every message they send in event groups is attributed to their real profile and role.

### Multiple org contexts

A user can belong to multiple orgs. On first login they see all memberships and pick which context to enter. Choice is remembered. Can switch from profile at any time. URL changes per context: `fello.lk/org/sliit-ieee-ias`.

---

## Org Creation Flow

1. User signs in → no org exists for their account
2. Option: paste website URL → Fello scrapes org name and logo only
3. Or enter manually
4. Redirect to dashboard with chatbot front and center
5. Chatbot handles all onboarding conversationally
6. AI infers org type from name, structure, members — no upfront form
7. If IEEE detected → chatbot confirms and pre-loads branch template
8. Template includes: branch excom roles + 6 sub-branches (IAS, RAS, CS, PES, EMBS, WIE) each with their own excom

### IEEE hierarchy

```
SLIIT IEEE Branch
  Executive committee: Chair, Vice chair, Secretary, Treasurer, Webmaster, Asst. secretary
  Functional teams: Editorial, Public visibility, Volunteer management, Logistics, Finance
  Sub-branches:
    IAS — Chair, Vice chair, Secretary, Editor, Asst. treasurer
    RAS — Chair, Vice chair, Secretary, Editor, Asst. treasurer
    CS  — Chair, Vice chair, Secretary, Editor, Asst. treasurer
    PES — Chair, Vice chair, Secretary, Editor, Asst. treasurer
    EMBS — Chair, Vice chair, Secretary, Editor, Asst. treasurer
    WIE — Chair, Vice chair, Secretary, Editor, Asst. treasurer
```

Each sub-branch chair is the org admin of their sub-branch node.

### Org verification (pending state for now)

- Button on dashboard — "Get verified"
- Collect: student ID photo + public URL of executive committee announcement post
- Status shows pending
- Manual review (automated later)
- Verified badge unlocks higher automation limits

---

## Event/Project Creation Flow

Anyone in excom or with permission can create an event or project. Same underlying structure, type flag differentiates:

- `type: "event"` → has registration form, delegates, public date
- `type: "project"` → internal only, no registration

### Two creation paths

**Dashboard path:**
- Click new event/project
- Chatbot guides conversationally
- Name, type, date, teams
- Connect Google Drive — use org account subfolder OR connect separate Google account
- Connect WhatsApp — use org gateway OR connect separate number for this event
- Drive folders and WhatsApp groups created only after respective accounts are connected
- Agent joins all groups once created

**WhatsApp path (the killer feature):**
- IAS chair drops message in org WhatsApp group: "we gonna start a new event called PTI"
- Agent detects intent, creates event record in Firestore
- Agent responds: "Created PTI. Do you have a logo or shall we create one?"
- Chair: "let's create one"
- Agent: "When do you need it by?"
- Chair: "next Friday"
- Agent creates task, sends to IAS Design Team group: "Hey team, we need a logo for PTI by next Friday. Anyone interested?"
- Designer: "I can do it"
- Agent: "Can you deliver by Friday or do you need more time?"
- Designer: "I need Saturday"
- Agent negotiates back, gets confirmation, assigns task with deadline
- Everything reflected in dashboard automatically

---

## WhatsApp Gateway Architecture

### GCE VM (Baileys)

- Persistent VM running Baileys
- Handles QR code sessions
- One dedicated number per event/project — not shared with org gateway
- Agent lives inside all created groups for that event
- Receives all messages, passes through filter pipeline

### Message processing pipeline

```
Message arrives at VM
  → Stage 1 filter (on VM, free)
      Drop: under 5 chars, "ok/thanks/👍/noted", fromMe, media captions under 10 chars
      ~60-70% of messages dropped here
  → Store raw message in Cloud SQL (all messages that pass Stage 1)
  → Stage 2 filter (Cloud Run, cheap)
      Keyword check for intent signals: done/finished/completed/blocked/stuck/help/
      send/share/file/document/deadline/due/when/?/i can do/assign
  → Gemini extraction (only ~10-15% of messages)
      Pass message + event context to Gemini
      Extract structured intent: task update, document request, question, deadline mention
      Write to message_events table
  → Trigger automations if relevant
```

### Excom visibility

Excom and org admins don't need to be in every event WhatsApp group. They ask the AI agent — "what's happening in the PTI design group?" — agent queries Cloud SQL for that event's messages, summarizes, responds. Full visibility without presence.

### Delegate onboarding via WhatsApp

1. Event registration form auto-generated by Fello
2. Form confirmation includes WhatsApp group invite link
3. Delegate joins group themselves
4. Wait 30-60 minutes
5. Check if they joined — if not, send personal WhatsApp message with link
6. Prevents number flagging by spacing outbound messages
7. Agent sends one welcome message when group opens — not per person
8. Individual confirmation sent privately, not in group

---

## Google Drive Integration

### Folder structure per event

```
[Org Root Drive or Separate Event Drive]/
  [Event Name]/
    whatsapp-documents/     ← ALL files received via WhatsApp go here
    design-team/
    publicity-team/
    logistics/
    finance/
    speakers/
    general/
```

Event members only have access to their event's folder. Cannot see root or other events.

If separate Google account connected for event — entirely isolated Drive, no connection to org root.

### WhatsApp documents folder

Every file that arrives in any WhatsApp group for an event goes into the `whatsapp-documents` folder in that event's Drive. This is a flat catch-all folder — every file from every group lands here regardless of which team sent it.

- Baileys receives the file on the GCE VM
- Cloud Run downloads it from WhatsApp
- Cloud Run uploads it to `whatsapp-documents/` in the event's Drive folder
- File is immediately indexed in Cloud SQL `documents` table
- Agent confirms in the WhatsApp group: "Saved to Drive."

### File routing for team-specific uploads

If a file is uploaded directly to Drive (not via WhatsApp), it goes into the relevant team subfolder. Cloud Run knows which group maps to which team for WhatsApp uploads — but all WhatsApp files regardless of source group go to `whatsapp-documents/` first, then can be organized later.

### Document index in Cloud SQL

All files indexed in `documents` table — from WhatsApp (source: 'whatsapp'), from direct Drive upload (source: 'drive_direct'), from form responses (source: 'form'), from AI generation (source: 'generated'). Full text search on filename via tsvector GIN index.

Every WhatsApp file must have:
- `source: 'whatsapp'`
- `group_jid` — which group it came from
- `message_id` — links back to the WhatsApp message it was attached to
- `drive_file_id` — the Google Drive file ID for retrieval
- `drive_folder: 'whatsapp-documents'`

Agent retrieves files on request in WhatsApp groups using the `documents` index. When someone asks "send the logo" — agent searches `documents` table by filename FTS, gets `drive_file_id`, fetches from Drive, sends back to group.

---

## Google Forms + Apps Script Automations

When event is created → registration form auto-generated with relevant fields. Apps Script trigger attached programmatically.

Trigger fires on form submission → hits Cloud Run endpoint → Cloud Run processes → triggers relevant automations.

User-defined automations: described in plain English → Gemini interprets → admin approves → deployed and runs automatically. No pre-built templates — fully AI generated, admin approved.

Example automation: "When someone fills the registration form, wait 30 minutes, check if they joined the WhatsApp group, if not send them a personal message with the group link."

---

## AI Agent (ADK)

The agent is the brain of the platform. It:

- Monitors all event WhatsApp groups
- Extracts structured meaning from conversations
- Creates and updates tasks automatically
- Assigns work based on conversation
- Sends follow-up reminders
- Retrieves documents on request
- Answers natural language questions about event status
- Negotiates deadlines
- Summarizes group activity for excom
- Generates event summaries on close

### Context injected into every agent prompt

```javascript
{
  org: { name, type, hierarchy },
  event: { name, date, status, teams },
  tasks: [ { title, assignee, deadline, status } ],
  members: [ { name, role, whatsappNumber } ],
  recentMessages: [ last 50 from Cloud SQL ]
}
```

### Natural language queries

Any user can ask the agent anything about their org or event:

- "What's blocking PTI right now?"
- "Who hasn't responded to the sponsorship outreach?"
- "Are we on track for the deadline?"
- "Assign the poster task to the design team lead"
- "Send a reminder to everyone with overdue tasks"
- "What happened in the design group today?"
- "Find the latest logo file"

---

## Event Lifecycle

```
Event created (dashboard or WhatsApp)
  → Tasks assigned
  → WhatsApp groups created (when number connected)
  → Drive folders created (when Drive connected)
  → Registration form created (if public event)
  → Agent monitors all groups

During event
  → Messages flow in
  → Tasks updated via WhatsApp or dashboard
  → Files uploaded to Drive via WhatsApp or directly
  → Agent sends reminders
  → Excom views progress via AI summaries

Event closes
  → Admin or agent marks complete
  → Gemini generates full event summary
  → Summary stored in Firestore event_summaries
  → All WhatsApp messages deleted from Cloud SQL
  → Drive access restricted
  → Learnings available for future events
```

---

## Demo Flow (The PTI Story — for competition video)

This is the exact sequence to demonstrate:

1. Vice chair drops message in IEEE IAS WhatsApp group: "guys we have a new event called PTI, need a logo"
2. Fello agent picks it up — creates PTI event, creates task "design logo"
3. Agent sends to IAS Design Team group: "New event PTI needs a logo. Anyone available?"
4. Designer: "I can do it"
5. Agent assigns task, confirms deadline
6. Logo done — designer says "logo is done" in group
7. Agent marks task complete, notifies chair
8. Agent asks: "Want me to create a volunteer registration form for PTI?"
9. Chair: "yes"
10. Form created automatically
11. Agent: "Want me to set up interview slots on Google Calendar?"
12. Calendar slots created
13. Volunteer interview WhatsApp group created
14. Agent sends reminders to registered volunteers about their booked slots
15. Chair asks on dashboard: "what's the status of PTI?" — agent responds with full summary

---

## Competition Brief Alignment

**Brief**: AI for Better Living and Smarter Communities — Build an AI-powered Decision Intelligence Platform.

**Our home in the brief**: Community Support and Social Impact Initiatives.

**Direct hits**:
- Natural language interaction → agent answers any question about org/event status
- Workflow automation → WhatsApp group creation, task assignment, follow-ups, form generation
- LLMs and ADK → Gemini for intent extraction, ADK for agent orchestration
- Ingest data from multiple sources → WhatsApp, Google Drive, Google Forms, Google Calendar
- Identify patterns and anomalies → bottleneck detection, overdue tasks, workload imbalance
- Decision support → "should we follow up with this sponsor?" based on response history
- Google Cloud stack → Firebase, ADK, Vertex AI, Cloud Run, Cloud SQL, GCE, Secret Manager

**The pitch**: Community organizations are the backbone of student development. They run on WhatsApp groups and spreadsheets. Fello changes that.

---

## What to Build First (Day 1-2 Priority)

1. Run `pnpm dlx shadcn@latest init --preset b1VlIttI --template next` to scaffold the project
2. Clone https://github.com/kavinduUdhara/uni-log-kavindu/ and study sidebar and border radius patterns before writing any UI
3. Add `login-05` and `sidebar-08` shadcn blocks
4. Firebase project — Auth with Google + Microsoft OAuth
5. Firestore — core collections: users, organizations, org_nodes, memberships
6. Firebase security rules — tenant isolation, capability checks
7. Cloud Run — basic API endpoint, custom claims generation after sign in
8. GCE VM — Baileys running with test number, QR session working
9. Cloud SQL — PostgreSQL instance, tables created with indexes
10. Basic sign in flow end to end — sign in → domain check → org creation chatbot → dashboard

Get everything connected and talking before building any features. The demo story comes after the infrastructure is solid.

---

## Important Decisions Already Made

- No vector database for now — Firestore index + PostgreSQL FTS is sufficient
- WhatsApp messages stored in Cloud SQL, deleted on event close after summary generated
- Documents indexed in Cloud SQL `documents` table — not Firestore
- Capabilities are dynamic and appendable — not hardcoded roles
- Multi-context switching like Slack workspaces -> URL changes per org context
- Domain restriction is STRICTLY enforced: personal emails are rejected and signed out, unknown institutional domains are granted low-level sessions restricted only to the `/waitlist` page.
- WhatsApp OTP required for all users — links their personal number to their Fello account
- Each event gets its own dedicated WhatsApp number — not shared with org gateway
- Excom accesses event group data through AI summaries — not by being in every group
- No pre-built automation templates — fully AI generated, admin approved
- Connection of Google Drive and WhatsApp per event is optional — core task management works without them
- No hardcoded colors anywhere — use shadcn CSS variables exclusively
