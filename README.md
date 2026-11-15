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
| `evaluation/` | **Evaluation & Guardrails**: evaluating LLMs, evaluating agents, guardrails |
| `agent/` | **The Carnet IA agent**: turns web pages into notes, with your approval ([guide](agent/README.md)) |
| `assets/` | Site design: colors, fonts, logo |
| `.github/` | The "New source" issue form and the two automations (agent, site publishing) |

The site is organised by **concept**, not by course: each topic page (`llms/index.qmd`,
`agents/index.qmd`, `evaluation/index.qmd`) declares its sections, and each note lives in the
folder of its section, e.g. `agents/memory/short-term-memory.qmd`.

## Adding a note

1. Open an issue with the **New source** form: a URL, and optionally other URLs and instructions in *Notes*.
2. The agent posts a **plan** on the issue. Reply `/approve`, `/replan …` or `/cancel`.
3. After `/approve`, it writes the page and opens a **pull request**. Merge it to publish.

## How the site is built

The site is built with [Quarto](https://quarto.org). Every push to `main` rebuilds and publishes it
through GitHub Actions (`.github/workflows/publish.yml`).
