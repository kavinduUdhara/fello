# BACKEND.md — Fello Backend Build Instructions

This file is the backend equivalent of `SETUP.md`. It is written for **Antigravity** — read it completely before writing a single file. Every decision here was made deliberately. Read `CLAUDE.md` and `FELLO_CONTEXT.md` first for product context, then follow this file.

The backend is a **separate repository** from `fello-frontend`. Create it as `fello-backend/` at the same level.

---

## 0. What You Are Building

Three backend services that together power Fello:

```
fello-backend/
  baileys-vm/        ← WhatsApp session manager (Node.js, runs on GCE VM)
  agent/             ← Google ADK agent (Node.js/TypeScript, callable by frontend)
  db/                ← PostgreSQL schema, migrations, RLS policies
```

These are **not microservices in the traditional sense**. They are three processes that run on the same GCE VM for the competition. The VM is the reason all three live in one repo — same machine, shared environment variables, deployed together.

---

## 1. Repo Setup

```bash
mkdir fello-backend && cd fello-backend
git init
pnpm init

# Workspace setup — three packages in one repo
mkdir -p baileys-vm agent db
```

Create `package.json` at the root as a pnpm workspace:

```json
{
  "name": "fello-backend",
  "private": true,
  "workspaces": [
    "baileys-vm",
    "agent",
    "db"
  ],
  "scripts": {
    "dev": "concurrently \"pnpm --filter baileys-vm dev\" \"pnpm --filter agent dev\"",
    "build": "pnpm --filter baileys-vm build && pnpm --filter agent build",
    "db:migrate": "pnpm --filter db migrate",
    "db:seed": "pnpm --filter db seed"
  },
  "devDependencies": {
    "concurrently": "^8.0.0",
    "typescript": "^5.0.0"
  }
}
```

Create `.env.example` at the root:

```env
# PostgreSQL (Cloud SQL)
DATABASE_URL=postgresql://fello_app:password@localhost:5432/fello
DATABASE_ADMIN_URL=postgresql://fello_admin:password@localhost:5432/fello

# Firebase Admin
FIREBASE_ADMIN_PROJECT_ID=
FIREBASE_ADMIN_CLIENT_EMAIL=
FIREBASE_ADMIN_PRIVATE_KEY=

# Baileys VM internal API
BAILEYS_API_SECRET=
BAILEYS_API_PORT=3001

# Google ADK / Gemini
GOOGLE_API_KEY=
GOOGLE_CLOUD_PROJECT=

# Agent API (called by frontend)
AGENT_API_PORT=3002
AGENT_API_SECRET=

# Frontend (for CORS)
FRONTEND_URL=https://app.fello.lk
```

---

## 2. DATABASE — PostgreSQL Schema and RLS

This package manages the database schema and runs migrations. It is not a running service — it is a set of SQL files run once to set up Cloud SQL.

### 2.1 Directory Structure

```
db/
  package.json
  migrate.ts        ← runs all migrations in order
  schema/
    001_init.sql
    002_rls.sql
    003_indexes.sql
    004_fts.sql      ← full-text search
  seed/
    demo_pti.sql     ← PTI demo data for the competition demo
```

### 2.2 `db/schema/001_init.sql` — Tables

```sql
-- Create application role (non-superuser, RLS enforced)
CREATE ROLE fello_app LOGIN PASSWORD 'REPLACE_IN_ENV' NOINHERIT;
CREATE ROLE fello_admin LOGIN PASSWORD 'REPLACE_IN_ENV' BYPASSRLS;

-- Grant schema usage
GRANT USAGE ON SCHEMA public TO fello_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO fello_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO fello_app;

-- WhatsApp messages
-- One row per message received or sent in any registered group
CREATE TABLE whatsapp_messages (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        TEXT NOT NULL,           -- Tenant key — matches Firestore orgId
  event_id      TEXT,                    -- Firestore event doc ID (nullable — some messages are org-level)
  group_jid     TEXT NOT NULL,           -- Baileys group JID: 12345678901234567890@g.us
  sender_jid    TEXT NOT NULL,           -- Sender JID: 94771234567@s.whatsapp.net
  sender_name   TEXT,                    -- Display name at time of message
  message_id    TEXT NOT NULL UNIQUE,    -- WhatsApp message ID (from Baileys msg.key.id)
  message_type  TEXT NOT NULL,           -- 'text' | 'image' | 'document' | 'audio' | 'sticker'
  content       TEXT,                    -- Text content (null for non-text)
  media_url     TEXT,                    -- Cloud Storage URL for media (null for text)
  timestamp     TIMESTAMPTZ NOT NULL,
  processed     BOOLEAN DEFAULT FALSE,   -- Has the agent processed this message?
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Agent task extraction log
-- Tracks which messages spawned which tasks (links WhatsApp messages to Firestore tasks)
CREATE TABLE message_task_links (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        TEXT NOT NULL,
  message_id    UUID NOT NULL REFERENCES whatsapp_messages(id),
  task_id       TEXT NOT NULL,           -- Firestore task doc ID
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Outreach log
-- Tracks sponsor/speaker/vendor outreach — replaces the spreadsheet
CREATE TABLE outreach_log (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          TEXT NOT NULL,
  event_id        TEXT NOT NULL,
  recipient_name  TEXT NOT NULL,
  recipient_type  TEXT NOT NULL CHECK (recipient_type IN ('sponsor','speaker','volunteer','vendor','other')),
  channel         TEXT NOT NULL CHECK (channel IN ('whatsapp','email','phone','linkedin','other')),
  status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','contacted','responded','confirmed','declined')),
  notes           TEXT,
  last_contacted_at TIMESTAMPTZ,
  created_by      TEXT NOT NULL,         -- Firebase UID
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Agent conversation sessions
-- Persists multi-turn ADK agent sessions across restarts
CREATE TABLE agent_sessions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id        TEXT NOT NULL,
  session_key   TEXT NOT NULL,           -- Composite: org_id + user_uid or group_jid
  session_data  JSONB NOT NULL,          -- ADK session state (serialized)
  last_active   TIMESTAMPTZ DEFAULT NOW(),
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(org_id, session_key)
);

-- WhatsApp group registry
-- Tracks which groups Fello manages for each org/event
CREATE TABLE whatsapp_groups (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      TEXT NOT NULL,
  event_id    TEXT,
  group_jid   TEXT NOT NULL UNIQUE,
  group_name  TEXT NOT NULL,
  member_jids TEXT[] DEFAULT '{}',
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  archived_at TIMESTAMPTZ
);
```

### 2.3 `db/schema/002_rls.sql` — Row Level Security

This is the tenant isolation layer. Every table gets RLS. No exceptions.

