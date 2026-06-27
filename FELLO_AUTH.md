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

### Step 2 — Domain check (Server Action)
After Firebase Auth resolves on the client, immediately call a Server Action to check the email domain.

```
email domain is unknown
  → add to waitlist in Firestore
  → redirect to waitlist page
  → stop here

email domain is known (google.com, sliit.lk, iit.ac.lk etc.)
  → continue to Step 3
```

Note: domain restriction is in code but NOT enforced during competition demo. All sign ins proceed.

### Step 3 — Create or update user document
Server Action writes to Firestore `users` collection:

```
users/{uid}
  name: displayName
  email: email
  photo: photoURL
  domain: email domain
  whatsappNumber: null (until verified)
  whatsappVerified: false
  lastOpenedOrg: null (until they select one)
  createdAt: timestamp
```

### Step 4 — Build and bake custom claims (Server Action)
This is the most important step. A Server Action using Firebase Admin SDK:

1. Queries all membership documents for this user
2. For each direct membership, computes all descendant org nodes they can access via ancestor array inheritance
3. Builds a complete access map
4. Writes it into the JWT as custom claims via `admin.auth().setCustomUserClaims(uid, claims)`
5. Forces a token refresh on the client so the new claims take effect immediately

```
firebase.auth().currentUser.getIdToken(true)
```

### Step 5 — Redirect based on state
```
user has lastOpenedOrg in Firestore
  → redirect to /org/[lastOpenedOrgId]

user has memberships but no lastOpenedOrg
  → redirect to / (org selector)

user has no memberships
  → redirect to /org/new or /org/join
```

---

## Custom Claims Structure

Claims are baked into the JWT token at sign in. Every subsequent request carries this token — no database reads needed for permission checks.

```typescript
{
  orgs: {
    'sliit-ieee': {
      access: 'full',
      nodeId: 'branch-root',
      capabilities: [
        'gmail.read', 'gmail.send',
        'drive.read', 'drive.write',
        'whatsapp.send', 'whatsapp.manage',
        'members.view', 'members.manage',
        'tasks.manage', 'events.manage',
        'analytics.view', 'finance.view',
        'forms.create', 'calendar.manage'
      ]
    },
    'sliit-ieee-ias': {
      access: 'readonly',
      nodeId: 'ias-root',
      via: 'sliit-ieee',           // inherited from parent
      capabilities: []              // readonly inherited access has no capabilities
    },
    'sliit-ieee-ras': {
      access: 'readonly',
      nodeId: 'ras-root',
      via: 'sliit-ieee',
      capabilities: []
    }
  },
  events: {
    'pti-2026': {
      access: 'event_only',
      orgId: 'sliit-ieee-ias'
    }
  },
  whatsappVerified: true,
  claimsVersion: 3                  // increments when claims are rebuilt
}
```

---

## How Claims Are Built at Sign In

This runs as a Server Action using Firebase Admin SDK. Never runs on the client.

```
For each direct membership document of this user:

  1. Get their direct org access and capabilities
     → stored in memberships/{userId}_{orgId}

  2. Find all descendant org nodes via ancestor array
     → query organizations where ancestors array contains this orgId
     → these are all orgs below this user in the hierarchy

  3. Add each descendant as readonly inherited access
     → access: 'readonly', via: directOrgId, capabilities: []

  4. Repeat for all direct memberships

  5. Merge everything into one claims object

  6. Write to JWT via setCustomUserClaims

  7. Force token refresh on client
```

Example: branch chair of `sliit-ieee` automatically gets readonly access to `sliit-ieee-ias`, `sliit-ieee-ras`, `sliit-ieee-wie` etc. because those orgs have `sliit-ieee` in their ancestors array. This happens automatically — no separate membership document needed for each sub-branch.

IAS chair only gets their direct IAS access. They cannot see branch level or sibling sub-branches.

---

## Access Levels

Four tiers — not hardcoded roles:

| Level | What it means |
|---|---|
| `full` | Org admin — sees everything, can edit structure, manage members, full control |
| `coordinator` | Chair, secretary — sees all teams and events, manages tasks and documents |
| `team` | Team lead and members — sees their specific team node only |
| `readonly` | Inherited from parent org — can see but not edit |
| `event_only` | External volunteers and delegates — one event only, no dashboard |

---

## Capability System

Access level controls what you can see. Capabilities control what functions you can use.

