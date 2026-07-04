# CLAUDE.md — Fello Project Instructions

This file is the single source of truth for Claude Code when working on the Fello codebase. Read every section before writing any code, creating any file, or running any command. Do not skip sections — every detail here was deliberately decided.

---

## 0. What Is Fello?

Fello is an AI-powered coordination platform for volunteer and civic organizations (university clubs, IEEE student branches, NGOs, PTI groups). The core problem it solves: organizational structure is never encoded anywhere, so every event forces volunteers to manually reconstruct teams, WhatsApp groups, communication channels, and document workflows from scratch.

Fello sits **on top of WhatsApp** rather than replacing it. An AI agent lives inside WhatsApp groups, listens to conversations, and orchestrates coordination work automatically. A web dashboard (chatbot-first interface) is the primary human control surface.

The primary demo narrative is a **PTI (Parents-Teachers Interaction) event coordination flow**.

---

## 1. Repository Layout

```
fello-frontend/          ← Next.js App Router frontend (primary workspace)
  app/
    (bare)/              ← Auth, setup, onboarding (no sidebar)
      page.tsx           ← Org selector / landing
      sign-in/
      setup/             ← WhatsApp OTP verification / user setup
      waitlist/
      org/
        join/
        new/
    org/
      [orgId]/           ← Full app layout (sidebar present)
        layout.tsx
        page.tsx         ← Org home / chatbot dashboard
        events/          ← NOT YET SCAFFOLDED
        members/         ← NOT YET SCAFFOLDED
        settings/        ← NOT YET SCAFFOLDED
  components/
    layout/              ← app-sidebar, nav-main, nav-projects, nav-secondary, nav-user, theme-provider
    ui/                  ← shadcn primitive components (see Section 6)
    auth/                ← login-form.tsx
  hooks/
    use-auth.ts
    use-mobile.ts
  lib/
    firebase.ts
    utils.ts
    actions/
      auth.ts
```

---

## 2. Tech Stack — Exact Versions and Tools

| Layer | Technology | Notes |
|---|---|---|
| Frontend framework | Next.js (latest), App Router | pnpm only |
| UI components | shadcn/ui | Preset: `pnpm dlx shadcn@latest init --preset b1VlIttI --template next` |
| Styling | Tailwind CSS | No hardcoded colors — shadcn CSS variables only |
| Auth | Firebase Auth | JWT custom claims baked at sign-in |
| Primary DB | Firestore | Org structure, multi-tenant hierarchy |
| Secondary DB | Cloud SQL / PostgreSQL | WhatsApp messages, document indexing, full-text search |
| WhatsApp integration | Baileys library | On a GCE VM (persistent session); one dedicated number per event |
| AI agent layer | Google ADK + Gemini | See Section 8 |
| Hosting | GCE (Baileys VM), Cloud Run / Vercel (frontend) | |
| Domain | `fello.lk` (static landing), `app.fello.lk` (product) |  |
| Package manager | pnpm | Never use npm or yarn |

---

## 3. UI Rules — Non-Negotiable

These rules apply to every single UI component and page you write. Violating them requires explicit approval.

