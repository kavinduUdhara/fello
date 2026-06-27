# Fello — Product Flow & User Story Map

## URL Structure
- `fello.lk` — landing page, static, Firebase Hosting
- `app.fello.lk` — the full product, Google Cloud App Hosting

---

## Routing Structure

```
app.fello.lk/
  /                          → org selector (bare layout)
  /sign-in                   → sign in page (bare layout)
  /setup                     → WhatsApp OTP verification (bare layout)
  /org/join                  → find and join or create an org (bare layout)
  /org/new                   → create a new org (bare layout)
  /org/[orgId]               → org home — CHATBOT (full app layout)
  /org/[orgId]/events        → all events and projects
  /org/[orgId]/events/[id]   → specific event dashboard
  /org/[orgId]/members       → member management
  /org/[orgId]/settings      → org settings
```

---

## Two Layout Templates

### Layout A — Bare
No sidebar. No navigation. No header. Centered content only. One job per page.

Used by:
- `/sign-in`
- `/` — org selector
- `/setup` — WhatsApp verification
- `/org/join`
- `/org/new`

### Layout B — Full App
Full sidebar with navigation, org switcher in sidebar header, user menu. Based on `sidebar-08` shadcn block, modified to match the pattern in https://github.com/kavinduUdhara/uni-log-kavindu/

Used by:
- `/org/[orgId]` and all routes underneath it

---

## Next.js App Router File Structure

```
app/
  layout.tsx                     ← root layout, just html+body, nothing else
  (bare)/
    layout.tsx                   ← bare layout, centered, no nav
    page.tsx                     ← org selector /
    sign-in/
      page.tsx
    setup/
      page.tsx
    org/
      join/
        page.tsx
      new/
        page.tsx
  org/
    [orgId]/
      layout.tsx                 ← full app layout with sidebar
      page.tsx                   ← org home — chatbot
      events/
        page.tsx
        [eventId]/
          page.tsx
      members/
        page.tsx
      settings/
        page.tsx
```

Route groups with parentheses `(bare)` share the bare layout without affecting the URL. `/` stays `/` not `/bare`.

---

## Redirect Logic

```
User hits app.fello.lk
  → signed out
      → redirect to /sign-in

  → signed in, has lastOpenedOrg in Firestore
      → redirect to /org/[lastOpenedOrgId]

  → signed in, no lastOpenedOrg
      → redirect to /

  → signed in, lands on /
      → show org selector

  → signed in, hits /org/[id] they don't have access to
      → redirect to /

  → signed in, on /org/[orgId], no WhatsApp verified yet
      → show WhatsApp verification banner (skippable)
      → if not skipped → /setup → return to /org/[orgId]
```

`lastOpenedOrg` is stored on the user's Firestore document — persists across devices. User switches from phone to laptop and still lands in the right org.

---

## Monorepo Structure

```
fello/
  apps/
    landing/         ← fello.lk — Firebase Hosting (static Next.js export)
    app/             ← app.fello.lk — Google Cloud App Hosting (full Next.js)
  packages/
    ui/              ← shared shadcn components used by both apps
    firebase/        ← shared Firebase config, auth hooks, cookie logic
```

Use `pnpm workspaces` to manage the monorepo.

---

## Shared Firebase Auth Across Subdomains

Firebase Auth session is shared between `fello.lk` and `app.fello.lk` via a cookie set on the root domain `.fello.lk`.

- User signs in on `app.fello.lk`
- ID token written to cookie with `domain: '.fello.lk'`
- Cookie accessible to all subdomains including `fello.lk`
- Landing page reads cookie, verifies token via Cloud Run backend
- **Signed in** → show user photo, name, "Go to app" button
- **Signed out** → show sign in button, marketing copy, waitlist

Add both `fello.lk` and `app.fello.lk` to authorized domains in Firebase Auth console.

Cookie settings: `domain: '.fello.lk'`, `secure: true`, `sameSite: 'strict'`, `expires: 7`