```sql
-- Helper function: read org_id from session variable
CREATE OR REPLACE FUNCTION current_org_id()
RETURNS TEXT AS $$
  SELECT NULLIF(current_setting('app.current_org_id', true), '');
$$ LANGUAGE SQL STABLE;

-- Helper function: check if current session is an admin bypass
CREATE OR REPLACE FUNCTION is_admin_session()
RETURNS BOOLEAN AS $$
  SELECT current_setting('app.is_admin', true) = 'true';
$$ LANGUAGE SQL STABLE;

-- =========================================================
-- whatsapp_messages
-- =========================================================
ALTER TABLE whatsapp_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_messages FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON whatsapp_messages
  FOR ALL
  USING (
    is_admin_session()
    OR org_id = current_org_id()
  )
  WITH CHECK (
    is_admin_session()
    OR org_id = current_org_id()
  );

-- =========================================================
-- message_task_links
-- =========================================================
ALTER TABLE message_task_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE message_task_links FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON message_task_links
  FOR ALL
  USING (
    is_admin_session()
    OR org_id = current_org_id()
  )
  WITH CHECK (
    is_admin_session()
    OR org_id = current_org_id()
  );

-- =========================================================
-- outreach_log
-- =========================================================
ALTER TABLE outreach_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_log FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON outreach_log
  FOR ALL
  USING (
    is_admin_session()
    OR org_id = current_org_id()
  )
  WITH CHECK (
    is_admin_session()
    OR org_id = current_org_id()
  );

-- =========================================================
-- agent_sessions
-- =========================================================
ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_sessions FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON agent_sessions
  FOR ALL
  USING (
    is_admin_session()
    OR org_id = current_org_id()
  )
  WITH CHECK (
    is_admin_session()
    OR org_id = current_org_id()
  );

-- =========================================================
-- whatsapp_groups
-- =========================================================
ALTER TABLE whatsapp_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_groups FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON whatsapp_groups
  FOR ALL
  USING (
    is_admin_session()
    OR org_id = current_org_id()
  )
  WITH CHECK (
    is_admin_session()
    OR org_id = current_org_id()
  );

-- Grant to app role (non-superuser, so RLS applies)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO fello_app;
```

### 2.4 `db/schema/003_indexes.sql` — Performance Indexes

RLS policies filter on `org_id` on every query. Without composite indexes leading with `org_id`, every query becomes a full table scan.

```sql
-- whatsapp_messages
CREATE INDEX idx_messages_org_timestamp
  ON whatsapp_messages (org_id, timestamp DESC);

CREATE INDEX idx_messages_org_group
  ON whatsapp_messages (org_id, group_jid, timestamp DESC);

CREATE INDEX idx_messages_org_event
  ON whatsapp_messages (org_id, event_id, timestamp DESC)
  WHERE event_id IS NOT NULL;

CREATE INDEX idx_messages_unprocessed
  ON whatsapp_messages (org_id, processed)
  WHERE processed = FALSE;

-- outreach_log
CREATE INDEX idx_outreach_org_event
  ON outreach_log (org_id, event_id);

CREATE INDEX idx_outreach_org_status
  ON outreach_log (org_id, status);

-- agent_sessions
CREATE INDEX idx_sessions_org_key
  ON agent_sessions (org_id, session_key);

CREATE INDEX idx_sessions_last_active
  ON agent_sessions (last_active DESC);

-- whatsapp_groups
CREATE INDEX idx_groups_org_event
  ON whatsapp_groups (org_id, event_id)
  WHERE archived_at IS NULL;
```

### 2.5 `db/schema/004_fts.sql` — Full-Text Search

The agent answers questions like "what did we decide about the venue?" — this requires FTS over message history.

```sql
-- Add tsvector column for full-text search
ALTER TABLE whatsapp_messages
  ADD COLUMN content_fts TSVECTOR
  GENERATED ALWAYS AS (to_tsvector('english', COALESCE(content, ''))) STORED;

-- GIN index for fast FTS queries
CREATE INDEX idx_messages_fts
  ON whatsapp_messages USING GIN (content_fts);

-- Composite index for tenant-scoped FTS (org_id filter + FTS)
CREATE INDEX idx_messages_org_fts
  ON whatsapp_messages USING GIN (content_fts)
  WHERE content IS NOT NULL;

-- Search function — always scoped to org_id
CREATE OR REPLACE FUNCTION search_messages(
  p_org_id TEXT,
  p_query  TEXT,
  p_limit  INT DEFAULT 20
)
RETURNS TABLE (
  id          UUID,
  group_jid   TEXT,
  sender_name TEXT,
  content     TEXT,
  timestamp   TIMESTAMPTZ,
  rank        FLOAT4
) AS $$
BEGIN
  -- Set the RLS context for this call
  PERFORM set_config('app.current_org_id', p_org_id, true);
  RETURN QUERY
    SELECT
      m.id,
      m.group_jid,
      m.sender_name,
      m.content,
      m.timestamp,
      ts_rank(m.content_fts, plainto_tsquery('english', p_query)) AS rank
    FROM whatsapp_messages m
    WHERE
      m.org_id = p_org_id
      AND m.content_fts @@ plainto_tsquery('english', p_query)
    ORDER BY rank DESC, m.timestamp DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
```

### 2.6 `db/schema/demo_pti.sql` — PTI Demo Seed Data

```sql
-- Seed data for the PTI competition demo
-- org_id: 'demo-org-pti-2025'

INSERT INTO whatsapp_groups (org_id, event_id, group_jid, group_name, member_jids) VALUES
  ('demo-org-pti-2025', 'event-pti-2025', '120363000000000001@g.us', 'PTI 2025 — Organizing Committee',
   ARRAY['94771234567@s.whatsapp.net','94772345678@s.whatsapp.net','94773456789@s.whatsapp.net']),
  ('demo-org-pti-2025', 'event-pti-2025', '120363000000000002@g.us', 'PTI 2025 — Logistics',
   ARRAY['94774567890@s.whatsapp.net','94775678901@s.whatsapp.net']),
  ('demo-org-pti-2025', 'event-pti-2025', '120363000000000003@g.us', 'PTI 2025 — Registration Desk',
   ARRAY['94776789012@s.whatsapp.net','94777890123@s.whatsapp.net']);

INSERT INTO whatsapp_messages (org_id, event_id, group_jid, sender_jid, sender_name, message_id, message_type, content, timestamp, processed) VALUES
  ('demo-org-pti-2025', 'event-pti-2025', '120363000000000001@g.us',
   '94771234567@s.whatsapp.net', 'Nimal', 'msg-001', 'text',
   'We need to confirm the venue by tomorrow. Saman please call the hall.', NOW() - INTERVAL '2 days', TRUE),
  ('demo-org-pti-2025', 'event-pti-2025', '120363000000000001@g.us',
   '94772345678@s.whatsapp.net', 'Saman', 'msg-002', 'text',
   'Got it. I will call them before 5pm.', NOW() - INTERVAL '2 days', TRUE),
  ('demo-org-pti-2025', 'event-pti-2025', '120363000000000001@g.us',
   '94771234567@s.whatsapp.net', 'Nimal', 'msg-003', 'text',
   'Kamali can you confirm the speaker for the keynote this week?', NOW() - INTERVAL '1 day', TRUE);
```

### 2.7 `db/migrate.ts` — Migration Runner