Capabilities are stored in the membership document and baked into the JWT. They are not hardcoded to roles — they are dynamic and appendable.

When an admin describes a role via chatbot — "our secretary also manages Instagram" — Fello appends `social.post` and `social.manage` to their capabilities. The membership document updates, claims rebuild, token refreshes.

### Base capability sets by role:

```typescript
const ROLE_CAPABILITIES = {
  chair: [
    'gmail.read', 'gmail.send',
    'drive.read', 'drive.write',
    'whatsapp.send', 'whatsapp.manage',
    'members.view', 'members.manage',
    'tasks.manage', 'events.manage',
    'analytics.view', 'finance.view',
    'forms.create', 'calendar.manage',
    'social.post'
  ],
  secretary: [
    'gmail.read', 'gmail.send',
    'drive.read', 'drive.write',
    'whatsapp.send',
    'members.view',
    'tasks.manage',
    'forms.create',
    'calendar.view'
  ],
  treasurer: [
    'drive.read', 'drive.write',
    'finance.view', 'finance.manage',
    'members.view',
    'tasks.view'
  ],
  webmaster: [
    'drive.read',
    'social.post', 'social.manage',
    'members.view',
    'tasks.view'
  ],
  design_lead: [
    'drive.read', 'drive.write',
    'whatsapp.send',
    'tasks.manage',
    'forms.view'
  ],
  member: [
    'drive.read',
    'tasks.view',
    'whatsapp.send'
  ],
  volunteer: [
    'tasks.view',
    'whatsapp.send'
  ],
  event_only: [
    'tasks.view'
  ]
}
```

### Checking capabilities in Server Actions:

```typescript
function hasCapability(token: DecodedIdToken, orgId: string, capability: string): boolean {
  return token.orgs?.[orgId]?.capabilities?.includes(capability) ?? false;
}
```

### UI shows or hides features based on capabilities:

```typescript
const capabilities = user.token.orgs[currentOrgId]?.capabilities ?? [];

const canReadGmail = capabilities.includes('gmail.read');
const canManageFinance = capabilities.includes('finance.manage');
const canPostSocial = capabilities.includes('social.post');
```

No hardcoding which role sees what. Just checking the capability list.

---

## When Roles Change

When an admin changes someone's role or appends a capability:

1. Update the membership document in Firestore
2. Rebuild that user's custom claims via Server Action
3. Increment `claimsVersion` on both the user document and the claims
4. The user's next request will have stale claims until they refresh

### Lazy refresh pattern

Don't force sign out when roles change. Instead use a version comparison:

- JWT token has `claimsVersion: 3`
- Org document has `structureVersion: 4`
- On every page load, compare the two
- If they don't match, silently refresh the token in the background
- User never notices — no sign out, no interruption

```typescript
// On app load or page navigation
const tokenClaims = await user.getIdTokenResult();
const org = await getOrgDoc(currentOrgId);

if (tokenClaims.claims.claimsVersion < org.structureVersion) {
  // Silently rebuild claims in background
  await rebuildClaims(user.uid);
  await user.getIdToken(true); // force refresh
}
```

This handles the case where:
- Someone's role changes while they are mid-session
- A new sub-branch is added to the org
- A capability is appended or removed

---

## Firestore Security Rules

