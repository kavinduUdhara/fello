# FELLO_CONTEXT.md — Full Product Context & Decision Log

This document captures the full product reasoning, user research, architecture decisions, and deliberate tradeoffs made during the Fello design phase. Claude Code should read this alongside `CLAUDE.md` before working on any feature. The *why* behind every decision is here — knowing it prevents well-intentioned mistakes.

---

## 1. The Problem (Validated)

Kavindu discovered this problem personally while coordinating events as an IEEE student branch member in Sri Lanka. It was validated through user research with **six individuals** from IEEE branches and university clubs.

### Validated Pain Points (in order of severity)

1. **Manual WhatsApp group creation per event** — Every event requires creating new groups, adding all the right people, naming them correctly. This is done manually every single time because there is no encoded record of who was in what group for a previous event.

2. **Exhausting follow-up work** — Coordinators manually chase people for task updates, document submissions, and confirmations. No automated reminders, no visibility into who hasn't responded.

3. **Sponsor and speaker outreach across spreadsheets** — Outreach is tracked in large shared spreadsheets. Multiple coordinators edit the same sheet, causing conflicts. No history of who said what to whom.

4. **Lost tasks with no visibility** — Tasks assigned verbally in WhatsApp groups have no persistence. There's no way to see what's pending without scrolling through hundreds of messages.

5. **Documents bouncing between teams causing missed deadlines** — Event documents (budgets, schedules, proposals) are emailed between people rather than having a single source of truth. People edit stale versions.

6. **Files scattered across personal drives and email** — No organizational document repository. When someone leaves, their files go with them.

### The Root Cause

Organizational structure exists nowhere in encoded form. Every event starts from zero. Fello's job is to encode that structure once and automate the reconstruction work every subsequent time.

---

## 2. The Product Vision

An AI agent that:
- Lives inside WhatsApp groups (where the work already happens)
- Listens to conversations and extracts actionable items automatically
- Orchestrates coordination work without requiring coordinators to change their behavior
- Provides a web dashboard (chatbot-first) as the primary control surface for administrators

**Fello sits on top of WhatsApp, not beside it.** Volunteers continue using WhatsApp exactly as they do today. The agent attends every conversation and does the coordination work that currently falls on humans.

---

## 3. Security Differentiation — The Real Moat

Most WhatsApp AI agent products store all messages and data centrally. This is a showstopper for most organizations that care about privacy:
- Student orgs don't want their internal communications on a third-party's server
- Professional bodies have obligations around member data
- Any org that handles sensitive member information (health orgs, legal aid clinics, etc.) cannot use centralized solutions

Fello's answer: **tenant-isolated architecture where organizations own their data.**

- Each organization's data (messages, tasks, documents, member info) is completely isolated
- No cross-tenant data access is possible by design (enforced at Firestore security rules and PostgreSQL RLS level)
- Organizations can delete all their data at any time
- The Fello platform processes data but does not own it

This is not a footnote — it is the primary reason organizations can adopt Fello when they cannot adopt competitors. Lead with this in the pitch.

---

## 4. What Fello Is NOT

These were considered and deliberately excluded:

### Not a WhatsApp replacement
Fello does not ask volunteers to install a new app, use a new chat interface, or change how they communicate. The agent attends their existing WhatsApp groups. The web dashboard is for administrators and coordinators only.

### Not a general project management tool
Fello is purpose-built for event/project coordination within volunteer organizations. It is not Trello, Asana, or Notion. It does not have boards, sprints, or roadmaps. Every feature must be grounded in the specific coordination workflows of student orgs and civic groups.

### Not a CRM
The outreach log feature is minimal — enough to replace the shared spreadsheet, not to become a full CRM. No lead scoring, pipeline stages, or sales-oriented features.

### Not an enterprise SaaS (yet)
The immediate target is student organizations and university clubs. The underlying infrastructure (tenant isolation, org-owned data) is an enterprise-grade pattern, but the product UX is designed for volunteers, not paid employees. Post-competition, the enterprise version will be validated with budget-holders separately.

---

## 5. Architecture Decisions & Rationale

### 5.1 Firebase Auth with JWT Custom Claims

**Decision:** Bake `{ tenantId, orgs: { [orgId]: { access, nodeId, capabilities } } }` into JWT custom claims at sign-in time.

**Why:** Every permission check in the app needs to know which org the user belongs to and what role/capabilities they have. Fetching this from Firestore on every request adds latency and costs reads. JWT claims are free to verify — the Firebase SDK does it locally. Zero-database-read permission checks was the explicit goal.

