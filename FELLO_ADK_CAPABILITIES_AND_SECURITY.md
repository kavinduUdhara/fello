# Fello — ADK Capabilities and Security Model

## What ADK Actually Is

Agent Development Kit is Google's open-source framework for building, testing, and deploying AI agents — from a single agent to a coordinated multi-agent system. It is the official agent layer for Google's Gemini Enterprise Agent Platform, and it deploys cleanly to Cloud Run, GKE, or Vertex AI Agent Engine without requiring infrastructure changes.

ADK is not just a wrapper around calling Gemini. It manages the full lifecycle — sessions, memory, tool orchestration, context assembly, evaluation, and deployment — as a coherent system rather than separate pieces you wire together yourself.

---

## Core Capabilities Relevant to Fello

### Context management is automatic, not manual

ADK treats context like source code, not like a string you keep appending to. It automatically filters irrelevant events out of the conversation, summarizes older turns so they don't bloat the prompt, lazy-loads artifacts only when needed, and tracks token usage throughout. This matters directly for Fello because the orchestrator agent will accumulate a lot of conversational history per event — without this automatic management, a long-running event conversation would eventually blow past context limits or get expensive. ADK handles this by default.

### Sessions and state — four distinct scopes

ADK's session state system maps almost perfectly onto Fello's needs:

**Session-scoped state** (`session.state['current_intent']`) — specific to the current conversation thread, like tracking which step of "creating an event" the user is currently on. Only persists if using a persistent SessionService.

**User-scoped state** (`session.state['user:preferred_language']`) — tied to a user_id, shared across all of that user's sessions within the app. This is where Fello would store things like a member's communication preference or their role context.

**App-scoped state** (`session.state['app:global_discount_code']`) — shared across all users and sessions for the entire application. Less relevant for Fello since almost everything is org-scoped, not app-global.

**Invocation-scoped (temp) state** (`session.state['temp:raw_api_response']`) — exists only for the single request-response cycle currently running, discarded immediately after. Used for intermediate calculations or data passed between tool calls within one invocation. When a parent agent calls a sub-agent through SequentialAgent or ParallelAgent, the sub-agent inherits the same invocation ID and therefore the same temp state — this is exactly how Fello's orchestrator would pass context to the Extraction Agent or Summary Agent without re-sending everything from scratch.

State values must be simple serializable types — strings, numbers, booleans, lists, and dicts of those. Complex objects (open file handles, live connections, class instances) cannot be stored directly — only their identifiers, with the actual object retrieved elsewhere when needed.

### Persistence options

InMemorySessionService is not persistent — state is lost on restart, useful only for local testing. For Fello's production behavior, DatabaseSessionService or VertexAiSessionService must be used so that conversation state survives Cloud Run instance restarts and scaling events.

### Multi-agent orchestration patterns

ADK supports composing specialized agents into a hierarchy rather than forcing everything into one giant prompt. The documented reasons production systems split agents:

**Context degradation** — once a single agent's tool count grows past roughly 10-15 tools, the model starts missing instructions, calling the wrong tool, or hallucinating parameters. Each additional tool dilutes the model's attention across a wider surface. This is the concrete threshold behind the recommendation in Fello's agent architecture doc to keep the orchestrator's tool count lean and push high-volume specialized work (message extraction, summarization) into separate sub-agents.

**Tool specialization** — each agent only has access to the tools it actually needs, which is both a context-size benefit and a security benefit (the Extraction Agent never has access to calendar-booking tools, for example).

**Independent development and isolated testing** — separate agents can be built, tested, and updated independently without one team's changes breaking another's logic.

**Graceful degradation** — if one specialized agent fails, the others keep functioning rather than the entire system going down.

Communication between agents in a pipeline (SequentialAgent, ParallelAgent) happens through `ToolContext.state` — a shared dictionary all sub-agents in that pipeline read and write to, rather than passing data through function arguments or return values. This is the actual mechanism behind "agents talking to each other" in Fello's orchestrator-plus-sub-agents design.

### Cross-language and remote agents (A2A protocol)

ADK supports the Agent2Agent protocol, which lets you wrap a remote agent — even one written in a different language — as a local sub-agent using `RemoteA2aAgent`. This is genuinely useful for large organizations with agents in different stacks, but for Fello's current scope it is unnecessary. All of Fello's agents live in one Cloud Run backend and communicate in-process. A2A becomes relevant only if Fello later needs to integrate a third-party agent service that lives outside its own infrastructure.

### Code execution sandbox