Rules check the JWT token only — zero document reads for permission checks.

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {

    // Check if user has any access to this org
    // (direct membership OR inherited via ancestor)
    function canAccess(orgId) {
      return orgId in request.auth.token.orgs;
    }

    // Get access level for this org
    function getAccess(orgId) {
      return request.auth.token.orgs[orgId].access;
    }

    // Check specific capability
    function hasCapability(orgId, capability) {
      return capability in request.auth.token.orgs[orgId].capabilities;
    }

    // Check if user can write (not readonly, not event_only)
    function canWrite(orgId) {
      return canAccess(orgId)
        && getAccess(orgId) != 'readonly'
        && getAccess(orgId) != 'event_only';
    }

    match /organizations/{orgId} {
      allow read: if canAccess(orgId);
      allow write: if canAccess(orgId) && getAccess(orgId) == 'full';
    }

    match /org_nodes/{nodeId} {
      allow read: if canAccess(resource.data.orgId);
      allow write: if canAccess(resource.data.orgId) && getAccess(resource.data.orgId) == 'full';
    }

    match /memberships/{membershipId} {
      allow read: if canAccess(resource.data.orgId);
      allow write: if canAccess(resource.data.orgId) && getAccess(resource.data.orgId) == 'full';
    }

    match /events/{eventId} {
      allow read: if canAccess(resource.data.orgId);
      allow write: if canWrite(resource.data.orgId);
    }

    match /tasks/{taskId} {
      allow read: if canAccess(resource.data.orgId);
      allow write: if canWrite(resource.data.orgId);
    }

    match /outreach/{outreachId} {
      allow read: if canAccess(resource.data.orgId)
        && hasCapability(resource.data.orgId, 'finance.view');
      allow write: if canWrite(resource.data.orgId)
        && hasCapability(resource.data.orgId, 'finance.manage');
    }

    match /automations/{automationId} {
      allow read: if canAccess(resource.data.orgId);
      allow write: if canAccess(resource.data.orgId)
        && getAccess(resource.data.orgId) == 'full';
    }

    match /event_summaries/{summaryId} {
      allow read: if canAccess(resource.data.orgId);
      allow write: if false; // only Cloud Run backend writes summaries
    }

    // WhatsApp messages — never accessible from client
    match /whatsapp_messages/{messageId} {
      allow read: if false;
      allow write: if false;
    }

    // OTP verifications — user can only read their own
    match /otp_verifications/{number} {
      allow read: if false;
      allow write: if false; // only backend writes OTPs
    }
  }
}
```

---

## WhatsApp OTP Verification

Every user must verify their personal WhatsApp number. This links their WhatsApp identity to their Fello account — messages they send in event groups are attributed to their real name and role.

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

### Rate limiting:
- Maximum 3 OTP requests per WhatsApp number per hour
- Prevents abuse and protects Baileys gateway number from being flagged

### Can be skipped:
- User can skip WhatsApp verification
- Shown again every session until verified
- Some features unavailable without verification — agent cannot attribute their WhatsApp messages

---

## Multiple Org Context Switching

A user can belong to multiple orgs. Their JWT claims contain all of them.

On first login → `/` org selector → user picks one → stored as `lastOpenedOrg` on Firestore user document → redirect to `/org/[orgId]`.

`lastOpenedOrg` is stored in Firestore not localStorage — persists across devices. User switches from phone to laptop and lands in the right org automatically.

### Switching orgs:
- Profile menu in sidebar has org switcher
- User selects different org
- `lastOpenedOrg` updated in Firestore
- URL changes to `/org/[newOrgId]`
- No sign out needed — all orgs already in JWT claims

### URL per context:
```
app.fello.lk/org/sliit-ieee          → branch level
app.fello.lk/org/sliit-ieee-ias      → IAS chapter
app.fello.lk/org/sliit-mozilla       → Mozilla club
```

Bookmarkable. Shareable. Browser history works naturally.

---

## Tenant Isolation — Three Layers

### Layer 1 — JWT token
User's JWT only contains orgs they belong to. A request from an IAS member for IEEE RAS data will not have RAS in their token claims. The check fails before any database call.

### Layer 2 — Firestore security rules
Even if someone manipulates the frontend to make a request, the database rejects it. `canAccess(orgId)` checks the JWT token directly. No document reads. Database-level enforcement.

### Layer 3 — Query scoping
Every single Firestore query in Server Actions always includes `orgId` as a filter. Cross-org data is structurally impossible to fetch even if a bug exists in application code.

```typescript
// ALWAYS do this — never query without orgId
const tasks = await db.collection('tasks')
  .where('orgId', '==', currentOrgId)
  .where('eventId', '==', eventId)
  .get();
```

---

## Server Actions vs Cloud Run for Auth

### Use Next.js Server Actions for:
- Domain check after sign in
- Building and writing custom claims
- Creating user document in Firestore
- Checking capabilities before rendering UI
- Lazy token refresh on page load
- WhatsApp OTP generation and verification
- All internal dashboard operations

Server Actions run on the server with Firebase Admin SDK access. Admin credentials never exposed to the client.

### Use Cloud Run API for:
- WhatsApp message receiver from GCE VM
- Apps Script webhook
- Gemini processing pipeline
- Anything called from outside the Next.js app

---

## Membership Document Structure

Document ID pattern: `{userId}_{orgId}` — fast single-document lookups, no queries needed.

```
memberships/{userId}_{orgId}
  userId: string
  orgId: string
  nodeId: string           // which specific node in the org tree
  role: string             // descriptive role name e.g. "design_lead"
  access: string           // full / coordinator / team / readonly / event_only
  capabilities: string[]   // array of permitted function strings
  addedBy: string          // uid of admin who added them
  addedAt: timestamp
