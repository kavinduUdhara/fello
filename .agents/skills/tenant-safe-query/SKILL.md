---
name: tenant-safe-query
description: Write a Firestore query or server action that is guaranteed to be tenant-safe. Use whenever writing any code that reads from or writes to Firestore. Auto-invokes when writing Firestore queries, server actions, or any database access code.
allowed-tools: Read Grep
---

## Tenant isolation is non-negotiable

Every Firestore query must be scoped to `orgId`. A query without an `orgId` filter is a data breach.

## Pattern for client-side queries (React hooks / real-time listeners)

```typescript
// CORRECT — always filter by orgId
const q = query(
  collection(db, 'organizations', orgId, 'events'),
  where('status', '==', 'active'),
  orderBy('date', 'desc')
);

// WRONG — missing orgId scope
const q = query(collection(db, 'events'), where('status', '==', 'active'));
```

## Pattern for server actions (Admin SDK)

```typescript
// CORRECT
const snapshot = await adminDb
  .collection('organizations')
  .doc(orgId)
  .collection('events')
  .get();

// WRONG
const snapshot = await adminDb.collection('events').get();
```

## Before writing any query, answer these three questions:
1. Is this query scoped to `organizations/{orgId}/...`? If not, fix it.
2. Does the calling code validate that the user's JWT claim `orgId` matches the `orgId` being queried?
3. Is the Firestore security rule for this collection in `firestore.rules`?

## Check current security rules coverage:
!`cat firestore.rules 2>/dev/null | grep -A3 "match /" | head -60 || echo "firestore.rules not found — create it"`