All shared auth logic lives in `packages/firebase`.

---

## The Big Picture

Fello is an AI-powered organization management platform. It encodes organizational structure once and lets AI handle the repetitive coordination work. WhatsApp is not replaced — the AI agent lives inside existing WhatsApp groups, listens, understands context, and orchestrates everything in the background.

Two surfaces:
1. **Dashboard** — `app.fello.lk` — where admins manage org structure, events, tasks, members, and interact with the AI via chatbot
2. **WhatsApp** — where day-to-day coordination happens, AI agent lives here

---

## Backbone Activities (Left to Right)

```
Sign In → Enter Org → Setup Org → Make Event/Project → Run Event → Track Progress → Close Event
```

---

## Activity 1 — Sign In

**URL**: `app.fello.lk/sign-in`
**Layout**: Bare
**shadcn block**: `login-05`

User lands on sign in page. Two options:
- Sign in with Google
- Sign in with Microsoft

After sign in, system checks the email domain.

### Domain check outcomes:

**Unknown domain (Institutional):**
- Firebase Auth session is KEPT ACTIVE (low-level session).
- Add to waitlist (counts uniquely per user via `waitlist_users` collection).
- Redirect to `/waitlist?domain=xxx`
- The `/waitlist` page uses the active session to display their Google/Microsoft profile picture and name.
- Displays a leaderboard of the top 5 requested domains using the Firebase REST API to prevent Next.js Server Action hanging.
- The root org selector (`/`) strictly checks allowed domains and redirects restricted users back to `/waitlist`.

**Unknown domain (Personal email like gmail.com):**
- Sign out immediately.
- Add to waitlist under the "general" bucket.
- Display an inline error on the login page prompting them to use a school or company email.

**Known domain (google.com or institution domain like sliit.lk):**
- Proceed to org entry
- Note: domain restriction is in code but NOT enforced during competition demo — all sign ins go through

---

## Activity 2 — Enter Org (Org Selector)

**URL**: `app.fello.lk/`
**Layout**: Bare

Shown only if user has no `lastOpenedOrg`. Otherwise redirected straight to `/org/[lastOpenedOrgId]`.

### Four possible states:

**No orgs exist for this user:**
- Show "Create an organization" and "Join an existing organization" options
- Goes to `/org/new` or `/org/join`

**Orgs exist, user hasn't joined any:**
- Show search — find org by name
- Fill request form
- Admin accepts or denies
- If accepted → `/org/[orgId]`

**Already a member of one org:**
- Don't force selection — show their one org
- "Join another" button with plus icon → `/org/join`
- Auto-redirect to `/org/[orgId]` after brief moment

**Already a member of multiple orgs:**
- Show all org cards
- User taps one → remembered as `lastOpenedOrg` in Firestore → redirect to `/org/[orgId]`
- "Join another" plus button always visible

**Claim ownership:**
- Option to claim an existing org
- Submit claim with proof
- Pending manual review
- Dead end for now

---

## Activity 3 — Setup Org

Appears only for newly created organizations. Existing orgs skip straight to `/org/[orgId]`.

### Step 1 — Verify WhatsApp number

**URL**: `app.fello.lk/setup`
**Layout**: Bare

Every user must verify their personal WhatsApp number. Can be skipped but nudged on every session until done.

- Enter personal WhatsApp number
- Fello sends 6-digit OTP via Baileys gateway
- User receives OTP in WhatsApp
- User enters OTP on Fello
- Number linked to Firebase account
- JWT custom claims updated
- Links WhatsApp identity to Fello profile — messages in event groups attributed to real name and role

### Step 2 — Org verification (admin only)

**URL**: `/org/[orgId]/settings/verify`

- "Get verified" button on dashboard
- Collect: picture of student ID + public URL of executive committee post
- Status shows "Verification pending"
- Manual review offline
- Verified badge unlocks higher automation limits
- Dead end for competition — button and form exist, no automated review

