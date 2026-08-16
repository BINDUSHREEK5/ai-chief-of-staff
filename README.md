<div align="center">

# 🧠 AI Chief of Staff

### An autonomous executive assistant that monitors your email, reasons about what matters, and only interrupts you when it has to.

*Built for the [Caspian Buildathon](https://caspian.devpost.com) · One handler · Two channels · Zero mocked demos*

</div>

---

## The Problem

Professionals receive hundreds of emails a day. Most tools forward everything, notify you about everything, and leave the judgment to you. The result: constant interruptions, missed priorities, and decision fatigue.

**AI Chief of Staff** flips this. Instead of forwarding messages, it reasons about them — and only reaches you when something genuinely needs you.

---

## What It Does

When an email arrives, the agent runs a four-stage autonomous pipeline:

```
📧 Email arrives
      │
      ▼
🧠 Classify Intent     — What does the sender want? (request / FYI / scheduling / spam)
      │
      ▼
⚡ Assess Urgency      — How time-sensitive is this? (0.0 → 1.0 score)
      │
      ▼
🤔 Reason & Decide     — One of four decisions:
      │
      ├─ AUTO_REPLY          → Drafts and sends immediately (routine, low-stakes)
      ├─ DRAFT_FOR_APPROVAL  → Drafts reply, sends approval card to Telegram
      ├─ NOTIFY_ONLY         → Pings you on Telegram, no reply drafted
      └─ IGNORE              → Logged silently, surfaces in daily digest
      │
      ▼
💾 Save Memory         — Learns contact importance, preferences, approved patterns
```

The approval card on Telegram has three buttons — **✅ Approve / ✏️ Edit / ❌ Reject**. Tapping Approve delivers the drafted reply directly back to the **original email thread** — not just to Telegram.

Over time, the agent learns from every approved reply and gets better at auto-replying to similar messages without asking.

---

## Why This Is Different

| Most email agents | AI Chief of Staff |
|---|---|
| Forward everything | Decides what matters |
| Notify you constantly | Interrupts only when necessary |
| Static rules | LLM reasoning per message |
| No memory | Learns from approvals |
| One channel | Email + Telegram, one handler |
| Mock demos | Real emails, real replies |

**Channel-specific approval logic:** Telegram messages (internal, to the owner) never need approval — a reply goes straight back to you. Email replies (external, reaching third parties) require sign-off when sensitive. This distinction is intentional and architecturally enforced.

---

## Live Demo

**Agent inbox:** `agt-5d4b15b9bce419dad54dc3c3-137f87@agents.trycaspianai.com`

### Scenario 1 — Sensitive email → Approval flow
1. Send from any Gmail to the agent inbox:
   - **Subject:** `URGENT: Please confirm the contract terms for Acme`
   - **Body:** `We need your sign-off before end of day. This is time-sensitive.`
2. Within seconds: Telegram shows a drafted reply with ✅ Approve / ✏️ Edit / ❌ Reject buttons
3. Tap **Approve** → the reply lands in the original sender's inbox

### Scenario 2 — Routine email → Auto-reply
1. Send: `Does 3pm Tuesday work for a quick call?`
2. Agent auto-replies within seconds — no human action needed

### Scenario 3 — Low priority → Silent
1. Send a newsletter or FYI-style message
2. No Telegram ping — surfaces in the 7am daily digest instead

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Caspian SDK                          │
│         One CommClient · One on_message handler         │
│              Email ←──────────→ Telegram                │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              LangGraph StateGraph                       │
│                                                         │
│  classify_intent → retrieve_memory → assess_urgency     │
│                                           │             │
│                                        reason           │
│                                           │             │
│              ┌────────────────────────────┤             │
│              │            │         │     │             │
│         auto_reply  draft_for_  notify  ignore          │
│              │       approval    only     │             │
│              │            │       │       │             │
│           draft        draft   notify     │             │
│              │            │       │       │             │
│           send      request_     ─┴───────┘             │
│              │       approval                           │
│              └────────────┴──────→ save_memory          │
└─────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              SQLite Memory Store                        │
│  contacts · preferences · conversations · decisions     │
│  approved_patterns · approvals · daily_digest           │
└─────────────────────────────────────────────────────────┘
```

### Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Communication** | [Caspian SDK](https://github.com/TryCaspian/caspian-sdk) | One handler for every channel |
| **Orchestration** | [LangGraph](https://langchain-ai.github.io/langgraph/) | Stateful multi-step agent pipeline |
| **LLM Inference** | [Featherless.ai](https://featherless.ai) | OpenAI-compatible, 40k+ open-source models |
| **LLM Model** | `Qwen/Qwen2.5-7B-Instruct` | Fast, capable, runs concurrently |
| **API Server** | [FastAPI](https://fastapi.tiangolo.com) | Async lifespan, auto Swagger docs |
| **Memory** | SQLAlchemy 2.0 async + SQLite | Postgres-ready via dialect swap |
| **Validation** | Pydantic v2 | Typed schemas for all LLM outputs |
| **Testing** | pytest + pytest-asyncio | 18 tests, deterministic fake LLM |
| **Language** | Python 3.12 | Latest async/typing features |

---

## Project Structure

```
ai-chief-of-staff/
│
├── app/
│   ├── main.py           # FastAPI app, lifespan wiring, HTTP endpoints
│   ├── channels.py       # Caspian SDK — the ONE on_message handler
│   ├── graph.py          # LangGraph decision pipeline (8 nodes)
│   ├── memory.py         # SQLAlchemy async ORM + Memory facade
│   ├── approval.py       # Approve/Edit/Reject card + command parser
│   ├── llm.py            # Featherless.ai wrapper with structured-output retries
│   ├── prompts.py        # System prompts (one per decision point)
│   ├── models.py         # Pydantic schemas + LangGraph AgentState
│   ├── summary.py        # Daily digest formatting
│   ├── config.py         # All settings from environment variables
│   └── logging_config.py # Structured logging setup
│
├── database/
│   └── schema.sql        # Reference schema (auto-created at startup)
│
├── tests/
│   ├── conftest.py       # Shared fixtures (isolated temp SQLite per test)
│   ├── test_memory.py    # ORM + Memory facade tests
│   ├── test_approval.py  # Approval command parsing tests
│   └── test_graph.py     # Full pipeline tests with fake LLM
│
├── docs/
│   └── DEPLOYMENT.md     # Render / Railway / Docker deployment guide
│
├── .env.example          # All environment variables documented
├── requirements.txt      # Pinned dependencies
├── Dockerfile            # Container image
├── docker-compose.yml    # Local one-command run
├── pytest.ini            # asyncio_mode = auto
└── render.yaml           # Render deployment config
```

---

## Quickstart

### Prerequisites
- Python 3.12
- A [Caspian](https://trycaspianai.com) account and API key
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A [Featherless.ai](https://featherless.ai) account (use promo code `AIBUILD26` for 1 month free)

### Installation

```bash
git clone https://github.com/YOUR_USERNAME/ai-chief-of-staff
cd ai-chief-of-staff

# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate
# Activate (Mac/Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Open `.env` and fill in:

```env
# Required
CASPIAN_API_KEY=your_caspian_key_here
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
FEATHERLESS_API_KEY=fw-your_featherless_key_here

# Optional (these defaults work out of the box)
FEATHERLESS_MODEL=Qwen/Qwen2.5-7B-Instruct
DATABASE_URL=sqlite+aiosqlite:///./agent.db
LOG_LEVEL=INFO
```

### Run

```bash
# Run tests first — should show 18 passed
pytest

# Start the agent
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for the interactive API explorer.

**Important:** Send any message to your Telegram bot once after startup so the agent knows where to reach you.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Liveness check — returns `{"status": "ok"}` |
| `GET` | `/approvals` | List all pending approval drafts |
| `GET` | `/approvals/{code}` | View a draft in the browser with approve/reject form |
| `POST` | `/approvals/{code}/action` | Approve / edit / reject via HTTP (fallback to Telegram) |
| `GET` | `/summary/daily` | Get the daily digest (add `?push=true` to send to Telegram) |
| `POST` | `/dev/simulate-message` | Test the pipeline without real email (dev only) |

### Simulate a message (no real email needed)

```bash
curl -X POST "http://localhost:8000/dev/simulate-message" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "email",
    "sender": "boss@company.com",
    "text": "URGENT: Can you confirm the Acme contract terms by EOD?",
    "conversation_id": "test-001"
  }'
