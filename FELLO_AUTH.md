# Fello — Authentication & Authorization

## Overview

Fello uses Firebase Auth for identity and a custom claims system for authorization. The core principle is: **compute everything once at sign in, bake it into the JWT token, and never hit the database again for permission checks.**

Two separate but linked identities per user:
1. **Google or Microsoft OAuth** — who you are, dashboard access
2. **WhatsApp OTP** — links your personal WhatsApp number to your Fello account so messages you send in event groups are attributed to your real name and role

---

## Sign In Flow

### Step 1 — OAuth sign in
User signs in with Google or Microsoft on `app.fello.lk/sign-in`.

Firebase Auth handles the OAuth flow and returns:
- `uid` — unique Firebase user ID
- `email` — their email address
- `displayName` — their full name
- `photoURL` — their profile photo
- `emailVerified` — whether email is verified

### Step 2 — Tenant check & Resolution (Server Action)
After Firebase Auth resolves on the client, immediately call a Server Action to resolve or register the tenant.
The tenant ID is the full email domain exactly as it comes from OAuth (e.g. `kavindu@my.sliit.lk` belongs to tenant `my.sliit.lk`).

```
tenant ID is unknown/not registered
  → add to waitlist in Firestore (waitlist/{email})
  → redirect to waitlist page
  → stop here

tenant ID is registered
  → continue to Step 3
```

Note: waitlist check is bypassed during the competition demo. All sign ins proceed.

### Step 3 — Create or update user document
Server Action writes to Firestore `users` collection:

```
users/{uid}
  uid: "uid_abc123"
  email: "kavindu@my.sliit.lk"
  tenantId: "my.sliit.lk"        // derived from email domain on sign in
  name: "Kavindu Udhara"
  photo: "https://..."
  whatsappNumber: "+94771234567" | null
  whatsappVerified: false
  lastOpenedOrg: "org_8f3k2a9x" | null  // stored as internal UUID, persists across devices
  createdAt: Timestamp
  claimsVersion: 3
```

### Step 4 — Build and bake custom claims (Server Action)
This is the most important step. A Server Action using Firebase Admin SDK:

1. Queries all membership documents for this user: `memberships/{userId}_{internalOrgId}`
2. For each direct membership, computes all descendant org nodes they can access via ancestor array inheritance (queries flat `organizations` where `ancestors` contains `orgId`)
3. Builds a complete access map using internal UUIDs for organization IDs
4. Writes it into the JWT as custom claims via `admin.auth().setCustomUserClaims(uid, claims)`
5. Forces a token refresh on the client so the new claims take effect immediately

```javascript
firebase.auth().currentUser.getIdToken(true)
```

### Step 5 — Redirect based on state
```
user has lastOpenedOrg (internal UUID) in Firestore
  → resolve its tenantId & compute tenantNamespace (domain dots to hyphens)
  → redirect to /org/[tenantNamespace]/[orgSlug] (e.g. /org/my-sliit-lk/ieee)

user has memberships but no lastOpenedOrg
  → redirect to / (org selector)

user has no memberships
  → redirect to /org/new or /org/join
```

---

## Custom Claims Structure

Claims are baked into the JWT token at sign in. Every subsequent request carries this token — zero database reads needed for permission checks.

```typescript
{
  tenantId: "my.sliit.lk",        // full email domain
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

---

## How Claims Are Built at Sign In

This runs as a Server Action using Firebase Admin SDK. Never runs on the client.

```
For each direct membership document of this user (memberships/{userId}_{orgId}):

  1. Get their direct org access and capabilities.
  
  2. Find all descendant org nodes via ancestors array
     → query organizations where ancestors array contains this orgId
     → these are all orgs below this user in the hierarchy

  3. Add each descendant as readonly inherited access
     → access: 'readonly', via: directOrgId, capabilities: []

  4. Repeat for all direct memberships.

  5. Merge everything into one claims object.

  6. Write to JWT via setCustomUserClaims.

  7. Force token refresh on client.