When ADK agents need to execute generated code, the Agent Engine Code Execution tool provides process-level isolation — a secure, isolated environment specifically designed to prevent model-generated code from compromising the host or reaching unauthorized resources. The sandbox persists state throughout a single agent session (variables, imports, file state survive across multiple tool calls within one task), but is still hermetic by Google's strong recommendation — no network access and no API calls by default, to prevent uncontrolled data exfiltration. For agents on GKE, the GkeCodeExecutor option goes further with gVisor for kernel-level sandbox isolation.

This is directly relevant to Fello's user-defined automation feature — if Fello ever moves from template-based automations to actually generating and running custom code per organization, this sandbox is the correct mechanism, with network access deliberately disabled unless explicitly required.

### Evaluation built into the framework

ADK has built-in evaluation tooling — you define a fixed set of prompts with expected behavioral properties (not exact string matches, but properties like "must call the correct tool" or "must not return data outside its scope") and run that evaluation set against every agent version change before rollout. For Fello this means you can build a small eval set per org type — "given a PTI-style WhatsApp message, the agent must create an event and not leak any other org's task data" — and gate any agent prompt changes against it before deploying.

---

## Multi-Tenant Security — What Google's Own Reference Architecture Says

Google Cloud published an official multi-tenant agentic AI reference architecture in June 2026, built specifically around ADK running inside the Gemini Enterprise Agent Platform. The core pattern is a hub-and-spoke model, and the principles map directly onto what Fello already needs.

### The isolation primitive

Google's default recommendation is one GCP project per tenant. The reasoning: a GCP project is the strongest isolation primitive Google Cloud offers — stronger than application-level checks, stronger than database row filtering alone. For Fello, full one-project-per-tenant is almost certainly overkill at the current stage and budget — this is the enterprise-scale version of tenant isolation. Fello's current architecture (JWT claims plus Firestore rules plus query scoping, all under one GCP project) is the appropriate equivalent at this stage. The principle to take from this — not the literal implementation — is that isolation should be enforced at the lowest possible layer, not just in application logic.

### Principal Access Boundary (PAB) policies

PAB policies are the mechanism Google's architecture uses to guarantee that an agent identity belonging to one tenant cannot reach resources belonging to another tenant, even by accident, even if the agent's reasoning goes wrong or its prompt is manipulated. This is the cloud-IAM-level equivalent of what Fello's Firestore security rules and Cloud SQL `org_id` scoping already do at the application level. The architectural lesson: don't rely on the agent "being told" not to access other tenants' data — enforce it at a layer the agent's own reasoning cannot override.

### Strict data isolation in practice