**Implication:** When a user's role changes, their token must be refreshed (force token refresh on next request). Handle this in `use-auth.ts`.

### 5.2 WhatsApp OTP vs Reverse-Message Flow

**Decision:** WhatsApp OTP (user receives an OTP message, enters it in the web UI).

**Considered:** Reverse-message flow (user sends a specific message to a Fello number to verify their phone).

**Why OTP won:** Lower friction. The reverse-message flow requires the user to know which number to message, compose a specific message, and wait. OTP is a familiar pattern (like SMS OTP) that users understand immediately. The implementation complexity is comparable.

**Do not revisit this decision.**

### 5.3 Baileys on GCE vs Cloud Run

**Decision:** GCE VM for Baileys.

**Why:** Baileys maintains a persistent WebSocket connection to WhatsApp's servers. Cloud Run instances are ephemeral — they spin down when idle, killing the connection. A persistent WhatsApp session cannot run on Cloud Run. GCE gives a long-lived VM where the session stays alive. Railway is a valid alternative if GCE management becomes a burden.

### 5.4 One WhatsApp Number Per Event

**Decision:** Each event gets its own dedicated WhatsApp number (Baileys session).

**Considered:** One number per organization, with the agent disambiguating events by context.

**Why per-event won:** Clear context separation. When the agent receives a message, it knows immediately which event it's for without having to parse context. Members also benefit — they know which group belongs to which event. Reduces the risk of agent confusion across concurrent events.

### 5.5 Firestore + PostgreSQL (Not One or the Other)

**Decision:** Firestore for org structure and real-time data; PostgreSQL for WhatsApp messages and full-text search.

**Why not Firestore for everything:** Firestore is not designed for full-text search or complex relational queries. WhatsApp message history needs both. The agent needs to search across message history to answer questions like "what did we decide about the venue?" — this requires proper FTS.

**Why not PostgreSQL for everything:** Firestore's real-time listeners are critical for the dashboard UI. Task updates, event status changes, and member activity should update instantly in the web UI. Firestore does this out of the box. Building real-time infrastructure on PostgreSQL would be a significant distraction.

### 5.6 Encrypted Raw Message Storage — Removed

**Decision:** Do not encrypt raw WhatsApp messages in PostgreSQL.

**Why removed:** The use case didn't justify the complexity. Tenant isolation via RLS already prevents cross-tenant access. Full-at-rest encryption would require key management infrastructure (KMS, key rotation, etc.) that is out of scope for the competition timeline. Revisit post-competition if enterprise customers require it.

---

## 6. User Story Map (Jeff Patton Methodology)

The user story map was built using Jeff Patton's methodology: backbone (user activities) → walking skeleton (key tasks) → stories (specific actions).

### Backbone (User Activities)

1. **Onboard** — Create or join an organization
2. **Plan an Event** — Create an event, assign coordinators, set up structure
3. **Coordinate** — Manage tasks, communication, documents during the event
4. **Execute** — Day-of coordination, real-time updates, issue resolution
5. **Close** — Archive the event, document learnings, offboard

### Walking Skeleton (Minimum Viable Stories per Activity)

**Onboard:**
- As a founder, I can create a new organization and become its admin
- As a volunteer, I can join an organization with an invite code
- As any user, I can verify my WhatsApp number during setup

**Plan an Event:**
- As an admin, I can create an event with a name, date, and description
- As an admin, I can assign coordinators to an event
- As a coordinator, I can create WhatsApp groups for the event from the dashboard
- As a coordinator, I can add members to the event's WhatsApp groups by selecting from the member directory

**Coordinate:**
- As a coordinator, I can see all tasks for an event and their status
- As the agent, I can detect action items from WhatsApp messages and create tasks automatically
- As the agent, I can send follow-up reminders to assignees whose tasks are overdue
- As a coordinator, I can log outreach attempts (sponsor/speaker) without a spreadsheet
- As a coordinator, I can link documents to an event

**Execute:**
- As a coordinator, I can ask the dashboard chatbot "what's pending?" and get a live summary
- As the agent, I can answer questions from WhatsApp group members about event logistics

**Close:**
- As an admin, I can mark an event as complete
- As an admin, I can archive the event's WhatsApp groups

---

## 7. Demo Script (PTI Event Flow)

The competition demo centers on a PTI (Parents-Teachers Interaction) event at a university. This is the narrative:

**Scene 1: The Problem**
Open with a coordinator manually making phone calls or sending individual WhatsApp messages to 30 committee members. Show the pain — the time, the repetition, the lack of visibility.

