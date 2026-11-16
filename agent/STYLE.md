# Carnet IA style guide

Every writer of a part reads this file. Edit it to change how the agent writes, without touching
the code (it is the agent's procedural memory).

The structure of a page (summary, key concepts, "Remember", sources, menus) is built by the
editor and by code: writers only write their part.

## Tone
- **English**, plain, for a reader who is learning. Short sentences, active voice.
- Explain a term the first time it appears.
- No anecdotes about the author's own debugging (failed cells, kernel restarts, missing keys…).

## Content
- Only knowledge that lasts: concepts, patterns, current APIs.
- Keep the source's important details: numbers, conditions, caveats, steps, named tools.
- **Code is always the current, working version.** If the source uses an old API, write the current one.
- Never invent facts, numbers, function names or URLs. Never cite this website or its repository.
- Examples from the source go inside the part they illustrate.

## Visual and concrete
- Each part has a concrete example (real names, inputs and outputs, numbers) in an example box.
- Prefer showing over telling: a diagram for a flow, a table for a comparison, steps for a procedure,
  a before/after for a good and a bad practice.
- Use `###` sub-parts when needed, never deeper.

## Components (Quarto markdown)

Example box:
```
::: {.example}
**A title for the example.** The scenario, in two or three sentences.
:::
```

Before/after:
```
::: {.compare}
::: {.col .bad}
**Without it**

What goes wrong.
:::
::: {.col .good}
**With it**

What changes.
:::
:::
```

Steps:
```
::: {.steps}
1. **First step**: what happens.
2. **Second step**: what happens.
:::
```

Diagram: a ```` ```{mermaid} ```` block (flowchart or sequenceDiagram; avoid subgraphs).

Warning: `::: {.callout-warning}` with `## Watch out` as its first line.
