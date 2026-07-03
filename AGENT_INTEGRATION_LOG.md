# Fello — Agent Integration & Google Forms Work Log

Summary of the work done to build, deploy, and wire up the Fello AI agent (Google
ADK + NVIDIA NIM) into the dashboard chat, and to add Google Forms create/edit
with rich UI. Newest work is at the top of each section.

Competition framing: **AI for Better Living and Smarter Communities / Decision
Intelligence** (Google Cloud), demo narrative = PTI (Parents–Teachers Interaction)
event coordination for an IEEE / volunteer / civic org.

---

## 1. Architecture at a glance

```
Dashboard chat  ──►  /api/chat (Next.js)  ──►  Vertex AI Agent Engine  ──►  Fello ADK agent
 (useChat,             buffers reply,           (deployed agent.py)          (NVIDIA NIM model
  TextStreamChat        splits thinking /                                     via LiteLlm)
  Transport)            tool-calls / answer                                        │
       ▲                       │                                                   ▼
       │                       └── NIM fallback path if Agent Engine unavailable   tools/skills
   Dynamic UI blocks  ◄── [BLOCK:*] markers in the reply                     (Firestore, WhatsApp,
   (dynamic-ui.tsx)                                                           Google Forms, analytics)
```

- **Agent**: a single flat ADK `Agent` (not sub-agents — nesting multiplied NIM
  cold-starts into 2–3 min turns). Tenant/org scope is bound from verified
  `session.state`, never from model output. `before_tool` fails closed if scope
  is missing.
- **Model**: NVIDIA NIM via `LiteLlm` (`openai/<model>` against
  `https://integrate.api.nvidia.com/v1`). Current primary:
  `nvidia/nemotron-3-super-120b-a12b` (chain-of-thought comes back as separate
  `thought=true` parts → rendered as collapsible "thinking"). Fallback:
  `meta/llama-3.3-70b-instruct`.
- **UI protocol**: the agent emits `[BLOCK:type]{json}[/BLOCK]` markers and
  `[SUGGESTIONS]a|b|c[/SUGGESTIONS]`, parsed by `parseBlocks` in
  `components/dynamic-ui.tsx` into live shadcn + recharts components.

---

## 2. Agent deployment (Vertex AI Agent Engine)

- Deploy via `fello-agent/deploy.py` using `from vertexai import agent_engines` +
  `AdkApp`; `agent_engines.create(app, requirements=, extra_packages=, env_vars=, display_name=)`.
- `requirements` includes `google-cloud-aiplatform[agent_engines]>=1.93.0`
  (the `vertexai` module ships inside it — do **not** add standalone `vertexai`,
  which pins an old aiplatform).
- `extra_packages=["agent.py","context.py","authz.py","observability.py","demo_fallback.py","skills"]`
  so the container can import the local modules/skills.
- `env_vars` is filtered to non-empty values. `GOOGLE_CLOUD_PROJECT` is
  **reserved** — must not be passed.
- ADC is used (no service-account key). `GOOGLE_APPLICATION_CREDENTIALS` is left
  unset/commented in `.env` so deploy uses Application Default Credentials.

### Deployment gotchas fixed
| Symptom | Fix |
|---|---|
| `externally-managed-environment` on pip | use a venv; bootstrap pip via `get-pip.py` |
| `vertexai.preview.agent_engines` gone (1.158) | use stable `vertexai.agent_engines` + `env_vars=` |
| Agent Engine rejects empty env vars | filter to non-empty |
| `GOOGLE_CLOUD_PROJECT is reserved` | remove it from env_vars |
| `ModuleNotFoundError: vertexai` in container | add `google-cloud-aiplatform[agent_engines]` |
| `ModuleNotFoundError: skills` | add `extra_packages` |
| Model 404 / 403 | rotate NVIDIA key, use real model ids |

---

## 3. Dashboard chat integration (frontend)

Files: `app/org/[tenantNamespace]/[orgSlug]/page.tsx`, `app/api/chat/route.ts`,
`lib/agent-engine.ts`.

