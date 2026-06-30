# Fello — Google Drive Folder Scoping and WhatsApp Group Authentication

## Part A — Google Drive Folder Scoping

### The problem this solves

If Fello has unrestricted access to a connected Google account's entire Drive, two things get worse at once. Complexity goes up because the system has to reason about an unbounded, unstructured set of files it knows nothing about. Security gets worse because a single OAuth grant now exposes everything in that Drive, not just what's relevant to the organization — far more surface area than necessary, and a much bigger liability if anything goes wrong.

The fix is to never let Fello operate against "the whole Drive." Fello only ever operates inside one specific root folder that the org explicitly designates, and everything created or indexed lives inside that folder's tree.

### The connection flow

When an admin connects Google Drive during org setup, after the OAuth consent screen completes, Fello asks a direct question before doing anything else:

```
"Do you already have a folder where your organization's 
files are kept, or are your files scattered across your Drive?"

Option A: "I have one folder" 
  -> admin picks the existing folder from a folder browser
  -> that folder becomes the designated root

Option B: "My files are scattered" 
  -> Fello creates a brand new folder, e.g. "Fello - SLIIT IEEE"
  -> that new folder becomes the designated root
  -> optionally: Fello can scan the existing scattered files the 
    user points it to and organize copies or references into 
    the new structure, but the original scattered locations are 
    never treated as ongoing data sources
```

Either way, the result is the same: exactly one root folder ID gets stored on the org document, and that is the only folder Fello will ever read from or write to from that point forward.

```typescript
// organizations/{internalId}
{
  // ...existing fields
  driveRootFolderId: "1BxiM7k2x9...",   // the ONE designated folder
  driveConnectedBy: "uid_abc123",
  driveConnectedAt: Timestamp
}
```

### Why this is non-negotiable, not just a default

Once `driveRootFolderId` is set, every Drive API call Fello makes — listing files, creating subfolders, uploading WhatsApp attachments, indexing documents — must include that folder ID as a hard scope, never a Drive-wide search or listing. This is enforced at the code level, not just as a UI convention:

```typescript
// WRONG - searches the entire connected Drive
const files = await drive.files.list({ q: `name contains 'logo'` });

// RIGHT - always scoped to the org's designated root
const files = await drive.files.list({
  q: `'${org.driveRootFolderId}' in parents and name contains 'logo'`,
});
```

If a future feature needs to touch anything outside that root folder, that is a deliberate, separate, explicitly-approved action — never the default behavior of any existing tool.

### The subfolder structure inside the root

Once the root is designated, Fello creates and maintains a consistent structure underneath it, scoped per event:

```
[Designated Root Folder]/
  [Event Name]/
    whatsapp-documents/     <- all files arriving via WhatsApp land here
    design-team/
    publicity-team/
    logistics/
    finance/
    speakers/
    general/
```

This structure was already defined in the core architecture. The addition here is that the entire structure lives under the one designated root — never anywhere else in the connected Drive — and the `documents` table in Cloud SQL only ever indexes files that live inside that root folder's tree. A file existing elsewhere in the connected Drive, even if technically accessible by the OAuth scope, is never indexed, never searchable, and never surfaced by the agent.

### Security and complexity benefits, stated plainly

Reduced blast radius — if anything goes wrong with the integration, the damage is contained to one folder tree the org explicitly designated, not their entire Drive.

Reduced reasoning surface — the AI agent never has to disambiguate between "files relevant to Fello" and "files that happen to exist in this Drive." Everything it can see is, by definition, relevant.

Clear mental model for the org admin — "Fello only touches this one folder" is something a non-technical chair or secretary can understand and verify themselves by just looking at that folder in their own Drive.

Trust building — when Fello eventually pitches itself to organizations who are wary of giving broad data access (this is the exact objection Chathumina raised), "we only ever touch one folder you choose, never your whole Drive" is a concrete, verifiable answer rather than an abstract security claim.

---

## Part B — WhatsApp Group Authentication

### The core principle

A WhatsApp number connected to Fello is a gateway, not a general-purpose inbox. The agent must behave completely differently depending on where a message arrives from, and it must never treat "this number received a message" as equivalent to "Fello should process or store this message."