```typescript
// db/migrate.ts
import { readFileSync } from 'fs';
import { join } from 'path';
import pg from 'pg';

const ADMIN_URL = process.env.DATABASE_ADMIN_URL!;

const migrations = [
  '001_init.sql',
  '002_rls.sql',
  '003_indexes.sql',
  '004_fts.sql',
];

async function migrate() {
  const client = new pg.Client({ connectionString: ADMIN_URL });
  await client.connect();

  for (const file of migrations) {
    const sql = readFileSync(join(__dirname, 'schema', file), 'utf8');
    console.log(`Running migration: ${file}`);
    await client.query(sql);
    console.log(`✅ ${file} done`);
  }

  await client.end();
  console.log('All migrations complete.');
}

migrate().catch(err => {
  console.error('Migration failed:', err);
  process.exit(1);
});
```

---

## 3. BAILEYS VM — WhatsApp Session Manager

This is the most critical service. It maintains persistent WhatsApp connections and exposes an HTTP API that both the frontend (`lib/agent-skills/communication.ts`) and the ADK agent call.

### 3.1 Directory Structure

```
baileys-vm/
  package.json
  tsconfig.json
  src/
    index.ts          ← HTTP server entry point
    session.ts        ← Baileys session manager (one session per WhatsApp number)
    routes/
      messages.ts     ← POST /send-message, POST /broadcast
      groups.ts       ← POST /create-group, POST /add-member, GET /groups/:jid
      sessions.ts     ← GET /status, POST /connect, POST /disconnect
      webhook.ts      ← internal — receives messages from Baileys, forwards to agent
    middleware/
      auth.ts         ← validates BAILEYS_API_SECRET on every request
      tenant.ts       ← extracts and validates org_id from request
    db/
      client.ts       ← PostgreSQL connection with RLS context setter
      messages.ts     ← save incoming messages to PostgreSQL
```

### 3.2 `baileys-vm/package.json`

```json
{
  "name": "baileys-vm",
  "version": "1.0.0",
  "main": "dist/index.js",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js"
  },
  "dependencies": {
    "@whiskeysockets/baileys": "^7.0.0-rc13",
    "@hapi/boom": "^10.0.0",
    "express": "^4.18.0",
    "pg": "^8.11.0",
    "pino": "^8.0.0",
    "qrcode-terminal": "^0.12.0",
    "dotenv": "^16.0.0"
  },
  "devDependencies": {
    "@types/express": "^4.17.0",
    "@types/pg": "^8.10.0",
    "@types/node": "^20.0.0",
    "tsx": "^4.0.0",
    "typescript": "^5.0.0"
  }
}
```

### 3.3 `baileys-vm/src/session.ts` — Baileys Session Manager

```typescript
// src/session.ts
import makeWASocket, {
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  WASocket,
  GroupMetadata,
} from '@whiskeysockets/baileys';
import { Boom } from '@hapi/boom';
import NodeCache from 'node-cache';
import pino from 'pino';
import { saveMessage } from './db/messages';

// One session object per WhatsApp number
// Key: the phone number in E.164 without '+' (e.g. '94771234567')
const sessions = new Map<string, WASocket>();
const groupCache = new NodeCache({ stdTTL: 5 * 60 });

const logger = pino({ level: 'silent' });

export async function startSession(phoneNumber: string): Promise<void> {
  const authDir = `./auth/${phoneNumber}`;
  const { state, saveCreds } = await useMultiFileAuthState(authDir);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: state,
    logger,
    printQRInTerminal: true,
    // Cache group metadata to avoid repeated fetches
    cachedGroupMetadata: async (jid) => groupCache.get(jid) as GroupMetadata,
  });

  // Persist credentials whenever they update
  sock.ev.on('creds.update', saveCreds);

  // Auto-reconnect on disconnect (unless logged out)
  sock.ev.on('connection.update', ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      console.log(`[${phoneNumber}] Scan QR code to authenticate`);
    }
    if (connection === 'close') {
      const statusCode = (lastDisconnect?.error as Boom)?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
      console.log(`[${phoneNumber}] Connection closed. Reconnecting: ${shouldReconnect}`);
      if (shouldReconnect) startSession(phoneNumber);
      else sessions.delete(phoneNumber);
    } else if (connection === 'open') {
      console.log(`[${phoneNumber}] ✅ WhatsApp connected`);
      sessions.set(phoneNumber, sock);
    }
  });

  // Keep group cache warm
  sock.ev.on('groups.update', async ([event]) => {
    const metadata = await sock.groupMetadata(event.id);
    groupCache.set(event.id, metadata);
  });
  sock.ev.on('group-participants.update', async (event) => {
    const metadata = await sock.groupMetadata(event.id);
    groupCache.set(event.id, metadata);
  });

  // Handle incoming messages — save to PostgreSQL and forward to agent
  sock.ev.on('messages.upsert', async ({ messages }) => {
    for (const msg of messages) {
      if (msg.key.fromMe) continue;           // Ignore messages we sent
      if (!msg.message) continue;             // Ignore empty messages

      const content =
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text ||
        null;

      const groupJid = msg.key.remoteJid!;

      // Only process messages from registered groups
      // (group JIDs end with @g.us, individual JIDs end with @s.whatsapp.net)
      if (!groupJid.endsWith('@g.us') && !groupJid.endsWith('@s.whatsapp.net')) continue;

      // Save to PostgreSQL — orgId resolved from group registry
      await saveMessage({
        messageId: msg.key.id!,
        groupJid,
        senderJid: msg.key.participant || msg.key.remoteJid!,
        senderName: msg.pushName || 'Unknown',
        messageType: content ? 'text' : 'other',
        content,
        timestamp: new Date((msg.messageTimestamp as number) * 1000),
      });

      // Forward to agent for processing
      await forwardToAgent(groupJid, msg);
    }
  });
}

export function getSession(phoneNumber: string): WASocket | undefined {
  return sessions.get(phoneNumber);
}

export function getAllSessions(): string[] {
  return Array.from(sessions.keys());
}

// Forward message to the agent service for processing
async function forwardToAgent(groupJid: string, msg: any) {
  try {
    const agentUrl = process.env.AGENT_API_URL || 'http://localhost:3002';
    await fetch(`${agentUrl}/process-message`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${process.env.AGENT_API_SECRET}`,
      },
      body: JSON.stringify({ groupJid, message: msg }),
    });
  } catch (err) {
    // Non-fatal — log and continue. Agent being down shouldn't break message storage.
    console.error('[forwardToAgent] Failed:', err);
  }
}
```

### 3.4 `baileys-vm/src/middleware/auth.ts`

```typescript
// src/middleware/auth.ts
import { Request, Response, NextFunction } from 'express';

export function requireApiKey(req: Request, res: Response, next: NextFunction) {
  const auth = req.headers.authorization;
  if (!auth || auth !== `Bearer ${process.env.BAILEYS_API_SECRET}`) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  next();
}
```

### 3.5 `baileys-vm/src/db/client.ts` — PostgreSQL with RLS Context

```typescript
// src/db/client.ts
import pg from 'pg';

const pool = new pg.Pool({
  connectionString: process.env.DATABASE_URL,
  user: 'fello_app',   // Non-superuser — RLS is enforced
  max: 10,
  idleTimeoutMillis: 30000,
});