```

---

## Memory System

The agent remembers across conversations:

| What | Where | How it's used |
|---|---|---|
| **Contacts** | `contacts` table | Importance score (0-1) affects urgency decisions |
| **Preferences** | `preferences` table | User's stated style/tone/priority preferences |
| **Conversations** | `conversations` table | Thread continuity across email and Telegram |
| **Approved patterns** | `approved_response_patterns` | Enables auto-reply for similar future messages |
| **Decision log** | `decisions` table | Full explainability — every decision has a reason |
| **Approvals** | `approvals` table | Pending/resolved drafts with status tracking |

To migrate from SQLite to PostgreSQL, change one line in `.env`:
```env
DATABASE_URL=postgresql+asyncpg://user:pass@host/db
```
No code changes needed — SQLAlchemy handles the dialect.

---

## Approval Workflow

When the agent decides a reply needs human review:

1. It creates an approval record in the database
2. Sends a card to Telegram with the drafted reply and three buttons
3. The user taps **✅ Approve**, **✏️ Edit**, or **❌ Reject**
4. Tapping sends `approve:CODE` / `edit:CODE` / `reject:CODE` back to the bot
5. The agent delivers the approved/edited reply to the **original email thread**

Alternatively, type in Telegram chat:
```
approve A1B2C3D4
edit A1B2C3D4: your revised text here
reject A1B2C3D4
```

Or use the browser fallback at `GET /approvals/{code}`.

---

## Testing

```bash
pytest -v
```

18 tests across three suites:

- **`test_memory.py`** — contact idempotency, preference CRUD, conversation threading, approval lifecycle, pattern matching, importance score clamping
- **`test_approval.py`** — button callback parsing, typed commands, edit with replacement text, rejection, invalid input handling
- **`test_graph.py`** — all four routing branches (auto-reply, draft-for-approval, notify-only, ignore), Telegram bypass rule, conversation reuse across messages

All LLM calls use a deterministic fake — no API spend, no network needed, no flakiness.

---

## Deployment

### Render (Recommended)

Create `render.yaml` in the project root:

```yaml
services:
  - type: web
    name: ai-chief-of-staff
    runtime: python
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    disk:
      name: agent-db
      mountPath: /data
      sizeGB: 1