- Chat uses `useChat` from `@ai-sdk/react` with a real **`TextStreamChatTransport`**
  (the earlier bug: a plain function was passed, so no network request fired).
  `prepareSendMessagesRequest` injects the Bearer ID token + `{orgId, eventId, sessionId}`.
- Messages read from `message.parts`, not `.content`.
- `/api/chat` (`maxDuration=300`): explicit, observable path selection
  (`[chat] agent path ok …` vs `[chat] using NIM fallback — reasons:`), fast-fails
  NIM when no key. Builds output as `[BLOCK:thinking]` + one `[BLOCK:tool_call]`
  per tool + the answer text.
- `getAgentReply()` in `lib/agent-engine.ts` returns `{ text, reasoning, toolCalls }`,
  parsing Agent Engine events (`function_call.name` → toolCalls, `p.thought` →
  reasoning, other text → answer). It **eagerly drains the body**
  (`await upstream.text()`) to avoid `UND_ERR_BODY_TIMEOUT`, with a 120 s abort.
- A **thinking skeleton** shows while awaiting the reply.

### Chat fixes
- Transport fix (`a0c4698`), thinking skeleton (`d4fe987`), explicit/observable
  path (`7dedccf`), buffer reply to fix body-timeout (`06f4108`).

---

## 4. Dynamic UI blocks (`components/dynamic-ui.tsx`)

`parseBlocks` turns `[BLOCK:type]{json}[/BLOCK]` and `[SUGGESTIONS]…[/SUGGESTIONS]`
into components. The regex is tolerant of a missing leading `[` / trailing `]`
on the suggestion markers (the model sometimes emits them malformed).

Block types: `text, stats, task, task_list, member_grid, event, event_list,
timeline, progress, outreach_pipeline, bar_chart, donut_chart, line_chart, alert,
actions, suggestions, thinking, tool_call, form, form_result`.

Notable components:
- **`ThinkingBlock`** — collapsible "Thought for a moment" accordion; strips stray
  block/suggestion markers out of the reasoning text.
- **`ToolCallBlock`** — themed chip with a `TOOL_META` map (tool name → label +
  icon). Supports a `brand` flag to render a full-color brand icon without the
  tinted square wrapper.
- **`FormBlock`** — renders labeled inputs like `/projects/new`; on submit it
  freezes the fields and sends a built instruction message back to the agent.

---

## 5. Google Forms integration

### Backend (agent skill) — `fello-agent/skills/google_workspace.py`
- **`create_google_form(title, description, questions, tool_context)`** — creates
  the form (API accepts only the title at create time), then `:batchUpdate` for
  description + short-answer questions. Returns
  `{success, form_id, responderUri, editUri}`.
- **`update_google_form(form_id, title, description, add_questions, tool_context)`**
  — edits an **existing** form (rename / change description / append questions) by
  `form_id`. Never creates a new form, never deletes. Appends questions after the
  form's current item count. Added so "rename this form" edits in place instead of
  spawning a duplicate.
- Both gate on `authz.CAP_DOCUMENTS_MANAGE`, resolve the org from verified context,
  and use the org's connected Google OAuth grant (`google_integrations/{orgId}`,
  refreshed via `_google.get_access_token`). Registered in `skills/__init__.py`
  and `agent.py`.

### Frontend test harness (bypasses the agent)
- `lib/google.ts` — `getOrgAccessToken(orgId)` + `createGoogleForm(token, …)`
  mirror the Python skill.
- `app/api/test-google-form/route.ts` — verifies the Bearer ID token,
  `resolveOrgScope`, gets the token, creates the form.
- `app/test-google-form-api/page.tsx` — one-click test page (prefills the user's
  first org). **Confirmed working end-to-end.**

### Enabling the API
Root cause of early "cannot create the form" was the Forms API not being enabled:
`gcloud services enable forms.googleapis.com drive.googleapis.com docs.googleapis.com`
in project `fello-pt`. Plus the admin-permissions fix below.

### Form result UI — `[BLOCK:form_result]`
- New block that renders the responder (share) and edit links as **Open / Edit
  buttons with Copy-link buttons** (clipboard copy with a "Copied" check).