```

For event-only members (volunteers, delegates):

```
event_members/{userId}_{eventId}
  userId: string
  eventId: string
  orgId: string
  role: string             // volunteer / delegate
  access: 'event_only'
  capabilities: ['tasks.view']
  addedAt: timestamp
```

---

## Important Rules

- Never expose Firebase Admin SDK credentials to the client
- Never check permissions in client components — always Server Actions or Firestore rules
- Never query Firestore without orgId as a filter
- Never hardcode roles — always use capability arrays
- Always force token refresh after claims change
- Always store lastOpenedOrg in Firestore not localStorage
- Claims have a 1000 byte limit — keep them lean, store only orgId, access, nodeId, capabilities


---

## Multi-Tenant Architecture

Every organization in Fello is a completely isolated tenant. SLIIT IEEE cannot see anything from NSBM IEEE. A user from one tenant cannot access another tenant's data under any circumstances.

### Every org is a node in a tree

The hierarchy is dynamic — not hardcoded. Every organization is stored as a node with a `parentId` and an `ancestors` array. This handles everything from a flat single club to a deep multi-level hierarchy.

```
organizations/
  sliit-ieee/
    parentId: null
    ancestors: []              ← root node, no parents

  sliit-ieee-ias/
    parentId: 'sliit-ieee'
    ancestors: ['sliit-ieee']  ← one level deep

  sliit-mozilla/
    parentId: null
    ancestors: []              ← standalone, no children
```

The `ancestors` array is computed and stored when a node is created. It never changes unless the node is moved. This means access inheritance checks are a simple array lookup — no tree traversal needed at query time.

### Access inheritance flows downward only

If you belong to `sliit-ieee`, you automatically get readonly access to every org that has `sliit-ieee` in its ancestors array. You cannot see sideways — IAS cannot see RAS. You cannot see upward — IAS chair cannot see branch level data.

This is enforced in three places:
1. Claims building at sign in — inherited orgs are baked into the JWT with `access: 'readonly'`
2. Firestore security rules — `canAccess(orgId)` checks token only
3. Query scoping — every query filters by `orgId`

### Adding a new sub-branch

When a new sub-branch is created under `sliit-ieee`:

1. New org node is created with `parentId: 'sliit-ieee'` and `ancestors: ['sliit-ieee']`
2. Org's `structureVersion` increments
3. Next time the branch chair loads the app, lazy refresh detects version mismatch
4. Claims rebuild — new sub-branch appears in their token as readonly
5. They immediately have visibility into the new sub-branch with no manual permission grant

### Standalone organizations

A Mozilla club with no sub-branches is just a root node with `parentId: null` and `ancestors: []`. Same system, flat shape. No sub-branches means no inherited access to compute. Simple and fast.

### Tenant data separation in Firestore

Every document in every collection carries its `orgId` directly. No document exists without an orgId. This means:

- Security rules can check orgId on every document without joins
- Queries always filter by orgId — cross-tenant fetches are structurally impossible
- Deleting a tenant means deleting all documents where `orgId == deletedOrgId`

### Tenant data separation in Cloud SQL

Every row in every table carries `org_id` as a non-nullable column. Every query from the backend always includes `WHERE org_id = $1` where `$1` comes from the verified JWT token — never from the client request body.

```sql
-- ALWAYS like this — org_id from verified token, never from client
SELECT * FROM whatsapp_messages
WHERE org_id = $1        -- from JWT
AND event_id = $2        -- from request
ORDER BY timestamp DESC
LIMIT 50;
```

Client cannot fake the org_id because it comes from the server-side JWT verification, not from anything the client sends.

### What one tenant can never do

- Read another tenant's Firestore documents
- Read another tenant's Cloud SQL rows
- Access another tenant's Google Drive folders
- Send messages to another tenant's WhatsApp groups
- See another tenant's members, events, tasks, or files

This is not just UI-level hiding. It is enforced at the database level, the token level, and the query level simultaneously. All three layers must be bypassed for a cross-tenant access to succeed — which is practically impossible.