### Step 3 — Connect Google account (admin only)

OAuth consent flow → Fello gets Drive access

Ask: "Do you already have org files in Google Drive?"
- **One folder**: go through all files, index into Cloud SQL documents table
- **Scattered**: go through all files, organize into folders, index while organizing
- **No files**: Fello creates fresh root org folder structure

### Step 4 — Connect WhatsApp as org gateway (admin only)

- Connect a dedicated WhatsApp number for the org (not personal)
- Backend initiates Baileys session on GCE VM
- QR code fetched from backend, displayed on frontend
- Admin scans QR with dedicated number
- Session established and verified

### Step 5 — Add new members (admin only)

Two ways:
- **File drop**: Drop CSV or spreadsheet. AI reads file, extracts names, emails, WhatsApp numbers, roles. Admin reviews and confirms. Fello creates placeholder accounts, sends WhatsApp invites.
- **Chatbot**: Describe members in plain English — "add Kavindu as IAS design team lead." AI extracts details, admin confirms, invite sent via WhatsApp.

Members receive invite, sign in with Google or Microsoft, verify WhatsApp OTP, see pre-configured workspace.

---

## Activity 4 — Make New Event or Project

**URL**: `/org/[orgId]/events/new`
**Layout**: Full app

Anyone in excom or with given permission can create.

Type flag:
- `type: event` → public, has registration form, delegates, public date
- `type: project` → internal only, no registration

### Path A — Dashboard creation

1. Name, type, date or deadline
2. Logo — upload or create task for design team
3. Add team members and roles for this event
4. Add tasks with deadlines and assign members
5. Connect Google Drive — optional
   - Use org account → subfolder inside org root Drive
   - Connect separate Google account → isolated Drive for this event
   - Event members only see their event folder
   - Folder structure created:
     ```
     [Event Name]/
       whatsapp-documents/   ← ALL WhatsApp files land here
       design-team/
       publicity-team/
       logistics/
       finance/
       speakers/
       general/
     ```
6. Connect WhatsApp for this event — optional
   - Separate dedicated number per event
   - QR code from backend, scan with dedicated number
   - Fello creates all team WhatsApp groups automatically
   - Agent joins all groups

### Path B — WhatsApp driven creation

Trigger: excom member drops a message in org-level WhatsApp group.

Example:
```
IAS Chair:    "we gonna start a new event called PTI"
Agent:        "Created PTI. Do you have a logo or shall we create one?"
Chair:        "let's create one"
Agent:        "When do you need it by?"
Chair:        "next Friday"
Agent:        [creates task, sends to design team group]
              "Hey team, PTI needs a logo by Friday. Anyone available?"
Designer:     "I can do it"
Agent:        "Can you deliver by Friday or do you need more time?"
Designer:     "I need Saturday"
Agent:        "The chair set Friday. Can you do Friday evening?"
Designer:     "okay Friday evening works"
Agent:        [assigns task, sets deadline, notifies chair]
```

Everything reflected in dashboard automatically. Drive folders and WhatsApp groups created only after respective accounts are connected.

---

## Activity 5 — Org Home (Chatbot)

**URL**: `/org/[orgId]`
**Layout**: Full app with sidebar

The home page of every org is a chatbot. This is the primary interaction surface for the dashboard. Not a traditional dashboard with widgets and charts — a conversational AI that knows everything about the org.

### What the chatbot can do:

**Queries:**
- "What's blocking PTI right now?"
- "Who hasn't responded to the sponsorship outreach?"
- "Are we on track for the deadline?"
- "What happened in the design group today?"
- "Find the latest logo file"
- "Show me all overdue tasks"
- "What's the status of all active events?"

**Actions:**
- "Create a new event called Annual Sessions"
- "Assign the poster task to the design team lead"
- "Send a reminder to everyone with overdue tasks"
- "Close PTI and generate the summary"
- "Add Kavindu as design team lead for IAS"