In Google's reference example (a large retail organization with multiple divisions), each agent resides in an isolated tenant project and only ever retrieves context from its own division's datastore. Two stated benefits map directly to Fello: specialized accuracy (the agent never confuses one org's data with another's because it's never exposed to it), and reduced blast radius (even if one tenant's agent identity were somehow compromised, it structurally cannot reach another tenant's resources).

### Hermetic agent environments

The strong recommendation across Google's documentation is that agent sandboxes and execution environments should have no network connections and no outbound API call capability unless explicitly required for the task. This prevents a compromised or misbehaving agent from exfiltrating data. For Fello's WhatsApp message processing pipeline, this means the Extraction Agent should only ever have the tools it needs (read message, write structured event) — not broad network or filesystem access.

### Observability and cost attribution per tenant

Production multi-tenant agent systems attribute every tool call to a specific tenant and end-user, typically via an OpenTelemetry wrapper around tool registration. This lets you answer "how much did org X's agent usage cost this month" and "which tenant triggered this tool call" after the fact. For Fello, this is worth building even at small scale — log `tenantId` and `orgId` alongside every Gemini call and every tool invocation from day one, since retrofitting this later is painful.

---

## How This Maps Onto Fello's Existing Architecture

Fello already has the application-layer version of everything Google's reference architecture describes at the infrastructure layer:

| Google's enterprise pattern | Fello's equivalent |
|---|---|
| One GCP project per tenant | One shared GCP project, full domain as `tenantId` field on every document and every JWT claim |
| Principal Access Boundary policies | Firestore security rules checking `tenantId` and `orgId` against JWT token, enforced at the database layer |
| Agent identity scoped to one tenant project | Every Cloud Run agent call carries the verified `tenantId` and `orgId` from the JWT — never trusted from client input |
| Hermetic sandboxed code execution | Reserved for the future user-defined automation feature — no network access by default if implemented |
| Per-tenant cost attribution via OpenTelemetry | Log `tenantId` and `orgId` on every Gemini call and tool invocation in Cloud Run |
| Strict datastore isolation per division | Cloud SQL queries always scoped by `org_id` from verified JWT, never from client request body |

The honest summary: Fello's current three-layer security model (JWT claims, Firestore rules, query scoping) is the right-sized version of Google's enterprise reference architecture for a competition build and early-stage product. The full one-project-per-tenant, VPC Service Controls, Principal Access Boundary version is what Fello would migrate toward if it scaled to serving large enterprise customers with strict data sovereignty requirements — not something to over-engineer for now.

---

## What This Means for Fello's ADK Agent Implementation

### Tool count discipline
Keep the orchestrator agent's directly-attached tools under roughly 10-15. This is not an arbitrary preference — it is the documented threshold where context degradation begins. Anything beyond that belongs in a specialized sub-agent, not bolted onto the orchestrator.

### State scoping discipline
Use `session.state` scoping deliberately:
- Event-specific conversation progress → session-scoped
- Member preferences and role context → user-scoped
- Nothing should ever be app-scoped in Fello — almost everything is org-specific, and app-global state risks leaking across tenants if misused
- Intermediate data passed between the orchestrator and a sub-agent within one request → temp-scoped, automatically discarded after

### Persistence requirement
Use DatabaseSessionService (backed by Cloud SQL or Firestore, not InMemorySessionService) so conversation state survives Cloud Run cold starts and horizontal scaling. InMemorySessionService is acceptable only during local development.

### Tenant binding on every tool call
Every ADK tool function Fello defines (createEvent, assignTask, retrieveDocument, etc.) must receive `tenantId` and `orgId` as parameters sourced from the verified JWT context passed into the agent invocation — never inferred from conversation text, never trusted from anything the model generates. The agent can decide *when* to call a tool, but the tenant and org scoping of that call must be deterministic and external to the model's reasoning.

### Sandbox discipline for future automations
If and when Fello implements fully custom user-generated automations (beyond the template-based approach used for the competition), any code execution must run in a hermetic sandbox with no network access by default, following Google's stated recommendation, with VPC Service Controls considered if Fello later scales to enterprise customers with stricter compliance needs.

### Per-tenant observability from day one
Wrap every tool registration with logging that captures `tenantId`, `orgId`, and the acting `userId` alongside the tool call. This costs almost nothing to build now and is expensive to retrofit later if Fello needs to debug a cross-tenant issue or bill usage per organization.


---

## Document Retrieval — RAG-Style System Without a Vector Database

### Why not a real vector database

A genuine RAG system with embeddings makes sense when you're searching semantically similar *content* across large volumes of unstructured text — "find me paragraphs that discuss similar themes to this one" even when no shared keywords exist. Fello's actual retrieval need is different and much simpler: someone in a WhatsApp group asks for a specific known document — "send the speaker brief," "where's the logo," "find the sponsorship proposal." These are keyword and metadata lookups against a small, well-structured, per-org dataset, not semantic similarity search across millions of documents.

Adding a vector database (Pinecone, Weaviate, or even pgvector) means an extra service to run, extra cost, extra latency from embedding generation on every file, and extra complexity in keeping the embedding index in sync with the actual files — all to solve a problem that PostgreSQL full text search already solves correctly for this scale. This was already decided earlier in the project: no vector database for now.

### What the system actually is

A hybrid retrieval pipeline: PostgreSQL full text search for fast keyword matching, combined with Gemini for understanding *what the user actually wants* when their phrasing doesn't match the filename exactly, plus the metadata context (which team, which event, which group) to disambiguate when multiple files could match.

### The documents table — extended for retrieval

This builds directly on the `documents` table already defined in the Claude Code prompt, with retrieval-specific additions.

```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  event_id TEXT NOT NULL, -- 'org_root' for organization-level files not tied to any event (see drive-sync.js walkFolderTree)
  team_node_id TEXT NOT NULL,
  file_name TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  drive_file_id TEXT NOT NULL,
  source TEXT NOT NULL,              -- 'whatsapp', 'drive_direct', 'form', 'generated'
  uploaded_by TEXT,
  group_jid TEXT,
  message_id UUID REFERENCES whatsapp_messages(id),

  -- Retrieval-specific fields
  description TEXT,                  -- short AI-generated description of what the file contains
  document_type TEXT,                -- 'logo', 'brief', 'proposal', 'form_response', 'poster', 'report', 'other'
  ai_extracted_summary TEXT,         -- for text-based files (PDFs, docs), a short summary Gemini generates once on upload

  search_vector TSVECTOR GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(file_name, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(ai_extracted_summary, '')), 'C')
  ) STORED,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_docs_org_event ON documents(org_id, event_id, created_at DESC);
CREATE INDEX idx_docs_fts ON documents USING GIN(search_vector);
CREATE INDEX idx_docs_team ON documents(org_id, team_node_id, created_at DESC);
CREATE INDEX idx_docs_type ON documents(org_id, event_id, document_type);
```

The weighted `search_vector` is the key upgrade over a plain filename-only index. Filename matches rank highest (weight A), the AI-generated description ranks second (weight B), and the deeper extracted summary ranks third (weight C). This means a search for "logo" matches a file named `final_design_v3.png` if its description says "PTI event logo, blue and white." Without this, only exact filename matches would work, and most files people upload through WhatsApp have unhelpful names like `IMG_2847.jpg`.

### What happens on file upload — building the index

When a file lands in the `whatsapp-documents` folder via the existing pipeline, before writing the documents row, one Gemini call classifies and describes it:

```
Input to Gemini: the file (image or document), plus context —
which event, which team group it came from, recent conversation 
around the upload (e.g. "here's the logo guys")

Output: 
{
  "document_type": "logo",
  "description": "PTI 2026 event logo, blue and white color scheme, circular badge design",
  "ai_extracted_summary": null  // only populated for text-heavy documents like PDFs
}
```

For images this is a single multimodal Gemini call (cheap, Flash-tier). For text documents (PDFs, Word docs, slides) an additional summary extraction runs once, also Flash-tier, and gets cached in `ai_extracted_summary` so it's never reprocessed.

This is the only AI cost in the indexing pipeline — one classification call per file at upload time, never repeated, never run again at query time.

### What happens at query time — retrieval

When someone asks the agent "send the speaker brief" in a WhatsApp group, or asks the dashboard chatbot "find the logo," the flow is:

```
1. Agent receives the natural language request
2. Agent extracts the likely search terms and document_type hint via Gemini
   ("speaker brief" → search terms: "speaker brief", likely document_type: "brief")
3. Run PostgreSQL full text search scoped to org_id + event_id:

   SELECT file_name, drive_file_id, document_type, description,
          ts_rank(search_vector, plainto_tsquery('english', $1)) AS rank
   FROM documents
   WHERE org_id = $2 AND event_id = $3
     AND search_vector @@ plainto_tsquery('english', $1)
   ORDER BY rank DESC
   LIMIT 5;

4. If exactly one strong match → agent retrieves it directly from Drive 
   and sends it back in the group, no further reasoning needed
5. If multiple plausible matches → agent asks for clarification:
   "I found 2 files that might be it — the speaker brief from last 
   week and one from yesterday's update. Which one?"
6. If no match → agent says so honestly rather than guessing:
   "I couldn't find a speaker brief for this event. Want me to check 
   if it was uploaded under a different name?"
```

This is a deterministic database query, not a semantic vector search, so it's fast (single-digit milliseconds with the GIN index) and the result is explainable — you can always show *why* a file matched (its filename, description, or summary contained the search terms), which a black-box vector similarity score cannot do as clearly.

### Tenant and org isolation in retrieval

Every retrieval query is scoped by `org_id` exactly like every other query in the system — sourced from the verified JWT context the agent operates under, never from anything the user's message says. A design team member in IAS asking the agent to "find the logo" can only ever retrieve documents where `org_id` matches their own org's internal UUID. This is the same three-layer isolation already established elsewhere in the architecture — applied identically here, not as a special case.

### Cross-event retrieval — explicitly scoped, not automatic

By default, retrieval is scoped to the current event only — someone in the PTI design group asking for "the logo" should get PTI's logo, not a logo from a different event months ago. Cross-event search ("find any logo we've used before") is a deliberately separate, explicit query path — only triggered when the user clearly asks across events ("show me logos from past events") — never the default behavior, to avoid surprising someone with results from an unrelated event.

### Why this is a stronger pitch than "we built RAG"

Saying "we use vector embeddings" sounds technically impressive but is the wrong tool here and a judge who understands retrieval systems will recognize that immediately for this use case. Saying "we use weighted full text search with AI-assisted classification at ingestion time, scoped by tenant and event" is both correct engineering for the actual problem and demonstrates that the system was designed deliberately rather than because "RAG" is a trend term. This is worth stating plainly if asked about the architecture in a technical Q&A.