There are exactly three categories of WhatsApp conversation the connected number can be part of, and they are handled in three completely different ways.

### Category 1 — Personal direct messages to the connected number

If someone sends a direct message to the WhatsApp number Fello is using as a gateway — not in any group, just a 1:1 chat with that number — Fello does nothing.

- No response is sent
- No message content is stored anywhere, not even temporarily
- No processing pipeline runs on it at all
- The message is received by Baileys, identified as a non-group direct message, and immediately discarded before it reaches any storage or any agent logic

This applies regardless of who sends it or what it says. The connected number is not a personal assistant number and must never behave like one. This is a hard rule enforced at the gateway layer on the GCE VM, before the message ever reaches Cloud Run.

```typescript
// On the Baileys gateway, before anything else happens
function shouldProcessMessage(message: WAMessage): boolean {
  if (!message.key.remoteJid?.endsWith('@g.us')) {
    // Not a group message - it's a personal DM to the gateway number
    return false; // discard immediately, no storage, no response
  }
  // continue to group authentication check below
}
```

### Category 2 — Group messages where the group is NOT yet authenticated

A group existing and having the Fello number as a member does not automatically mean Fello trusts that group or processes its messages. Until a group passes the authentication flow described below, any message arriving from it is also discarded — not stored, not responded to, not processed by any agent. This prevents someone from simply adding the Fello number to a random WhatsApp group and having it start listening, creating data, or responding.

### Category 3 — Group messages where the group IS authenticated

Only once a group has been explicitly authenticated through one of the two flows below does Fello begin storing its messages, running the extraction pipeline, and allowing the agent to respond and take actions in that group.

### How a group becomes authenticated — two paths

The authentication requirement depends entirely on who created the WhatsApp group, because the two situations carry different inherent trust levels.

**Path 1 — Fello created the group itself**

When an admin tells the chatbot or the agent to set up a project/event and have Fello create the WhatsApp groups (the standard flow already designed — Fello creates the design team group, publicity group, etc. and adds the right members), no additional OTP verification step is required. Fello created the group, Fello knows exactly which org and which project it belongs to, and Fello added every member to it deliberately based on the org's membership records. The group is authenticated by construction — there is no ambiguity to resolve.

```typescript
// whatsapp_groups/{internalId}
{
  orgId: "org_8f3k2a9x",
  tenantId: "my.sliit.lk",
  eventId: "evt_9k2m3x1a",
  jid: "120363xxx@g.us",
  name: "PTI Design Team",
  type: "design",
  createdByFello: true,           // group origin
  authenticated: true,            // authenticated automatically, by construction
  authenticatedAt: Timestamp,
  authenticationMethod: "created_by_fello"
}
```

**Path 2 — The organization already had the group and adds Fello to it**

This is the case where an org says "we already created our 8 WhatsApp groups, we just want Fello to join and start working inside them." Here, Fello has no inherent knowledge of what this group is or whether it genuinely belongs to the organization claiming it — anyone could add the Fello number to any group and claim it belongs to their org. This requires explicit verification before any processing begins.

The verification flow:

```
1. Admin tells Fello (via dashboard or WhatsApp): 
   "I've added you to our existing design team group, 
   please authenticate it for the PTI project"

2. Fello generates a one-time 6-digit code, scoped to 
   that specific group + project combination

3. Fello sends a direct message INTO that group:
   "To confirm this group belongs to PTI 2026 for SLIIT IEEE IAS, 
   please have an admin reply with this code: 847291"

4. Someone in the group sends "847291" as a message in that group

5. Fello verifies:
   - the code matches and hasn't expired (10 minute window)
   - the sender has a verified Fello account
   - the sender has admin or coordinator access on that org
   - (if all pass) the group is marked authenticated for that 
    specific project

6. Only after this succeeds does Fello begin storing messages 
   from that group and responding to requests in it
```

```typescript
// whatsapp_groups/{internalId}
{
  orgId: "org_8f3k2a9x",
  tenantId: "my.sliit.lk",
  eventId: "evt_9k2m3x1a",
  jid: "120363xxx@g.us",
  name: "PTI Design Team (existing)",
  type: "design",
  createdByFello: false,          // group origin - pre-existing
  authenticated: false,            // starts unauthenticated, must verify
  authenticationMethod: "otp_verification",
  authenticationCode: "847291",
  authenticationExpiresAt: Timestamp,
  authenticatedBy: null,           // set once verified
  authenticatedAt: null
}
```