**Insights:**
- "Which team has the most overdue tasks?"
- "How did our last event perform compared to this one?"
- "Who are the top contributors this month?"

The chatbot has full context of the org — structure, all active events, all tasks, all members, recent WhatsApp activity summaries.

---

## Activity 6 — Run Event

**URL**: `/org/[orgId]/events/[eventId]`
**Layout**: Full app

### Public event — volunteer and delegate onboarding:

- Registration form auto-generated by Fello
- Form confirmation includes WhatsApp group invite link
- Delegate joins group from the link
- Wait 30-60 minutes — check if joined
- If not joined → send personal WhatsApp message with link
- Agent sends ONE welcome message when group opens — not per person
- Individual confirmation sent privately

### Task management during event:

**Via dashboard or chatbot:**
- Create, assign, update tasks
- Mark complete
- View all statuses

**Via WhatsApp:**
- "done" in group → agent marks task complete
- "I'm stuck" → agent flags blocked, notifies team lead
- File uploaded to group → saved to Drive `whatsapp-documents/`, indexed in Cloud SQL, agent confirms in group
- "send the brief" → agent searches documents table, fetches from Drive, sends to group

### Outreach tracking:
- Add contacts to outreach tracker
- Agent monitors response status
- Auto-reminder when no response after set days
- Status: contacted / responded / confirmed / declined

---

## Activity 7 — Track Progress

**URL**: `/org/[orgId]/events/[eventId]/progress` or via chatbot on `/org/[orgId]`

### Via chatbot (primary):
Ask anything in natural language. Agent queries Firestore and Cloud SQL, returns real answers.

### Via dashboard:
- All tasks and statuses
- Overdue tasks highlighted
- Workload distribution across members
- Outreach pipeline status

### Excom visibility without being in every group:
Excom are NOT in every event WhatsApp group. They ask the chatbot:
- "What's happening in the PTI design group?"
- Agent queries Cloud SQL message history
- Returns summary
- Full visibility without presence

### Automated alerts:
- Task overdue → agent notifies assignee in team group
- Document not uploaded before deadline → agent flags
- Sponsor not responded after 3 days → surfaces in tracker
- Event date approaching → countdown reminders

---

## Activity 8 — Close Event

Triggered by:
- Admin clicks "Close event" on dashboard
- Event date passes — Cloud Scheduler checks daily
- Chair tells agent in WhatsApp: "close PTI"

### Close flow:
1. Gemini generates full event summary
2. Summary stored in Firestore `event_summaries`:
   - Narrative summary
   - Tasks completed vs missed
   - Top contributors
   - Per-group summaries
   - Key decisions
   - Blockers
   - Lessons learned
3. All WhatsApp messages deleted from Cloud SQL
4. Drive access restricted to read-only
5. Event status set to closed
6. Summary available for future planning via chatbot

---

## User-Defined Automations

At any point, members can request custom automations via the chatbot.

1. Member describes in plain English
2. Gemini generates automation config
3. Stored as "pending approval"
4. Admin notified, reviews plain English description
5. Admin approves or rejects
6. If approved → runs automatically

No pre-built templates. Fully AI generated, admin approved.

---

## WhatsApp Message Processing Pipeline

```
Message arrives at GCE VM (Baileys)
  ↓
Stage 1 filter — on VM, free
  Drop: under 5 chars, "ok/thanks/👍/noted/lol", sent by bot, short media captions
  ~60-70% dropped here
  ↓
Store raw message in Cloud SQL whatsapp_messages
  (all messages passing Stage 1 are stored)
  ↓
Stage 2 filter — Cloud Run keyword check
  Intent signals: done/finished/blocked/stuck/help/send/share/file/
  document/deadline/due/when/?/i can do/assign/yes/no
  ↓
If intent signal → Gemini extraction
  Pass message + event context
  Extract: task update, document request, question, deadline, confirmation
  Write to message_events table
  Trigger automations
  ↓
If file attached
  Download from WhatsApp
  Upload to Drive whatsapp-documents/ folder
  Index in Cloud SQL documents table
  Agent confirms in group: "Saved to Drive."
```