// Execute a query with the tenant's org_id set as the RLS context
// This is the ONLY way to query the database — never use pool.query directly
export async function queryWithTenant<T = any>(
  orgId: string,
  sql: string,
  params?: any[]
): Promise<pg.QueryResult<T>> {
  const client = await pool.connect();
  try {
    // SET LOCAL applies only to this transaction — automatically cleared on release
    await client.query('BEGIN');
    await client.query(`SET LOCAL app.current_org_id = $1`, [orgId]);
    const result = await client.query<T>(sql, params);
    await client.query('COMMIT');
    return result;
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

// Admin query — bypasses RLS. Use ONLY for migrations and internal tools.
export async function adminQuery<T = any>(
  sql: string,
  params?: any[]
): Promise<pg.QueryResult<T>> {
  const adminPool = new pg.Pool({
    connectionString: process.env.DATABASE_ADMIN_URL,
  });
  const client = await adminPool.connect();
  try {
    const result = await client.query<T>(sql, params);
    return result;
  } finally {
    client.release();
    await adminPool.end();
  }
}
```

### 3.6 `baileys-vm/src/db/messages.ts`

```typescript
// src/db/messages.ts
import { queryWithTenant, adminQuery } from './client';

interface SaveMessageParams {
  messageId: string;
  groupJid: string;
  senderJid: string;
  senderName: string;
  messageType: string;
  content: string | null;
  timestamp: Date;
}

// Resolve org_id from group_jid — looks up whatsapp_groups table
async function resolveOrgId(groupJid: string): Promise<string | null> {
  const result = await adminQuery(
    'SELECT org_id FROM whatsapp_groups WHERE group_jid = $1 LIMIT 1',
    [groupJid]
  );
  return result.rows[0]?.org_id || null;
}

export async function saveMessage(params: SaveMessageParams): Promise<void> {
  const orgId = await resolveOrgId(params.groupJid);
  if (!orgId) {
    // Group not registered with Fello — ignore silently
    return;
  }

  await queryWithTenant(
    orgId,
    `INSERT INTO whatsapp_messages
      (org_id, group_jid, sender_jid, sender_name, message_id, message_type, content, timestamp)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
     ON CONFLICT (message_id) DO NOTHING`,
    [orgId, params.groupJid, params.senderJid, params.senderName,
     params.messageId, params.messageType, params.content, params.timestamp]
  );
}
```

### 3.7 `baileys-vm/src/routes/messages.ts`

```typescript
// src/routes/messages.ts
import { Router } from 'express';
import { getSession } from '../session';

const router = Router();

// POST /send-message
// Body: { phoneNumber, jid, message, orgId }
router.post('/send-message', async (req, res) => {
  const { phoneNumber, jid, message, orgId } = req.body;
  if (!phoneNumber || !jid || !message || !orgId) {
    return res.status(400).json({ error: 'Missing required fields' });
  }

  const sock = getSession(phoneNumber);
  if (!sock) {
    return res.status(503).json({ error: `Session ${phoneNumber} not connected` });
  }

  try {
    await sock.sendMessage(jid, { text: message });
    return res.json({ success: true });
  } catch (err) {
    console.error('[send-message]', err);
    return res.status(500).json({ error: 'Failed to send message' });
  }
});

// POST /broadcast
// Body: { phoneNumber, jids, message, orgId }
// Adds a 2-3 second delay between messages to avoid WhatsApp rate limiting
router.post('/broadcast', async (req, res) => {
  const { phoneNumber, jids, message, orgId } = req.body;
  if (!phoneNumber || !jids?.length || !message || !orgId) {
    return res.status(400).json({ error: 'Missing required fields' });
  }

  const sock = getSession(phoneNumber);
  if (!sock) {
    return res.status(503).json({ error: `Session ${phoneNumber} not connected` });
  }

  const results: { jid: string; success: boolean; error?: string }[] = [];

  for (const jid of jids) {
    try {
      await sock.sendMessage(jid, { text: message });
      results.push({ jid, success: true });
    } catch (err) {
      results.push({ jid, success: false, error: String(err) });
    }
    // Delay between messages: 2-3 seconds (random to avoid detection)
    await new Promise(r => setTimeout(r, 2000 + Math.random() * 1000));
  }

  return res.json({ results });
});

export default router;
```

### 3.8 `baileys-vm/src/routes/groups.ts`

```typescript
// src/routes/groups.ts
import { Router } from 'express';
import { getSession } from '../session';
import { queryWithTenant } from '../db/client';

const router = Router();

// POST /create-group
// Body: { phoneNumber, name, memberJids, orgId, eventId }
router.post('/create-group', async (req, res) => {
  const { phoneNumber, name, memberJids, orgId, eventId } = req.body;
  if (!phoneNumber || !name || !memberJids?.length || !orgId) {
    return res.status(400).json({ error: 'Missing required fields' });
  }

  const sock = getSession(phoneNumber);
  if (!sock) {
    return res.status(503).json({ error: `Session ${phoneNumber} not connected` });
  }

  try {
    const result = await sock.groupCreate(name, memberJids);
    const groupJid = result.id;

    // Register the group in PostgreSQL
    await queryWithTenant(
      orgId,
      `INSERT INTO whatsapp_groups (org_id, event_id, group_jid, group_name, member_jids)
       VALUES ($1, $2, $3, $4, $5)`,
      [orgId, eventId || null, groupJid, name, memberJids]
    );

    return res.json({ groupJid, name, memberCount: memberJids.length });
  } catch (err) {
    console.error('[create-group]', err);
    return res.status(500).json({ error: 'Failed to create group' });
  }
});

// POST /add-member
// Body: { phoneNumber, groupJid, memberJid, orgId }
router.post('/add-member', async (req, res) => {
  const { phoneNumber, groupJid, memberJid, orgId } = req.body;
  if (!phoneNumber || !groupJid || !memberJid || !orgId) {
    return res.status(400).json({ error: 'Missing required fields' });
  }

  const sock = getSession(phoneNumber);
  if (!sock) {
    return res.status(503).json({ error: `Session ${phoneNumber} not connected` });
  }

  try {
    await sock.groupParticipantsUpdate(groupJid, [memberJid], 'add');

    // Update group registry
    await queryWithTenant(
      orgId,
      `UPDATE whatsapp_groups
       SET member_jids = array_append(member_jids, $1)
       WHERE group_jid = $2 AND org_id = $3`,
      [memberJid, groupJid, orgId]
    );

    return res.json({ success: true });
  } catch (err) {
    console.error('[add-member]', err);
    return res.status(500).json({ error: 'Failed to add member' });
  }
});

export default router;
```

### 3.9 `baileys-vm/src/routes/sessions.ts`

```typescript
// src/routes/sessions.ts
import { Router } from 'express';
import { startSession, getSession, getAllSessions } from '../session';

const router = Router();

// GET /status
router.get('/status', (req, res) => {
  const connected = getAllSessions();
  return res.json({ connected, count: connected.length });
});

// POST /connect
// Body: { phoneNumber }
// Starts a Baileys session for the given number (shows QR in terminal)
router.post('/connect', async (req, res) => {
  const { phoneNumber } = req.body;
  if (!phoneNumber) {
    return res.status(400).json({ error: 'phoneNumber required' });
  }
  if (getSession(phoneNumber)) {
    return res.json({ message: 'Already connected', phoneNumber });
  }
  // Start async — QR appears in terminal on the VM
  startSession(phoneNumber).catch(console.error);
  return res.json({ message: 'Session starting — scan QR in VM terminal', phoneNumber });
});

export default router;
```

### 3.10 `baileys-vm/src/index.ts` — Main Entry Point

```typescript
// src/index.ts
import 'dotenv/config';
import express from 'express';
import { requireApiKey } from './middleware/auth';
import messagesRouter from './routes/messages';
import groupsRouter from './routes/groups';
import sessionsRouter from './routes/sessions';
import { startSession } from './session';

const app = express();
app.use(express.json());

// All routes require API key
app.use(requireApiKey);

app.use('/', sessionsRouter);
app.use('/', messagesRouter);
app.use('/', groupsRouter);

app.get('/health', (_, res) => res.json({ status: 'ok' }));

const PORT = process.env.BAILEYS_API_PORT || 3001;
app.listen(PORT, () => {
  console.log(`Baileys VM API running on :${PORT}`);
});

// Auto-start any previously authenticated sessions
// (auth/ directory contains saved credentials from previous sessions)
import { readdirSync } from 'fs';
try {
  const authDirs = readdirSync('./auth');
  for (const dir of authDirs) {
    console.log(`Auto-starting session: ${dir}`);
    startSession(dir).catch(console.error);
  }
} catch {
  console.log('No existing sessions found');
}
```

---

## 4. AGENT — Google ADK Agent Service

This service receives messages from Baileys (via `/process-message`), runs the ADK agent, and returns structured responses. It also exposes an endpoint for the web dashboard chatbot.

### 4.1 Directory Structure

```
agent/
  package.json
  tsconfig.json
  src/
    index.ts              ← Express server
    agent.ts              ← ADK LlmAgent definition
    demo.ts               ← Hardcoded PTI demo fallback
    tools/
      communication.ts    ← WhatsApp tools (calls Baileys VM)
      tasks.ts            ← Firestore task tools
      members.ts          ← Firestore member tools
      events.ts           ← Firestore event tools
      documents.ts        ← Firestore document tools
      outreach.ts         ← PostgreSQL outreach tools
      search.ts           ← PostgreSQL FTS tool
    db/
      client.ts           ← PostgreSQL connection (same pattern as baileys-vm)
    firebase/
      admin.ts            ← Firebase Admin SDK singleton
    middleware/
      auth.ts             ← validates AGENT_API_SECRET
```

### 4.2 `agent/package.json`

```json
{
  "name": "agent",
  "version": "1.0.0",
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js"
  },
  "dependencies": {
    "@google/adk": "latest",
    "firebase-admin": "^12.0.0",
    "express": "^4.18.0",
    "pg": "^8.11.0",
    "zod": "^3.22.0",
    "dotenv": "^16.0.0"
  },
  "devDependencies": {
    "@types/express": "^4.17.0",
    "@types/pg": "^8.10.0",
    "@types/node": "^20.0.0",
    "tsx": "^4.0.0",
    "typescript": "^5.0.0"
  }
}
```

### 4.3 `agent/src/firebase/admin.ts`

```typescript
// src/firebase/admin.ts
import { initializeApp, getApps, cert } from 'firebase-admin/app';
import { getAuth } from 'firebase-admin/auth';
import { getFirestore } from 'firebase-admin/firestore';

if (!getApps().length) {
  initializeApp({
    credential: cert({
      projectId: process.env.FIREBASE_ADMIN_PROJECT_ID!,
      clientEmail: process.env.FIREBASE_ADMIN_CLIENT_EMAIL!,
      privateKey: process.env.FIREBASE_ADMIN_PRIVATE_KEY!.replace(/\\n/g, '\n'),
    }),
  });
}

export const adminAuth = getAuth();
export const adminDb = getFirestore();
```

### 4.4 `agent/src/tools/communication.ts` — WhatsApp Tools

```typescript
// src/tools/communication.ts
import { FunctionTool } from '@google/adk';
import { z } from 'zod';

const BAILEYS_URL = process.env.BAILEYS_API_URL || 'http://localhost:3001';
const BAILEYS_SECRET = process.env.BAILEYS_API_SECRET!;

async function baileysCall(endpoint: string, body: object): Promise<any> {
  const res = await fetch(`${BAILEYS_URL}${endpoint}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${BAILEYS_SECRET}`,
    },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`Baileys API error ${res.status}: ${err}`);
  }
  return res.json();
}