**Scene 2: Fello in Action**
1. Admin opens Fello dashboard for the PTI event
2. Types in chatbot: "Set up the coordination structure for PTI 2025"
3. Agent responds: creates 3 WhatsApp groups (Organizing Committee, Logistics, Registration) and adds all relevant members automatically
4. Shows the groups appear instantly on participants' phones
5. Admin types: "What tasks are still pending?"
6. Agent responds with a structured task list with owners and due dates
7. Admin types: "Remind everyone with overdue tasks"
8. Agent sends personalized reminders to each person via WhatsApp

**Scene 3: The Payoff**
End screen: "Fello automated 7 coordination actions in 2 minutes that would have taken a coordinator 45 minutes manually."

**Fallback:** If the ADK agent is slow or unresponsive during the live demo, a hardcoded response path is pre-loaded that runs the same script with scripted agent responses. The judge cannot tell the difference.

---

## 8. Pitch Deck Structure

1. **Opening — Human Moment:** A PTI coordinator making 30 manual WhatsApp messages one by one. No voiceover needed — the image speaks for itself. Caption: "This is how Sri Lanka's 200,000+ university volunteers coordinate events today."

2. **The Problem:** Organizational structure is never encoded. Every event starts from zero. [The 6 validated pain points, briefly]

3. **Why Now:** WhatsApp is where the work already happens. AI agents can now attend those conversations. Tenant-isolated infrastructure is now feasible for student budgets (Google Cloud credits).

4. **The Solution:** Fello — an AI coordination agent that lives in your WhatsApp groups.

5. **How It Works:** [Short product demo or screenshots of the 3-step demo flow]

6. **The Security Differentiator:** Your data never leaves your organization's tenant. [1 slide on tenant isolation, presented as a trust feature, not a technical footnote]

7. **Traction / Validation:** 6 user research interviews. [Names of IEEE branches / orgs interviewed]

8. **The Ask / Vision:** Competition submission. Post-competition: enterprise validation. The same infrastructure that works for a student org works for a national NGO.

---

## 9. Features Explicitly Cut (With Reasons)

| Feature | Why Cut |
|---|---|
| Color palette generator | Scope creep — no user research supporting this |
| Internet scraping for investors/sponsors | Out of scope for student org use case; legal complexity |
| Volunteer coordination add-on | Too broad; the event coordination flow is already the volunteer use case |
| Encrypted raw message storage | KMS complexity not justified by current use case |
| Reverse-message WhatsApp OTP | Higher friction than standard OTP |
| Trello/Asana-style boards | Over-engineering; task list is sufficient |
| Real-time collaboration on documents | Out of scope; link documents, don't host them |
| Email notifications | WhatsApp is the channel; don't split notification surface |

**Do not re-propose any of these features.** If a user brings them up in a future conversation, explain the reasoning above and move on.

---

## 10. Post-Competition Roadmap (Do Not Build Now)

These are validated future directions, not current scope:

1. **Enterprise tier:** Same tenant-isolated infrastructure, sold to NGOs, professional associations, and civic bodies with actual budgets. Validate with budget-holders post-competition.

2. **Multi-language agent:** The agent currently operates in English. Sri Lankan orgs communicate in Sinhala and Tamil. Multi-language support is a significant opportunity.

3. **Document hosting:** Instead of linking external documents, Fello could host them within the tenant. Requires storage infrastructure.

4. **Analytics dashboard:** Event completion rates, volunteer engagement metrics, task completion velocity. Useful for org leadership, not for the demo.

5. **Integration with Google Workspace:** Auto-create Drive folders per event, sync documents bidirectionally.

---

## 11. Key Principles for Development

1. **If it's not in the user stories, don't build it.** Every feature must trace back to a validated pain point.

2. **WhatsApp first.** When a feature could live in the web UI or in WhatsApp, prefer the WhatsApp surface. That's where volunteers already are.

3. **The agent is the product.** The web dashboard is a control surface for the agent, not an independent application. Every UI decision should serve the agent's coordination work.

4. **Security is not optional.** Tenant isolation must be enforced at every layer — Firestore rules, PostgreSQL RLS, API middleware. A data leak between tenants would be a fatal product failure.

5. **Demo first, polish second.** The competition deadline is the priority. Build the PTI demo flow to production quality. Everything else can be rough.

6. **Kavindu makes architecture decisions.** Claude Code assists in implementation. Do not propose architectural changes without being asked. If something seems wrong, flag it clearly once — then implement what is instructed.