```

Then:
1. Push to GitHub (repo must be public for submission)
2. render.com → New → Web Service → connect repo
3. Add environment variables in the Environment tab
4. Set `DATABASE_URL=sqlite+aiosqlite:////data/agent.db`
5. Deploy — verify at `https://your-app.onrender.com/health`

### Docker

```bash
docker compose up --build
```

Full deployment guide: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)

---

## How It Helps

- **Executives and founders** who receive 200+ emails a day and need triage without hiring an EA
- **Solo developers** who want to stay focused without missing critical client messages
- **Remote teams** where async communication is the norm and response time matters
- **Anyone** who has ever missed an urgent email because it was buried under newsletters

The agent doesn't just filter — it drafts. By the time you see an approval request, the reply is already written. One tap and it's sent.

---

## Hackathon Compliance

| Requirement | Status |
|---|---|
| Uses Caspian SDK | ✅ `app/channels.py` — `CommClient` |
| One handler for all channels | ✅ Single `on_message` callback |
| Two or more channels | ✅ Email + Telegram |
| Actually runs (no mocked demos) | ✅ Real email, real Telegram, real LLM |
| Creative use case | ✅ Autonomous reasoning + approval workflow |
| Open source | ✅ MIT License |
| Deployable | ✅ Render / Railway / Docker |

---

## License

MIT — see [`LICENSE`](LICENSE)

---

<div align="center">

Built with ❤️ using [Caspian SDK](https://github.com/TryCaspian/caspian-sdk) · Inference by [Featherless.ai](https://featherless.ai)

⭐ If you found this useful, please star the [Caspian SDK repo](https://github.com/TryCaspian/caspian-sdk)

</div>