**CRITICAL:** Refer to [DESIGN_PRINCIPLES.md](file:///home/kavindu/repos/fello/DESIGN_PRINCIPLES.md) in the workspace root for Kavindu's layout preferences, image containment/padding rules, default visuals, inline slug structures, and button designs.

### 3.1 Reference Repo

Before writing any UI code, study the existing repo at:
```
https://github.com/kavinduUdhara/uni-log-kavindu
```
Follow the exact patterns used there for:
- Component structure
- shadcn component usage
- Border radius patterns for grouped list items (rounded top corners on first item, rounded bottom corners on last item, square on middle items)
- Spacing and layout conventions

### 3.2 Colors

**Never hardcode any color.** Use only shadcn CSS variables:
- `bg-background`, `bg-card`, `bg-muted`, `bg-primary`, `bg-secondary`, `bg-accent`, `bg-destructive`
- `text-foreground`, `text-muted-foreground`, `text-primary-foreground`, etc.
- `border`, `ring`, `input`

### 3.3 Components

Use shadcn components exclusively for all UI primitives. Do not install or use any other component library. The installed primitives are:
`alert`, `avatar`, `breadcrumb`, `button`, `collapsible`, `dropdown-menu`, `field`, `hover-card`, `input`, `label`, `rounded-list`, `select`, `separator`, `sheet`, `sidebar`, `skeleton`, `tooltip`

Install additional shadcn components with `pnpm dlx shadcn@latest add <component>` when needed.

### 3.4 Border Radius Pattern for Lists

When rendering a list of grouped items (e.g., member list, event list, task list):
- First item: `rounded-t-lg rounded-b-none`
- Middle items: `rounded-none`
- Last item: `rounded-t-none rounded-b-lg`
- Single item: `rounded-lg`

This pattern must match exactly what is in the reference repo.

### 3.5 No Form Tags

Never use HTML `<form>` tags. Use `onClick` / `onChange` handlers on buttons and inputs instead.

---

## 4. Authentication Architecture

### 4.1 Flow Overview

1. User enters phone number → receives WhatsApp OTP
2. OTP verified → Firebase Auth custom token created server-side
3. Firebase Auth signs in with custom token → issues Firebase ID token
4. On sign-in, Firebase Auth custom claims are baked into the JWT: tenantId (domain), orgs map (keyed by internal UUIDs), events map, whatsappVerified, and claimsVersion.
5. All permission checks use these JWT claims — **zero Firestore reads for permission checks**

### 4.2 Why WhatsApp OTP (not reverse-message flow)

WhatsApp OTP was chosen over the reverse-message flow (user sends a message to a Fello number) because it has lower friction for the user. This is a deliberate, reasoned tradeoff — do not suggest changing it.

### 4.3 Custom Claims Structure

Baked into JWT at sign in — zero DB reads on subsequent requests.
```typescript
interface FelloCustomClaims {
  tenantId: string;        // full email domain (e.g. "my.sliit.lk")
  orgs: {
    [internalOrgId: string]: { // internal UUID (e.g. "org_8f3k2a9x")
      access: "full" | "coordinator" | "team" | "readonly" | "event_only";
      nodeId: string;      // which specific node in the hierarchy
      capabilities: string[];
      via?: string;        // parent org ID if inherited access
    }
  };
  events: {
    [internalEventId: string]: {
      access: "event_only";
      orgId: string;       // internal UUID of parent org
    }
  };
  whatsappVerified: boolean;
  claimsVersion: number;
}
```

### 4.4 Server Actions

Auth server actions live in `lib/actions/auth.ts`. Keep all Firebase Admin SDK calls here — never in client components.

---

## 5. Multi-Tenant Architecture — Security First

This is Fello's primary product moat. Every data access pattern must respect it.

### 5.1 Tenant and Org Identity

- **Tenant**: Every user belongs to a tenant determined by their email domain (e.g., `my.sliit.lk`, `nsbm.ac.lk`). The full domain is the tenant ID, used for data isolation and security.
- **Namespace**: Derived automatically from the email domain by replacing all dots with hyphens and lowercasing everything (e.g., `my.sliit.lk` becomes `my-sliit-lk`). Computed deterministically on the server/client whenever needed. It is only ever used for URL routing and is never stored in Firestore documents.
- **Slug**: Orgs have a short slug (e.g., `ieee`) unique within the tenant only. Two tenants can both have `ieee`.
- **URL Path**: `/org/[tenant-namespace]/[org-slug]` (e.g., `/org/my-sliit-lk/ieee`).
- **Internal UUID**: Orgs have an internal UUID (`org_8f3k2a9x`) used in all documents, security rules, and membership checks. Slugs and namespaces are just display aliases.

### 5.2 Firestore Data Model (Flat Collections)

We use flat collections at the root level rather than nested subcollections. Tenant boundaries are enforced on every document using `tenantId` (the email domain) and `orgId` (internal UUID).

- `institutions/{domain}`: Keyed by domain.
- `organizations/{internalId}`: Keyed by internal UUID.
- `org_nodes/{internalId}`: Any sub-branch, team, or department.
- `memberships/{userId}_{internalOrgId}`: Composite ID for single read lookup.
- `users/{uid}`: Authenticated user profiles.
- `events/{internalId}`: Keyed by internal UUID.
- `tasks/{internalId}`: Keyed by internal UUID.
- `outreach/{internalId}`: Sponsor/speaker outreach logs.
- `automations/{internalId}`: Trigger-specific automation configs.
- `event_summaries/{eventId}`: Generated event wrap-ups.
- `whatsapp_groups/{internalId}`: Managed WhatsApp group registries.
- `otp_verifications/{whatsappNumber}`: OTP verification records.
- `waitlist/{email}`: Request list for new institutions.

### 5.3 PostgreSQL (Cloud SQL) Tenant Isolation

Every table that stores WhatsApp messages or document indexes must have an `org_id` column. Row-Level Security (RLS) must be enabled and policies must enforce `org_id` matching the authenticated tenant/org.

---

## 6. Firestore Data Model Details

### institutions/{domain}
```typescript
{
  domain: string,          // Document ID (e.g. "my.sliit.lk"), never changes. URL namespace is computed: domain.replaceAll('.', '-')
  displayName: string,
  verified: boolean,
  createdAt: Timestamp,
  structureVersion: number
}
```

### organizations/{internalId}
```typescript
{
  id: string,              // Internal UUID, Document ID (e.g. "org_8f3k2a9x")
  tenantId: string,        // Full email domain (e.g. "my.sliit.lk")
  slug: string,            // Unique within this tenant only (e.g., "ieee")
  name: string,
  logo: string,
  parentId: string | null,
  ancestors: string[],     // computed on creation
  verified: boolean,
  verificationStatus: "pending" | "approved" | "rejected",
  createdBy: string,
  createdAt: Timestamp,
  structureVersion: number
}
```

### memberships/{userId}_{internalOrgId}
```typescript
{
  userId: string,
  orgId: string,          // Internal UUID
  tenantId: string,       // Tenant boundary
  nodeId: string,         // Specific node in org hierarchy
  role: string,           // e.g. "design_lead"
  access: "full" | "coordinator" | "team" | "readonly" | "event_only",
  capabilities: string[], // permissions list
  addedBy: string,
  addedAt: Timestamp
}
```

### events/{internalId}
```typescript
{
  id: string,             // Internal UUID
  orgId: string,          // Internal UUID
  tenantId: string,       // Tenant boundary
  nodeId: string,         // Associated node
  name: string,
  type: "event" | "project",
  status: "active" | "closed",
  date: Timestamp | null,
  driveAccountType: "org" | "separate",
  driveRootFolderId: string,
  whatsappGatewayNumber: string | null,
  createdBy: string,
  createdAt: Timestamp
}
```

### tasks/{internalId}
```typescript
{
  id: string,
  orgId: string,          // Internal UUID
  tenantId: string,       // Tenant boundary
  eventId: string,        // Event UUID
  title: string,
  assigneeId: string | null,
  deadline: Timestamp | null,
  status: "unassigned" | "assigned" | "in_progress" | "completed" | "blocked",
  createdBy: string,
  createdAt: Timestamp
}
```

---

## 7. WhatsApp Integration (Baileys)

### 7.1 Architecture

- Baileys runs on a **GCE VM** (not Cloud Run — Cloud Run was ruled out because Baileys requires a persistent WebSocket session)
- **One dedicated WhatsApp number per event** (not per org) — this is intentional for clear context separation
- Railway is an acceptable alternative to GCE if needed

### 7.2 What Baileys Does

- Maintains persistent WhatsApp sessions
- Listens to all messages in registered groups
- Forwards messages to the AI agent layer (Google ADK) via internal API
- Executes actions sent back from the agent (send messages, create groups, add members)

### 7.3 Message Storage

Raw WhatsApp messages are stored in **PostgreSQL (Cloud SQL)**, not Firestore. This enables:
- Full-text search across message history
- Document indexing
- Efficient time-range queries

**Encrypted raw message storage was deliberately removed** — the use case did not justify the complexity. Store messages in plaintext with tenant isolation enforced via RLS.

### 7.4 WhatsApp Group Lifecycle

For each event, the agent can:
1. Create a new WhatsApp group
2. Add members by their phone numbers (from the members directory)
3. Set group name and description
4. Monitor conversations in the group
5. Archive or close the group when the event is complete

Manual WhatsApp group creation per event is the primary pain point being eliminated.

---

## 8. AI Agent Layer (Google ADK + Gemini)

### 8.1 Overview

The agent is built with **Google ADK** (Agent Development Kit) using **Gemini** as the underlying model. It is the brain of Fello — it listens to WhatsApp conversations and orchestrates coordination work.

### 8.2 Agent Skills / Tools

The agent must be equipped with the following skills (ADK tools). Each skill is a callable function the agent can invoke:

#### Communication Skills
- `send_whatsapp_message(jid, message)` — Send a message to a WhatsApp group or individual
- `create_whatsapp_group(name, member_jids)` — Create a new WhatsApp group and add members
- `add_member_to_group(group_jid, member_jid)` — Add a member to an existing group
- `broadcast_message(member_jids, message)` — Send the same message to multiple individuals

#### Task Management Skills
- `create_task(event_id, title, description, assignee_uids, due_date)` — Create a task in Firestore
- `update_task_status(task_id, status)` — Update a task's status
- `list_tasks(event_id, status_filter)` — List tasks for an event
- `assign_task(task_id, assignee_uids)` — Assign or reassign a task

#### Member Directory Skills
- `lookup_member(name_or_phone)` — Find a member by name or phone number
- `list_members(role_filter)` — List org members, optionally filtered by role
- `get_member_whatsapp_jid(uid)` — Resolve a Firebase UID to a WhatsApp JID

#### Event Skills
- `get_event_details(event_id)` — Fetch event metadata
- `update_event_status(event_id, status)` — Update an event's status
- `list_upcoming_events()` — List all upcoming events for the org

#### Document Skills
- `create_document_stub(event_id, title, type)` — Register a document placeholder in Firestore
- `link_document(event_id, doc_id, url)` — Link an external document (Google Drive, etc.) to an event
- `list_documents(event_id)` — List all documents for an event

#### Outreach Skills
- `draft_outreach_message(context, recipient_type)` — Generate a draft message for sponsor/speaker outreach
- `log_outreach_attempt(event_id, recipient, channel, status)` — Log an outreach attempt (replaces the spreadsheet workflow)

### 8.3 Agent Trigger Conditions

The agent activates when:
1. A message is sent in a registered WhatsApp group
2. A message is sent directly to the Fello WhatsApp number
3. A user sends a message in the web dashboard chatbot

### 8.4 Demo Strategy

For the competition demo, implement a **hardcoded fallback** for the ADK agent layer. If the agent fails or is slow, the demo can switch to a scripted response path that demonstrates the same coordination flow. End the demo on a **quantified automation count** (e.g., "Fello just automated 7 coordination actions that would have taken 45 minutes manually").

### 8.5 Agent Context Window

Every agent invocation must include:
```typescript
{
  org_id: string,
  event_id: string | null,
  conversation_history: Message[],   // Last N messages from the WhatsApp group
  member_directory: Member[],        // All members for this org (for name resolution)
  active_tasks: Task[],              // Current tasks for context
  trigger_message: Message,          // The message that triggered this invocation
}
```

---

## 9. Dashboard Chatbot (Primary UI)

The web dashboard at `/org/[orgId]` is **chatbot-first**. The primary interface is a chat window where users interact with the same AI agent as in WhatsApp, but with a richer UI.

### 9.1 Chatbot UI Requirements

- Chat input at the bottom, conversation history scrolling upward
- Agent responses can include **structured cards** (not just text):
  - Task cards (with status badge, assignee avatar, due date)
  - Member cards (avatar, name, role, phone)
  - Event summary cards
  - Document link cards
- Quick action buttons below agent responses (e.g., "Assign this task", "Create WhatsApp group", "Send to all members")
- The chatbot must feel like a coordinator's assistant, not a generic AI chat

### 9.2 Sidebar Navigation

Current sidebar sections (from `app-sidebar.tsx`):
- Main nav (`nav-main.tsx`)
- Projects/Events (`nav-projects.tsx`)
- Secondary nav (`nav-secondary.tsx`)
- User profile (`nav-user.tsx`)

The sidebar must show:
- Organization name at the top
- Active events list (linkable to `/org/[orgId]/events/[eventId]`)
- Links to Members, Settings
- User profile with sign-out option at the bottom

---

## 10. Missing Routes — What to Build Next

These routes exist in `FELLO_FLOW.md` but are not yet scaffolded. Build them in this order:

### Priority 1: Events Dashboard (`/org/[orgId]/events`)
- List of all events for the org
- Status badges (planning, active, completed, cancelled)
- Create new event button → modal or inline form
- Each event card links to the event detail page

### Priority 2: Event Detail (`/org/[orgId]/events/[eventId]`)
Sub-tabs within the event:
- **Overview** — event metadata, status, date, coordinators
- **Tasks** — task list with status filters, create task, assign task
- **Members / Teams** — which members are assigned to this event
- **WhatsApp Groups** — list of groups for this event, create group button
- **Documents** — linked documents, upload stubs
- **Outreach Log** — sponsor/speaker outreach tracking

### Priority 3: Members (`/org/[orgId]/members`)
- Full member directory table
- Role badge (admin, member, viewer)
- Phone number (WhatsApp)
- Invite new member (by phone number)
- Change role action

### Priority 4: Settings (`/org/[orgId]/settings`)
- Organization name, slug
- WhatsApp number configuration
- Danger zone: delete org

---

## 11. Features Cut — Do Not Re-Add

These features were explicitly scoped out. Do not suggest or implement them:

- Color palette generator
- Internet scraping for investors or sponsors
- Volunteer coordination add-on (separate from the core event coordination flow)
- Encrypted raw WhatsApp message storage (use case didn't justify complexity)
- Reverse-message WhatsApp OTP flow (replaced by standard OTP)

---

## 12. Organization Onboarding Flow

### New Organization (`/org/new`)
1. The `/org/new` page is a chatbot interface (no form fields).
2. User talks to Fello, who collects everything through conversation:
   - Organization name.
   - Logo URL (from URL scrape suggestion or manual input).
   - Url Namespace selection/confirmation: If user's domain does not exist in the `institutions` collection, Fello suggests a namespace (e.g. `sliit` for `my.sliit.lk`), checks its global availability in Firestore, and lets the user confirm or customize it. If the domain is already registered, Fello uses the existing URL namespace.
   - Org type detection.
3. Once confirmed, Fello writes the institution, organization, membership, and user updates to Firestore and redirects.
4. Redirect to setup (WhatsApp number assignment).

### Join Organization (`/org/join`)
1. Enter invite code or org slug
2. Verify membership eligibility
3. Add user as member → set member custom claim
4. Redirect to org dashboard

### User Setup (`/setup`)
1. WhatsApp OTP verification
2. Display name entry
3. Redirect to org selector or specific org

---

## 13. Waitlist Page (`/waitlist`)

Already partially implemented. Has:
- `ShareButton.tsx`
- `UserProfile.tsx`
- Loading states

The waitlist is for users who sign up before their org is on Fello. Capture phone number and email. Do not implement waitlist backend beyond Firestore write — no email sending for now.

---

## 14. Error Handling Conventions

- Use `try/catch` around all Firebase calls
- Display errors using the shadcn `alert` component with `variant="destructive"`
- Never expose raw Firebase error codes to the user — map them to friendly messages
- Loading states must use the shadcn `skeleton` component (not spinners)

---

## 15. TypeScript Conventions

- Strict mode enabled (`tsconfig.json`)
- No `any` types — use proper interfaces
- All Firestore document shapes must have a corresponding TypeScript interface in `lib/types.ts` (create this file if it doesn't exist)
- Server actions must be typed with proper return types using `{ data, error }` pattern:
```typescript
type ActionResult<T> = { data: T; error: null } | { data: null; error: string };
```

---

## 16. Environment Variables

```env
# Firebase
NEXT_PUBLIC_FIREBASE_API_KEY=
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NEXT_PUBLIC_FIREBASE_PROJECT_ID=
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
NEXT_PUBLIC_FIREBASE_APP_ID=

# Firebase Admin (server only)
FIREBASE_ADMIN_PROJECT_ID=
FIREBASE_ADMIN_CLIENT_EMAIL=
FIREBASE_ADMIN_PRIVATE_KEY=

# Cloud SQL / PostgreSQL
DATABASE_URL=

# Baileys VM
BAILEYS_API_URL=
BAILEYS_API_SECRET=

# Google ADK
GOOGLE_ADK_API_KEY=
GOOGLE_CLOUD_PROJECT=
```

Never commit `.env.local`. The `.env.example` file should list all keys with empty values.

---

## 17. Competition Context

- Competition: Google Cloud-focused, centered on community well-being
- Submission deadline is tight — prioritize working demo over completeness
- Demo narrative: PTI (Parents-Teachers Interaction) event coordination
- Pitch deck opens with a human research moment: a coordinator making a large volume of manual outreach calls, before introducing the technology
- Security differentiation (tenant isolation, org-owned data) is a genuine moat — lead with it in the pitch, not as a footnote
- Post-competition goal: validate the enterprise version with actual budget-holders

---

## 18. Commands Reference

```bash
# Install dependencies
pnpm install

# Init shadcn (first time only)
pnpm dlx shadcn@latest init --preset b1VlIttI --template next

# Add a shadcn component
pnpm dlx shadcn@latest add <component-name>

# Dev server
pnpm dev

# Build
pnpm build

# Type check
pnpm tsc --noEmit
```

---

## 19. What to Do When Stuck

1. Re-read this file (`CLAUDE.md`) before asking anything
2. Re-read `FELLO_CONTEXT.md` for product reasoning
3. Check the reference repo: `https://github.com/kavinduUdhara/uni-log-kavindu`
4. If a UI pattern isn't clear from the reference repo, ask before implementing — do not guess
5. If a feature seems like a good idea to add, do not add it without explicit instruction — scope creep is the primary risk