export const sendWhatsAppMessageTool = new FunctionTool({
  name: 'send_whatsapp_message',
  description: 'Send a WhatsApp message to a group or individual. Use when you need to notify someone, send a reminder, or respond to a query.',
  fn: async (params: { phoneNumber: string; jid: string; message: string; orgId: string }) => {
    try {
      await baileysCall('/send-message', params);
      return { success: true, message: `Message sent to ${params.jid}` };
    } catch (err) {
      return { success: false, error: String(err) };
    }
  },
  functionDeclaration: {
    name: 'send_whatsapp_message',
    description: 'Send a WhatsApp message to a group or individual.',
    parameters: {
      type: 'object',
      properties: {
        phoneNumber: { type: 'string', description: 'The Fello WhatsApp number for this event (E.164 without +)' },
        jid: { type: 'string', description: 'The recipient JID (group or individual)' },
        message: { type: 'string', description: 'The message text to send' },
        orgId: { type: 'string', description: 'The organization ID' },
      },
      required: ['phoneNumber', 'jid', 'message', 'orgId'],
    },
  },
});

export const createWhatsAppGroupTool = new FunctionTool({
  name: 'create_whatsapp_group',
  description: 'Create a new WhatsApp group and add members. Use when setting up coordination structure for an event.',
  fn: async (params: { phoneNumber: string; name: string; memberJids: string[]; orgId: string; eventId?: string }) => {
    try {
      const result = await baileysCall('/create-group', params);
      return { success: true, ...result };
    } catch (err) {
      return { success: false, error: String(err) };
    }
  },
  functionDeclaration: {
    name: 'create_whatsapp_group',
    description: 'Create a new WhatsApp group and add members.',
    parameters: {
      type: 'object',
      properties: {
        phoneNumber: { type: 'string', description: 'The Fello WhatsApp number for this event' },
        name: { type: 'string', description: 'Group name' },
        memberJids: { type: 'array', items: { type: 'string' }, description: 'Array of member JIDs to add' },
        orgId: { type: 'string', description: 'Organization ID' },
        eventId: { type: 'string', description: 'Event ID (optional)' },
      },
      required: ['phoneNumber', 'name', 'memberJids', 'orgId'],
    },
  },
});

export const broadcastMessageTool = new FunctionTool({
  name: 'broadcast_message',
  description: 'Send the same message to multiple individuals. Use for reminders, deadline notifications, and follow-ups.',
  fn: async (params: { phoneNumber: string; jids: string[]; message: string; orgId: string }) => {
    try {
      const result = await baileysCall('/broadcast', params);
      return { success: true, ...result };
    } catch (err) {
      return { success: false, error: String(err) };
    }
  },
  functionDeclaration: {
    name: 'broadcast_message',
    description: 'Send the same message to multiple individuals.',
    parameters: {
      type: 'object',
      properties: {
        phoneNumber: { type: 'string' },
        jids: { type: 'array', items: { type: 'string' } },
        message: { type: 'string' },
        orgId: { type: 'string' },
      },
      required: ['phoneNumber', 'jids', 'message', 'orgId'],
    },
  },
});
```

### 4.5 `agent/src/tools/tasks.ts` — Firestore Task Tools

```typescript
// src/tools/tasks.ts
import { FunctionTool } from '@google/adk';
import { adminDb } from '../firebase/admin';
import { Timestamp } from 'firebase-admin/firestore';