```

Access inheritance checks are simple array lookups on internal UUIDs.

---

## Access Levels

Five tiers:

| Level | What it means |
|---|---|
| `full` | Org admin — sees everything, can edit structure, manage members, full control |
| `coordinator` | Chair, secretary — sees all teams and events, manages tasks and documents |
| `team` | Team lead and members — sees their specific team node only |
| `readonly` | Inherited from parent org — can see but not edit |
| `event_only` | External volunteers and delegates — one event only, no dashboard |

---

## Capability System

Access level controls what you can see. Capabilities control what functions you can use. They are stored in the membership document and baked into the JWT.

When an admin describes a role via chatbot — "our secretary also manages Instagram" — Fello appends `social.post` and `social.manage` to their capabilities. The membership document updates, claims rebuild, token refreshes.

### Base capability sets by role:

```typescript
const ROLE_CAPABILITIES = {
  chair: [
    'drive.read', 'drive.write',
    'whatsapp.send', 'whatsapp.manage',
    'members.manage', 'tasks.manage',
    'events.manage', 'analytics.view',
    'finance.view', 'finance.manage'
  ],
  secretary: [
    'drive.read', 'drive.write',
    'whatsapp.send', 'tasks.manage',
    'members.manage'
  ],
  design_lead: [
    'drive.read', 'drive.write',
    'whatsapp.send', 'tasks.manage'
  ]
}
```

---

## Firestore Security Rules

Rules check the JWT token only — zero document reads for permission checks. Flat collection paths are secured using `orgId` and `tenantId`.

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // Check if user has access to this org
    // Works for both direct membership and inherited access via ancestor array
    function canAccess(orgId) {
      return orgId in request.auth.token.orgs;
    }

    // Get access level for this org from token
    function getAccess(orgId) {
      return request.auth.token.orgs[orgId].access;
    }

    // Check specific capability from token
    function hasCapability(orgId, capability) {
      return capability in request.auth.token.orgs[orgId].capabilities;
    }

    // Check if user can write — not readonly or event_only
    function canWrite(orgId) {
      return canAccess(orgId)
        && getAccess(orgId) != 'readonly'
        && getAccess(orgId) != 'event_only';
    }

    // Check tenant boundary — user's tenant must match document's tenant
    function sameTenant(tenantId) {
      return request.auth.token.tenantId == tenantId;
    }

    // Institutions — readable by anyone in that tenant
    match /institutions/{domain} {
      allow read: if request.auth.token.tenantId == domain;
      allow write: if false; // only backend writes institutions
    }

    // Organizations — readable if user has access via token
    match /organizations/{orgId} {
      allow read: if canAccess(orgId)
        && sameTenant(resource.data.tenantId);
      allow write: if canAccess(orgId)
        && getAccess(orgId) == 'full'
        && sameTenant(resource.data.tenantId);
    }

    // Org nodes — same as organizations
    match /org_nodes/{nodeId} {
      allow read: if canAccess(resource.data.orgId)
        && sameTenant(resource.data.tenantId);
      allow write: if canAccess(resource.data.orgId)
        && getAccess(resource.data.orgId) == 'full'
        && sameTenant(resource.data.tenantId);
    }

    // Memberships — readable by org members
    match /memberships/{membershipId} {
      allow read: if canAccess(resource.data.orgId)
        && sameTenant(resource.data.tenantId);
      allow write: if canAccess(resource.data.orgId)
        && getAccess(resource.data.orgId) == 'full'
        && sameTenant(resource.data.tenantId);
    }

    // Users — users can read and write their own document only
    match /users/{userId} {
      allow read: if request.auth.uid == userId;
      allow write: if request.auth.uid == userId;
    }

    // Events — readable by org members, writable by coordinators and above
    match /events/{eventId} {
      allow read: if canAccess(resource.data.orgId)
        && sameTenant(resource.data.tenantId);
      allow write: if canWrite(resource.data.orgId)
        && sameTenant(resource.data.tenantId);
    }

    // Tasks — readable and writable by org members
    match /tasks/{taskId} {
      allow read: if canAccess(resource.data.orgId)
        && sameTenant(resource.data.tenantId);
      allow write: if canWrite(resource.data.orgId)
        && sameTenant(resource.data.tenantId);
    }

    // Outreach — requires finance capability
    match /outreach/{outreachId} {
      allow read: if canAccess(resource.data.orgId)
        && sameTenant(resource.data.tenantId)
        && hasCapability(resource.data.orgId, 'finance.view');
      allow write: if canWrite(resource.data.orgId)
        && sameTenant(resource.data.tenantId)
        && hasCapability(resource.data.orgId, 'finance.manage');
    }

    // Automations — readable by members, writable by full access only
    match /automations/{automationId} {
      allow read: if canAccess(resource.data.orgId)
        && sameTenant(resource.data.tenantId);
      allow write: if canAccess(resource.data.orgId)
        && getAccess(resource.data.orgId) == 'full'
        && sameTenant(resource.data.tenantId);
    }

    // Event summaries — readable by org members, never writable from client
    match /event_summaries/{summaryId} {
      allow read: if canAccess(resource.data.orgId)
        && sameTenant(resource.data.tenantId);
      allow write: if false; // backend only
    }

    // WhatsApp groups — readable by org members
    match /whatsapp_groups/{groupId} {
      allow read: if canAccess(resource.data.orgId)
        && sameTenant(resource.data.tenantId);
      allow write: if false; // backend only
    }

    // OTP verifications — never readable from client
    match /otp_verifications/{number} {
      allow read: if false;
      allow write: if false; // backend only
    }

    // Waitlist — never readable from client
    match /waitlist/{email} {
      allow read: if false;
      allow write: if false; // backend only
    }
  }
}
```

