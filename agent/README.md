# Carnet IA agent

A LangGraph agent that turns a web page into a proposed note for the site, then opens a pull request.

## Use it

1. Open a new issue with the **New source** form and paste a URL.
2. The agent runs in GitHub Actions (a few minutes) and comments with a link to a pull request.
3. Read the pull request. **Merge** to publish, or close it to discard.

## The graph

```
fetch → read → categorize → find_gaps ─┬→ search → select → write → review ─┬→ finalize → publish
                                       └─────────(no gaps)──────↑           │
                                                                ├─ write ◄──┤  text issues
                                          research_critique → search ◄──────┘  missing topics
```

| Node | Kind | Job |
|---|---|---|
| `fetch` | code | Downloads the page text (Tavily Extract, plain download as fallback) |
| `read` | LLM | Structured notes: summary, key points, definitions, code |
| `categorize` | code + LLM + code | Lists existing pages → decides update/create, topic, folder → checks the decision |
| `find_gaps` | LLM | What a learner would miss → up to 3 search queries |
| `search` | code | Runs the queries |
| `select` | LLM + code | Keeps useful facts with their URL → drops any URL that wasn't in the results |
| `write` | LLM + tools | Writes or rewrites the page; may call `web_search` / `fetch_url` |
| `review` | code + LLM + tools | Mechanical checks, then a critical review |
| `research_critique` | LLM | Searches for topics the reviewer found missing |
| `finalize` | code | Front matter, pills, **Sources section**, menus |
| `publish` | code | Branch, commit, pull request |

Rule of thumb used everywhere: **always happens → code; needs judgment → LLM; the LLM decides if it needs it → tool.**

## Files

| File | Contents |
|---|---|
| `carnet_agent/state.py` | Graph state and the structured outputs the LLM fills |
| `carnet_agent/graph.py` | The nodes and the graph |
| `carnet_agent/prompts.py` | One system prompt per role |
| `carnet_agent/site.py` | Code-only site operations: page index, sources, menus |
| `carnet_agent/web.py` | Fetch and search functions, and the tools given to the LLM |
| `carnet_agent/publish.py` | Pull request creation |
| `carnet_agent/config.py` | Models and limits |
| `STYLE.md` | Writing rules the agent reads every time (procedural memory) |
| `tests/test_offline.py` | Runs the whole graph with fake models: no API key needed |

## Run locally (optional)

```bash
cd agent
pip install -r requirements.txt
python tests/test_offline.py                                  # free, no keys
python -m carnet_agent.run https://example.com --dry-run       # needs OPENAI_API_KEY and TAVILY_API_KEY
```

## Secrets

The workflow needs two repository secrets: `OPENAI_API_KEY` and `TAVILY_API_KEY`
(Settings → Secrets and variables → Actions).
