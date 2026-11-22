# Carnet IA

A learning notebook on applied AI, published at **https://salouaaifqui.github.io/carnet-ia/**

> 📘 **How the agent that writes the notes is built:** see the detailed guide (in French) in
> [`agent/README.md`](agent/README.md): the graph, each step (code, LLM or tool), routing,
> human approval, sources, tests.

## What's in this repository

| Folder | What it contains |
|---|---|
| `llms/` | **LLMs**: how LLMs work, foundation models, open-source models |
| `agents/` | **Agents**: foundations, memory, control |
| `evaluation/` | **Measure What Matters**: evaluation frameworks, evaluating LLMs, evaluating agents |
| `guardrails/` | **Ship with Guardrails**: the section page. Its notes live in `evaluation/guardrails/`, so their URLs never changed |
| `toolbox/tools/` | One card per tool or framework, shown in its theme (`tool-theme:`) under "Tools in practice" |
| `agent/` | **The Carnet IA agent**: turns web pages into notes, with your approval ([guide](agent/README.md)) |
| `assets/` | Site design (colors, fonts, logo) and the synthesis visual of each note |
| `_scripts/`, `_filters/`, `_includes/`, `_templates/` | Reading layout: reading times, meta line, code steps, progress bar, numbered paths |
| `reference/`, `docs/` | The redesign brief, its mockups and the grammar of the visuals |
| `.github/` | The "New source" issue form and the two automations (agent, site publishing) |

The site is organised by **concept**, not by course: each topic page (`llms/index.qmd`,
`agents/index.qmd`, `evaluation/index.qmd`, `guardrails/index.qmd`) declares its sections, and each note lives in the
folder of its section, e.g. `agents/memory/short-term-memory.qmd`.

## Adding a note

1. Open an issue with the **New source** form: a URL (or a course page), and optionally other URLs and
   instructions in *Notes*.
2. The agent posts a **plan**: where the content goes, the parts it will write, and extra facts found on
   the web. Reply `/approve`, `/approve F1 F3` (to keep some web facts), `/replan …` or `/cancel`.
3. The agent writes the page and opens a **pull request**, with a link to a **preview** of the page on the
   site. Read it, then merge to publish.

## How the site is built

The site is built with [Quarto](https://quarto.org). Every push to `main` rebuilds and publishes it
through GitHub Actions (`.github/workflows/publish.yml`).