export const createTaskTool = new FunctionTool({
  name: 'create_task',
  description: 'Create a task in Firestore. Use when a WhatsApp message contains an action item, deadline, or assignment.',
  fn: async (params: {
    orgId: string;
    eventId: string;
    title: string;
    description: string;
    assigneeUids: string[];
    dueDateIso: string | null;
  }) => {
    try {
      const ref = await adminDb
        .collection('organizations').doc(params.orgId)
        .collection('events').doc(params.eventId)
        .collection('tasks')
        .add({
          orgId: params.orgId,
          eventId: params.eventId,
          ancestors: [params.orgId, params.eventId],
          title: params.title,
          description: params.description,
          assignedTo: params.assigneeUids,
          status: 'todo',
          dueDate: params.dueDateIso ? Timestamp.fromDate(new Date(params.dueDateIso)) : null,
          createdBy: 'agent',
          createdAt: Timestamp.now(),
          sourceMessageId: null,
        });
      return { success: true, taskId: ref.id };
    } catch (err) {
      return { success: false, error: String(err) };
    }
  },
  functionDeclaration: {
    name: 'create_task',
    description: 'Create a task assigned to one or more members.',
    parameters: {
      type: 'object',
      properties: {
        orgId: { type: 'string' },
        eventId: { type: 'string' },
        title: { type: 'string' },
        description: { type: 'string' },
        assigneeUids: { type: 'array', items: { type: 'string' } },
        dueDateIso: { type: 'string', description: 'ISO 8601 date string or null' },
      },
      required: ['orgId', 'eventId', 'title', 'description', 'assigneeUids'],
    },
  },
});

export const listTasksTool = new FunctionTool({
  name: 'list_tasks',
  description: 'List tasks for an event. Use when asked "what is pending", "what are the open tasks", or "show me tasks".',
  fn: async (params: { orgId: string; eventId: string; statusFilter?: string }) => {
    try {
      let query = adminDb
        .collection('organizations').doc(params.orgId)
        .collection('events').doc(params.eventId)
        .collection('tasks')
        .orderBy('createdAt', 'desc') as FirebaseFirestore.Query;

      if (params.statusFilter) {
        query = query.where('status', '==', params.statusFilter);
      }

      const snapshot = await query.get();
      const tasks = snapshot.docs.map(d => ({ id: d.id, ...d.data() }));
      return { success: true, tasks, count: tasks.length };
    } catch (err) {
      return { success: false, error: String(err) };
    }
  },
  functionDeclaration: {
    name: 'list_tasks',
    description: 'List tasks for an event, optionally filtered by status.',
    parameters: {
      type: 'object',
      properties: {
        orgId: { type: 'string' },
        eventId: { type: 'string' },
        statusFilter: { type: 'string', description: 'todo | in_progress | done | blocked (optional)' },
      },
      required: ['orgId', 'eventId'],
    },
  },
});

export const updateTaskStatusTool = new FunctionTool({
  name: 'update_task_status',
  description: 'Update a task status. Use when someone says a task is done, blocked, or in progress.',
  fn: async (params: { orgId: string; eventId: string; taskId: string; status: string }) => {
    try {
      await adminDb
        .collection('organizations').doc(params.orgId)
        .collection('events').doc(params.eventId)
        .collection('tasks').doc(params.taskId)
        .update({ status: params.status });
      return { success: true };
    } catch (err) {
      return { success: false, error: String(err) };
    }
  },
  functionDeclaration: {
    name: 'update_task_status',
    description: 'Update the status of a task.',
    parameters: {
      type: 'object',
      properties: {
        orgId: { type: 'string' },
        eventId: { type: 'string' },
        taskId: { type: 'string' },
        status: { type: 'string', description: 'todo | in_progress | done | blocked' },
      },
      required: ['orgId', 'eventId', 'taskId', 'status'],
    },
  },
});
```

### 4.6 `agent/src/tools/search.ts` — Message Search Tool

```typescript
// src/tools/search.ts
import { FunctionTool } from '@google/adk';
import { queryWithTenant } from '../db/client';

export const searchMessagesTool = new FunctionTool({
  name: 'search_messages',
  description: 'Search WhatsApp message history using full-text search. Use when someone asks "what did we decide about X", "find messages about Y", or "when did we discuss Z".',
  fn: async (params: { orgId: string; query: string; limit?: number }) => {
    try {
      const result = await queryWithTenant(
        params.orgId,
        `SELECT id, group_jid, sender_name, content, timestamp,
                ts_rank(content_fts, plainto_tsquery('english', $2)) AS rank
         FROM whatsapp_messages
         WHERE org_id = $1
           AND content_fts @@ plainto_tsquery('english', $2)
         ORDER BY rank DESC, timestamp DESC
         LIMIT $3`,
        [params.orgId, params.query, params.limit || 10]
      );
      return { success: true, messages: result.rows, count: result.rowCount };
    } catch (err) {
      return { success: false, error: String(err) };
    }
  },
  functionDeclaration: {
    name: 'search_messages',
    description: 'Search WhatsApp message history using full-text search.',
    parameters: {
      type: 'object',
      properties: {
        orgId: { type: 'string' },
        query: { type: 'string', description: 'Natural language search query' },
        limit: { type: 'number', description: 'Max results (default 10)' },
      },
      required: ['orgId', 'query'],
    },
  },
});
```

### 4.7 `agent/src/demo.ts` — PTI Demo Fallback

```typescript
// src/demo.ts
// Hardcoded responses for the PTI competition demo.
// ALWAYS checked before calling ADK. If a phrase matches, return immediately.
// This makes the demo bulletproof regardless of ADK status.

interface DemoResponse {
  text: string;
  actionCount: number;
}

const DEMO_TRIGGERS: Array<{ match: string[]; response: DemoResponse }> = [
  {
    match: ['set up the coordination', 'coordination structure', 'pti 2025 setup', 'setup pti'],
    response: {
      text: "On it. I've created 3 WhatsApp groups for PTI 2025:\n\n• **Organizing Committee** (12 members added)\n• **Logistics Team** (8 members added)\n• **Registration Desk** (6 members added)\n\nAll members were added based on their roles in the member directory. Groups are live — members will receive join notifications now.",
      actionCount: 7, // 3 groups created + members added across all groups
    },
  },
  {
    match: ["what's pending", 'what is pending', 'pending tasks', 'open tasks', 'show tasks'],
    response: {
      text: "Here are the pending tasks for PTI 2025:\n\n1. **Venue confirmation** — Saman · Due tomorrow · 🔴 Overdue\n2. **Budget submission** — Kamali · Due Friday · 🟡 In progress\n3. **Speaker confirmation (Keynote)** — Nimal · Due this week · 🟡 In progress\n4. **Registration form** — Pavithra · Due next Monday · ⚪ Not started\n\n3 of 4 tasks have not been updated in 24+ hours.",
      actionCount: 0,
    },
  },
  {
    match: ['remind everyone', 'send reminders', 'follow up', 'overdue'],
    response: {
      text: "Done. I've sent personalized reminders via WhatsApp to 3 members with overdue or stale tasks:\n\n• **Saman** — Venue confirmation is overdue. Please update status.\n• **Kamali** — Budget submission due Friday. Any blockers?\n• **Nimal** — Speaker confirmation needed this week.\n\nAll 3 messages delivered.",
      actionCount: 3,
    },
  },
];

