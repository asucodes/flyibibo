# flyibibo

An AI travel agent. You describe a trip in a sentence; it asks for whatever
you left out, researches the destination in parallel, and hands back a single
page pitching a complete plan — flights, day-by-day itinerary, food, hotels
and a budget.

Prototype. Not deployed, not a product.

---

## How it works

One model, one endpoint, many agents. What separates the agents is not the
model — it is the **context slice** each one receives, the **tools** it can
call, the **schema** it must satisfy, and the **temperature** it runs at. That
is the whole design, so the schemas in `travel/schemas.py` are the
load-bearing part of this repository.

```
prompt ──▶ brief extractor ──▶ clarify (gaps only) ──▶ TripBrief
                                                          │
                        ┌──────────────┬──────────────┬───┴──────────┐
                        ▼              ▼              ▼              ▼
                     flights      attractions        food          hotels
                        └──────────────┴──────┬───────┴──────────────┘
                                              ▼
                                      route optimizer
                                     (clusters by district,
                                      respects closed days)
                                              ▼
                                        budget agent
                                              ▼
                                     master synthesizer
                                    (emits Itinerary JSON)
                                              ▼
                                    template renders the page
```

Two properties are deliberate.

**It is a pipeline, not an autonomous swarm.** Every stage is a function from
one typed input to one typed output. That makes it cacheable, debuggable and
deterministic. Agents that choose their own next steps buy you nondeterminism
you cannot debug in a prototype.

**The model never writes HTML.** The synthesizer emits `Itinerary` JSON; a
template renders it. So restyling the page is a CSS edit rather than a re-roll,
and a truncated model response degrades one field instead of the whole page.

---

## Layout

| Path | Role |
|---|---|
| `travel/schemas.py` | Typed contracts — the actual design |
| `travel/flights.py` | `FlightProvider` interface + seeded mock |
| `travel/photos.py` | Wikimedia Commons photography (keyless) |
| `travel/agents.py` | The five-row agent config table |
| `travel/pipeline.py` | Fan-out / fan-in orchestration |
| `gpt_researcher/` | Base harness: LLM providers, retrievers, actions |
| `backend/` | FastAPI server and streaming endpoints |
| `frontend/nextjs/` | Next.js UI and the itinerary route |

---

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env      # then fill in the two keys below
```

Two keys are required:

```bash
GROQ_API_KEY=             # fast tier  -> parallel fan-out agents
OPENROUTER_API_KEY=       # smart tier -> synthesizer
```

Everything else is keyless by design. Flights run off a seeded mock, POI
grounding comes from Wikivoyage, photography from Wikimedia Commons, and web
search from DuckDuckGo.

Run it:

```bash
python -m uvicorn backend.server.app:app --reload --port 8000
cd frontend/nextjs && npm install && npm run dev
```

---

## Configuration

Model routing is per-tier. The value is `<provider>:<model>`, split on the
first colon, so OpenRouter model IDs containing a slash work unmodified.

| Variable | Default | Notes |
|---|---|---|
| `FAST_LLM` | `groq:openai/gpt-oss-120b` | Parallel agents; speed matters |
| `SMART_LLM` | `openrouter:google/gemini-3.8-flash` | Synthesizer; 1M context |
| `STRATEGIC_LLM` | `openrouter:google/gemini-3.8-flash` | Planning and slot filling |
| `TEMPERATURE` | `0.2` | Low on purpose — see below |
| `RETRIEVER` | `duckduckgo` | Keyless |
| `FLIGHT_PROVIDER` | `mock` | Swap to `serpapi` for live fares |

Temperature is global and held low. Research stages should be boring — a
creative flights agent invents restaurants that do not exist at prices that
are not real. The creative budget belongs to the synthesizer alone, and it is
expressed in that stage's prompt rather than in a higher global temperature.

---

## Status

| Area | State |
|---|---|
| Schemas and mock flights | Working |
| Pipeline orchestration | In progress |
| Itinerary page | In progress |
| Live flight data | Stubbed (`SerpApiFlightProvider`) |
| Persistence | None — in-memory only |

---

## Attribution

Built on [gpt-researcher](https://github.com/assafelovic/gpt-researcher)
(Apache-2.0), which supplies the harness: LLM provider layer, retriever
abstraction, FastAPI backend and Next.js frontend. Retained as a remote for
pulling upstream fixes:

```bash
git remote add upstream https://github.com/assafelovic/gpt-researcher.git
git fetch upstream && git merge upstream/master
```

Upstream's own documentation, eval suite and community files were removed from
this tree — they describe a research tool, not this one. The original license
is retained in `LICENSE`.

The interface follows a dark editorial design system: near-black canvas, a
light-weight serif for display, and monospaced uppercase labels for data.