---

## Google Drive Folder Structure

```
[Org Root or Separate Event Drive]/
  [Event Name]/
    whatsapp-documents/     ← ALL WhatsApp files land here regardless of source group
    design-team/
    publicity-team/
    logistics/
    finance/
    speakers/
    general/
```

Every file indexed in Cloud SQL `documents` table:
- `org_id`, `event_id`, `team_node_id`
- `file_name`, `mime_type`, `drive_file_id`
- `source`: whatsapp / drive_direct / form / generated
- `group_jid` — which WhatsApp group it came from
- `message_id` — links back to the WhatsApp message
- Full text search vector on filename via GIN index

---

## User Types

| User Type | Dashboard | WhatsApp | Creates Events | Sees All Groups |
|---|---|---|---|---|
| Org admin | Full | Full | Yes | Yes via chatbot |
| Branch chair | Full read across branch | Full | Yes | Yes via chatbot |
| Sub-branch chair | Full within sub-branch | Full within sub-branch | Yes | Yes via chatbot |
| Team lead | Their team only | Their team group | No | No |
| Team member | Their tasks only | Their team group | No | No |
| Event volunteer | Their tasks only | Volunteer group only | No | No |
| Event delegate | Announcements only | Delegate group only | No | No |

---

## Security Model

Three layers of tenant isolation:

1. **JWT custom claims** — org IDs and capabilities baked into token. Computed once at sign in. Zero database reads on subsequent requests.

2. **Firestore security rules** — database-level enforcement. Cross-org requests rejected at database, not just hidden in UI.

3. **Query-level scoping** — every Firestore and Cloud SQL query always includes `org_id` as filter. Cross-org data structurally impossible to fetch.

WhatsApp messages only accessible via Cloud Run Admin SDK. Firestore rule: `allow read: if false` on `whatsapp_messages` collection.

Hierarchy access: branch chair reads all sub-branches via ancestor array. Access flows downward only.

---

## Competition Demo Flow (The PTI Story)

Exact sequence for competition video:

1. Vice chair types in IEEE IAS WhatsApp group: *"guys we have a new event called PTI, need a logo"*
2. Agent creates PTI event in Firestore
3. Agent: *"Created PTI. Shall we design a logo?"*
4. Chair: *"yes, by next Friday"*
5. Agent creates task, sends to design team: *"PTI needs a logo by Friday. Anyone available?"*
6. Designer: *"I can do it"*
7. Agent assigns task, negotiates deadline, confirms
8. Designer: *"logo is done"*
9. Agent marks complete, notifies chair
10. Agent: *"Want me to create a volunteer registration form?"*
11. Chair: *"yes"*
12. Form created automatically
13. Agent: *"Want me to set up interview slots on Google Calendar?"*
14. Calendar slots created
15. Volunteer interview WhatsApp group created
16. Agent sends reminders to registered volunteers
17. Chair asks on dashboard chatbot: *"what's the status of PTI?"*
18. Agent responds with full real-time summary

---

## Now vs Later

### Competition demo — build these:
- Sign in with Google and Microsoft
- Org selector page
- Org creation via chatbot
- WhatsApp OTP verification
- Connect Google account and Drive
- Connect WhatsApp gateway via QR
- Add members via file drop and AI
- Create event via dashboard and WhatsApp
- Task creation and assignment via WhatsApp conversation
- Auto WhatsApp group creation
- File upload to Drive from WhatsApp with indexing
- Natural language queries via dashboard chatbot
- Registration form auto-generation
- Google Calendar slot booking
- Event summary on close
- Shared auth cookie across fello.lk and app.fello.lk

### Later:
- Org verification automated review
- Claim ownership flow
- Waitlist processing
- User-defined automations
- Cross-event pattern analysis
- Scattered Drive files organization
- Social media posting
- Finance tracking
- Full analytics beyond chatbot