---

## WhatsApp OTP Verification

Every user must verify their personal WhatsApp number. This links their WhatsApp identity to their Fello account.

### Flow:

1. User enters their personal WhatsApp number on `/setup`
2. Server Action generates a 6-digit OTP
3. OTP stored in Firestore `otp_verifications/{whatsappNumber}` with 10 minute expiry
4. Baileys gateway sends OTP to that number: "Your Fello verification code is: 847291. Expires in 10 minutes."
5. User receives OTP in WhatsApp
6. User enters OTP back on Fello
7. Server Action verifies: correct OTP, not expired, not already used
8. WhatsApp number linked to Firebase user account
9. Firestore user document updated: `whatsappNumber`, `whatsappVerified: true`
10. Custom claims rebuilt with `whatsappVerified: true`
11. Token refreshed

---

## Multiple Org Context Switching

A user can belong to multiple orgs. Their JWT claims contain all of them (keyed by internal UUID).

On first login → `/` org selector → user picks one → stored as `lastOpenedOrg` on Firestore user document → computes namespace and slug, redirects to `/org/[tenantNamespace]/[slug]`.

### URL per context:
Instead of exposing internal UUIDs like `org_8f3k2a9x` in the URL, Fello uses deterministic tenant-namespace/slug URL resolution:
```
app.fello.lk/org/my-sliit-lk/ieee          → IEEE Student Branch of my.sliit.lk
app.fello.lk/org/nsbm-ac-lk/ieee           → IEEE Student Branch of nsbm.ac.lk
```

Resolving URL slug to internal ID is done in a Server Action:
```typescript
// Deterministic resolution: tenantNamespace (URL) → tenantId (Firestore) → orgSlug → internal UUID
async function resolveOrgPath(tenantNamespace: string, orgSlug: string): Promise<string | null> {
  // Step 1 — Reverse transformation: replace hyphens back with dots to get tenantId (domain)
  const tenantId = tenantNamespace.toLowerCase().replace(/-/g, '.');

  // Step 2 — resolve org slug within that tenant domain
  const org = await db.collection('organizations')
    .where('tenantId', '==', tenantId)
    .where('slug', '==', orgSlug)
    .where('verified', '==', true)
    .limit(1)
    .get();

  if (org.empty) return null;
  return org.docs[0].id; // internal UUID
}
```

---

## Tenant Isolation — Three Layers

### Layer 1 — JWT token
User's JWT only contains orgs they belong to (internal UUIDs). A request from an unauthorized tenant fails token checks before any database query.

### Layer 2 — Firestore security rules
Firestore security rules enforce same-tenant boundary (`sameTenant`) and membership checks (`canAccess`) on flat root-level collections.

### Layer 3 — Query scoping
Every Firestore query in Server Actions includes `tenantId` and `orgId` as filters:
```typescript
const tasks = await db.collection('tasks')
  .where('tenantId', '==', tenantId)
  .where('orgId', '==', currentOrgId)
  .where('eventId', '==', eventId)
  .get();
```