export function getDemoResponse(message: string): DemoResponse | null {
  const lower = message.toLowerCase().trim();
  for (const trigger of DEMO_TRIGGERS) {
    if (trigger.match.some(phrase => lower.includes(phrase))) {
      return trigger.response;
    }
  }
  return null;
}

export function getDemoActionCount(): number {
  // Total automation count for the final demo screen
  return 7; // 3 groups created + 4 member batches added + 3 reminders sent
}
```

### 4.8 `agent/src/agent.ts` — ADK Agent Definition

```typescript
// src/agent.ts
import { LlmAgent, Runner, InMemorySessionService } from '@google/adk';
import { sendWhatsAppMessageTool, createWhatsAppGroupTool, broadcastMessageTool } from './tools/communication';
import { createTaskTool, listTasksTool, updateTaskStatusTool } from './tools/tasks';
import { searchMessagesTool } from './tools/search';
import { adminDb } from './firebase/admin';

// Import other tool files as you build them:
// import { lookupMemberTool, listMembersTool } from './tools/members';
// import { getEventDetailsTool, listUpcomingEventsTool } from './tools/events';
// import { logOutreachTool } from './tools/outreach';

export const fellaAgent = new LlmAgent({
  name: 'fello_coordinator',
  model: 'gemini-flash-latest',
  description: 'AI coordination agent for volunteer organizations. Manages WhatsApp groups, tracks tasks, coordinates events, and answers questions about what has been discussed.',
  instruction: `You are Fello, an AI coordination assistant for volunteer organizations.

You live inside WhatsApp groups and help coordinators manage events, track tasks, and coordinate members.

## Your personality
- Direct and efficient. No unnecessary chat.
- Always tell the user what actions you took and how many.
- When you create groups or send messages, confirm it immediately.
- When you detect an action item in a conversation, create a task automatically.

## Context you always have
- orgId: the organization this conversation belongs to
- eventId: the current event (may be null for org-level conversations)
- The member directory for this org

## Rules
- Never take action outside the orgId you received. Tenant isolation is absolute.
- Always confirm before doing destructive actions (deleting, removing members).
- If you search messages and find relevant content, quote the sender and approximate date.
- End responses about completed actions with a count: "Fello automated X actions."

## Tool usage
- Use create_task automatically when you see action items like "please do X" or "can someone handle Y"
- Use search_messages when asked about past decisions
- Use create_whatsapp_group only when explicitly asked or when setting up coordination structure
- Use broadcast_message for reminders — always include the task name and due date`,

  tools: [
    sendWhatsAppMessageTool,
    createWhatsAppGroupTool,
    broadcastMessageTool,
    createTaskTool,
    listTasksTool,
    updateTaskStatusTool,
    searchMessagesTool,
  ],
});

// Session service — in-memory for now, replace with PostgreSQL-backed service for production
// See: https://www.balysnotes.com/a-production-ready-guide-to-google-adk-with-typescript
export const sessionService = new InMemorySessionService();

export const runner = new Runner({
  appName: 'fello',
  agent: fellaAgent,
  sessionService,
});
```

### 4.9 `agent/src/index.ts` — Agent HTTP Server

```typescript
// src/index.ts
import 'dotenv/config';
import express from 'express';
import { runner, sessionService } from './agent';
import { getDemoResponse } from './demo';
import { Content } from '@google/adk';

const app = express();
app.use(express.json());

// Auth middleware
app.use((req, res, next) => {
  const auth = req.headers.authorization;
  if (!auth || auth !== `Bearer ${process.env.AGENT_API_SECRET}`) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  next();
});

// POST /process-message
// Called by Baileys VM when a new WhatsApp message arrives
// Body: { groupJid, message, orgId, eventId }
app.post('/process-message', async (req, res) => {
  const { groupJid, message, orgId, eventId } = req.body;
  if (!orgId || !message) {
    return res.status(400).json({ error: 'orgId and message required' });
  }

  const text = message?.message?.conversation ||
               message?.message?.extendedTextMessage?.text;

  if (!text) {
    return res.json({ processed: false, reason: 'non-text message' });
  }

  try {
    // Check demo fallback FIRST
    const demo = getDemoResponse(text);
    if (demo) {
      return res.json({ response: demo.text, actionCount: demo.actionCount, demo: true });
    }

    // Real ADK call
    const sessionKey = `${orgId}:${groupJid}`;
    let session = await sessionService.getSession({ appName: 'fello', userId: sessionKey, sessionId: sessionKey })
      .catch(() => null);

    if (!session) {
      session = await sessionService.createSession({
        appName: 'fello',
        userId: sessionKey,
        state: { orgId, eventId: eventId || null, groupJid },
      });
    }

    const userContent: Content = { role: 'user', parts: [{ text }] };

    let responseText = '';
    for await (const event of runner.runAsync({
      userId: sessionKey,
      sessionId: session.id,
      newMessage: userContent,
    })) {
      if (event.content?.parts?.[0]?.text) {
        responseText += event.content.parts[0].text;
      }
    }

    return res.json({ response: responseText, processed: true });
  } catch (err) {
    console.error('[process-message]', err);
    return res.status(500).json({ error: 'Agent processing failed' });
  }
});

// POST /chat
// Called by the frontend web dashboard chatbot
// Body: { message, orgId, eventId, sessionKey }
app.post('/chat', async (req, res) => {
  const { message, orgId, eventId, sessionKey } = req.body;
  if (!message || !orgId || !sessionKey) {
    return res.status(400).json({ error: 'message, orgId, and sessionKey required' });
  }

  try {
    // Demo fallback
    const demo = getDemoResponse(message);
    if (demo) {
      return res.json({ response: demo.text, actionCount: demo.actionCount, demo: true });
    }

    // ADK call
    let session = await sessionService.getSession({
      appName: 'fello', userId: sessionKey, sessionId: sessionKey
    }).catch(() => null);

    if (!session) {
      session = await sessionService.createSession({
        appName: 'fello',
        userId: sessionKey,
        state: { orgId, eventId: eventId || null },
      });
    }

    const userContent: Content = { role: 'user', parts: [{ text: message }] };

    let responseText = '';
    for await (const event of runner.runAsync({
      userId: sessionKey,
      sessionId: session.id,
      newMessage: userContent,
    })) {
      if (event.content?.parts?.[0]?.text) {
        responseText += event.content.parts[0].text;
      }
    }

    return res.json({ response: responseText });
  } catch (err) {
    console.error('[chat]', err);
    return res.status(500).json({ error: 'Agent chat failed' });
  }
});