- `extractFormResults` also **auto-lifts bare Google Forms links out of plain
  agent text** into the same card — so it renders as buttons even before the agent
  emits the explicit marker (works with the currently deployed agent).
- Prompt guidance: after create/update succeeds, emit `[BLOCK:form_result]` with
  the exact returned URLs (never invent URLs); for edits call `update_google_form`
  on the existing `form_id`.

---

## 6. Real Google brand icons

- `components/icons/google-icons.tsx` — **`GoogleFormsIcon`** (purple gradient
  rounded-square glyph with white bullets + lines, per-instance gradient id via
  `React.useId()`) and **`GoogleDriveIcon`** (canonical tri-color Drive triangle).
- The Forms icon is used in the `form_result` card header and the
  `create_google_form` / `update_google_form` tool chips, rendered without the
  tinted wrapper. Drive icon is available for future use.

---

## 7. Permissions & security

- `resolveOrgScope` uses `capabilitiesFor(access, capabilities)` → returns `["*"]`
  (wildcard) when access is `full`/`owner`/`admin`, otherwise the explicit list.
  This fixed form creation being blocked for the org admin (whose membership had
  `access: "full"` but no explicit `documents.manage`).
- Invariants preserved: tenant/org scope comes only from verified server context
  (JWT / `session.state`), never from the model; `before_tool` fails closed;
  full-access admins get wildcard capability.

> ⚠️ **Action item:** the first NVIDIA API key was printed to logs at one point —
> it should be rotated.

---

## 8. Model journey (NVIDIA NIM)

| Model | Result |
|---|---|
| `meta/llama-3.3-70b-instruct` | clean, but 30–53 s cold starts (now the fallback) |
| `meta/llama-3.1-8b-instruct` | instant but loops / hallucinated fake form links |
| `nvidia/llama-3.3-nemotron-super-49b-v1.5` | chain-of-thought leaked into content |
| **`nvidia/nemotron-3-super-120b-a12b`** | **current** — reasoning separated as `thought=true` parts, makes real tool calls, ~15–22 s |

Planned: swap in Gemini via `_make_model` for speed — to be bundled with the next
redeploy.

---

## 9. Commit map

**Agent / main repo**
- `adbab13` advance pointer — Google brand icons in form cards
- `6992c80` add `update_google_form` skill + form_result card guidance
- `7ad9022` advance pointer — forms test page, form cards, suggestions fix
- `ebddc75` emit `[BLOCK:form]` card to collect inputs
- `95ba167` advance pointer — admin perms, thinking + tool-call UI
- `579e6c5` add Google Forms skill (org's connected Google account)
- `83f306e` / `c68c170` / `4de8b61` / `c8f2257` chat fixes (buffer, path, skeleton, transport)
- `334c3de` working NVIDIA model ids + bundle local modules for deploy
- `1a60190` update deploy.py for current vertexai agent_engines API

**Frontend repo**
- `05af78f` real Google Forms brand icon in form cards
- `c1d35a3` render Google Form links as open/edit/copy buttons
- `4455e28` Forms test page, interactive form cards, robust suggestions
- `4bdb7e9` admin permissions, collapsible thinking, tool-call chips
- `06f4108` buffer agent reply (undici body-timeout)
- `7dedccf` explicit, observable `/api/chat` path
- `d4fe987` thinking skeleton
- `a0c4698` real `ChatTransport`

---

## 10. Status & next steps

**Working:** agent deployed; dashboard chat connected + tenant-safe; nemotron makes
real tool calls; Google Forms create + test page confirmed end-to-end; thinking +
tool-call UI; interactive form cards; form result cards with Open/Edit/Copy buttons
and real brand icons; suggestions parsing.

**Needs a redeploy to activate** (frontend already handles them):
1. `update_google_form` edit-in-place behavior.
2. Agent emitting `[BLOCK:form]` and `[BLOCK:form_result]` markers.
3. (Optional, same redeploy) the Gemini `_make_model` swap.

**Reminder:** rotate the NVIDIA API key that was exposed in logs.