This must be repeated separately for every individual pre-existing group the org wants Fello to work inside. If an org has 8 existing groups and wants Fello in all of them, that's 8 separate OTP verifications — one per group — because each group needs its own independent confirmation that it genuinely belongs to the claimed org and project. There is no way to bulk-authenticate multiple groups with one code, since that would reintroduce the exact ambiguity this flow exists to prevent.

### Authorization level inside a group — same JWT model as the web app

Once a group is authenticated, Fello does not treat every message inside it as equally privileged. The agent attributes every message to the sender's verified WhatsApp number, which is linked to their Firebase account (via the WhatsApp OTP verification flow already in the auth design), which carries the exact same access level and capabilities that user has in the web dashboard.

This means the authorization check for any action requested via WhatsApp uses the identical JWT custom claims structure already defined for the web app — there is no separate, weaker permission system for WhatsApp:

```typescript
// When the agent processes a message and considers taking an action
async function canTakeAction(
  senderWhatsAppNumber: string, 
  orgId: string, 
  requiredCapability: string
): Promise<boolean> {

  // Resolve the WhatsApp number to a verified Firebase user
  const user = await getUserByVerifiedWhatsApp(senderWhatsAppNumber);
  if (!user) return false; // unverified number, no identity, no action

  // Pull their custom claims - the SAME claims used on the web app
  const claims = await getCustomClaims(user.uid);
  const orgAccess = claims.orgs?.[orgId];
  if (!orgAccess) return false; // not a member of this org at all

  return orgAccess.capabilities?.includes(requiredCapability) ?? false;
}
```

A practical example: if a general member (not a team lead, not an admin) asks the agent in a WhatsApp group to "delete the PTI event," the agent checks their capabilities exactly as it would for a dashboard request, sees they lack `events.manage`, and declines — same outcome as if they'd tried that action on the web app. Someone whose WhatsApp number was never linked to a verified Firebase account at all cannot trigger any state-changing action regardless of what they type, because there is no identity to check capabilities against.

### What happens for messages from people without a verified WhatsApp link

Inside an authenticated group, some senders may not have completed the WhatsApp OTP verification linking their number to a Fello account — for example, a guest, a new member who hasn't signed up yet, or someone added to the group before completing onboarding.

For these senders:
- Their messages can still be stored (the group itself is authenticated, so message storage applies to everyone in it) for context purposes
- The agent can still read and use their messages as conversational context when reasoning about the group's activity
- But the agent cannot attribute any task, any assignment, or any state-changing action to them, because there is no verified identity to check permissions against
- If their message looks like it's trying to trigger an action ("assign this to me," "mark this done"), the agent should respond asking them to verify their WhatsApp number first, rather than silently ignoring them or silently acting on their behalf

### Summary of the full authentication model

```
Message arrives at gateway number
  |
  +- Is it a direct/personal message (not in a group)?
  |    +- YES -> discard immediately, no storage, no response, no exceptions
  |
  +- Is it in a group?
       |
       +- Is the group authenticated?
       |    |
       |    +- NO -> discard, do not store, do not respond
       |    |
       |    +- YES -> proceed to process the message
       |              |
       |              +- Was the sender's WhatsApp number 
       |              |   verified and linked to a Fello account?
       |              |     |
       |              |     +- NO -> can be used as context only, 
       |              |     |        cannot trigger actions, agent 
       |              |     |        asks them to verify if they 
       |              |     |        attempt an action
       |              |     |
       |              |     +- YES -> check their JWT capabilities 
       |              |              for the requested action, same 
       |              |              rules as the web dashboard
       |              |
       |              +- Continue with normal Stage 1 / Stage 2 
       |                 filter pipeline and Gemini extraction as 
       |                 already defined elsewhere in the architecture

How a group becomes authenticated:
  |
  +- Created by Fello itself -> authenticated automatically, no OTP needed
  |
  +- Pre-existing group, Fello added afterward -> requires one OTP 
     verification per individual group, sent into that group, 
     confirmed by a sender with verified admin/coordinator access
```