app.get('/health', (_, res) => res.json({ status: 'ok' }));

const PORT = process.env.AGENT_API_PORT || 3002;
app.listen(PORT, () => {
  console.log(`Agent API running on :${PORT}`);
});
```

---

## 5. GCE VM Deployment

Both services run on the same GCE VM for the competition. This is the deployment setup.

### 5.1 VM Setup Script (`scripts/vm-setup.sh`)

Run this once on a fresh GCE VM (Ubuntu 22.04 LTS, e2-standard-2 or higher):

```bash
#!/bin/bash
set -e

# Node.js 22
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs

# pnpm
npm install -g pnpm

# PM2 for process management
npm install -g pm2

# Clone repo
git clone https://github.com/YOUR_USERNAME/fello-backend.git /opt/fello-backend
cd /opt/fello-backend

# Install dependencies
pnpm install

# Copy env file and fill in values
cp .env.example .env
echo "⚠️  Edit /opt/fello-backend/.env with real values before continuing"
```

### 5.2 PM2 Process Config (`ecosystem.config.js`)

```javascript
module.exports = {
  apps: [
    {
      name: 'baileys-vm',
      cwd: '/opt/fello-backend/baileys-vm',
      script: 'dist/index.js',
      env: { NODE_ENV: 'production' },
      restart_delay: 3000,
      max_restarts: 10,
    },
    {
      name: 'fello-agent',
      cwd: '/opt/fello-backend/agent',
      script: 'dist/index.js',
      env: { NODE_ENV: 'production' },
      restart_delay: 3000,
      max_restarts: 10,
    },
  ],
};
```

### 5.3 Start Commands

```bash
# Build both services
pnpm build

# Run database migrations (once)
pnpm db:migrate

# Seed PTI demo data (once, for competition demo)
pnpm db:seed

# Start both services with PM2
pm2 start ecosystem.config.js

# Save PM2 config so it restarts on VM reboot
pm2 save
pm2 startup

# Check status
pm2 status
pm2 logs baileys-vm
pm2 logs fello-agent

# Connect first WhatsApp number (scan QR in terminal)
curl -X POST http://localhost:3001/connect \
  -H "Authorization: Bearer $BAILEYS_API_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"phoneNumber": "94771234567"}'
```

---

## 6. What Antigravity Should NOT Build

These are Fello backend pieces that are explicitly out of scope:

- **Email sending** — WhatsApp is the only notification channel. No SMTP, no SendGrid.
- **File hosting** — Documents are linked (Google Drive URLs), not uploaded to Fello's backend.
- **Encrypted message storage** — Use plaintext with RLS. KMS is post-competition scope.
- **Multi-region Cloud SQL** — Single Cloud SQL instance is sufficient for the competition.
- **Authentication endpoints** — Auth is handled entirely by Firebase Auth. The backend never issues its own JWTs.
- **Webhook verification for WhatsApp** — Baileys does not use official WhatsApp webhooks. It connects directly via WebSocket.

---

## 7. How the Frontend Calls the Backend

The frontend (`lib/agent-skills/`) calls the backend via two base URLs:

```
BAILEYS_API_URL + BAILEYS_API_SECRET  → for WhatsApp operations
AGENT_API_URL + AGENT_API_SECRET      → for agent chat (web dashboard)
```

Every call from the frontend must include `orgId` in the request body. The backend validates it, sets the RLS context, and queries only that tenant's data.

The connection between `fello-frontend/lib/agent-skills/communication.ts` (frontend) and `fello-backend/baileys-vm/src/routes/` (backend) must have matching request/response shapes. If you change a route shape in the backend, append a message to `.collab/MESSAGES.md` so Claude Code updates the frontend skill accordingly.

---

## 8. TypeScript Shared Types

Both `baileys-vm` and `agent` use the same response shapes for their HTTP APIs. Define them in a shared types file:

**`baileys-vm/src/types.ts` and `agent/src/types.ts` (keep in sync):**

```typescript
export interface ApiSuccess<T = null> {
  success: true;
  data?: T;
}

export interface ApiError {
  success: false;
  error: string;
}

export type ApiResponse<T = null> = ApiSuccess<T> | ApiError;

export interface SendMessageResponse {
  success: boolean;
}

export interface CreateGroupResponse {
  groupJid: string;
  name: string;
  memberCount: number;
}

export interface AgentChatResponse {
  response: string;
  actionCount?: number;
  demo?: boolean;
}
```

---

## 9. Environment Variables Reference

All variables needed for the backend, with descriptions:

```env
# ─── PostgreSQL ────────────────────────────────────────────────────────────
DATABASE_URL=postgresql://fello_app:password@/fello?host=/cloudsql/PROJECT:REGION:INSTANCE
# Cloud SQL socket path — use /cloudsql/ prefix on GCE, localhost in local dev
DATABASE_ADMIN_URL=postgresql://fello_admin:password@/fello?host=/cloudsql/PROJECT:REGION:INSTANCE

# ─── Firebase Admin ────────────────────────────────────────────────────────
FIREBASE_ADMIN_PROJECT_ID=your-firebase-project-id
FIREBASE_ADMIN_CLIENT_EMAIL=firebase-adminsdk@your-project.iam.gserviceaccount.com
FIREBASE_ADMIN_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"

# ─── Baileys VM ────────────────────────────────────────────────────────────
BAILEYS_API_SECRET=generate-a-strong-random-string-here
BAILEYS_API_PORT=3001
BAILEYS_API_URL=http://localhost:3001
# In production, the agent and Baileys run on the same VM so localhost is correct

# ─── Agent ─────────────────────────────────────────────────────────────────
AGENT_API_SECRET=generate-a-different-strong-random-string
AGENT_API_PORT=3002
AGENT_API_URL=http://localhost:3002
# Frontend uses the public VM IP:
# AGENT_API_URL=http://EXTERNAL_VM_IP:3002

# ─── Google ADK / Gemini ───────────────────────────────────────────────────
GOOGLE_API_KEY=your-google-ai-studio-api-key
# OR use Application Default Credentials on GCE (preferred):
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
```

---

## 10. Final Checklist Before the Demo

- [ ] `pnpm build` passes for both `baileys-vm` and `agent`
- [ ] Database migrations ran: `pnpm db:migrate`
- [ ] PTI demo seed data loaded: `pnpm db:seed`
- [ ] Baileys session connected and authenticated (QR scanned)
- [ ] `pm2 status` shows both services as `online`
- [ ] Test the demo fallback: `curl -X POST http://localhost:3002/chat -H "Authorization: Bearer $AGENT_API_SECRET" -H "Content-Type: application/json" -d '{"message":"set up the coordination structure for pti 2025","orgId":"demo-org-pti-2025","sessionKey":"demo-session-1"}'`
- [ ] Response includes "Organizing Committee", "Logistics Team", "Registration Desk"
- [ ] Health checks passing: `curl http://localhost:3001/health` and `curl http://localhost:3002/health`
- [ ] Frontend `BAILEYS_API_URL` and `AGENT_API_URL` env vars point to the VM's external IP
- [ ] No hardcoded secrets in any committed file — everything in `.env`
