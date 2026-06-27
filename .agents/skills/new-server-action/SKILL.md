---
name: new-server-action
description: Write a new Next.js server action for the Fello backend. Use when creating any server-side function — auth actions, Firestore writes, Baileys VM calls, or ADK agent calls.
allowed-tools: Read Grep
---

## Server action template

Every server action must follow this pattern exactly:

```typescript
'use server';

import { adminAuth, adminDb } from '@/lib/firebase-admin';
import type { ActionResult } from '@/lib/types';

export async function myAction(
  param: string,
  orgId: string  // Always receive orgId explicitly — never trust client state
): Promise<ActionResult<ReturnType>> {
  try {
    // 1. Validate inputs
    if (!param || !orgId) {
      return { data: null, error: 'Missing required fields' };
    }

    // 2. Verify orgId matches caller's JWT claim
    // (This is done at the API route level — in server actions called from
    //  authenticated pages, the orgId comes from the session token, not user input)

    // 3. Perform the operation
    const result = await adminDb
      .collection('organizations')
      .doc(orgId)
      .collection('...')
      .add({ ... });

    return { data: { id: result.id }, error: null };

  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error';
    console.error(`[myAction] ${message}`);
    // Return friendly message — never expose raw Firebase errors
    return { data: null, error: 'Something went wrong. Please try again.' };
  }
}
```

## After writing a server action:
1. Check it uses `ActionResult<T>` return type from `lib/types.ts`
2. Check it has a try/catch
3. Check it never returns raw Firebase error codes to the client
4. Run: !`pnpm tsc --noEmit 2>&1 | tail -10`
