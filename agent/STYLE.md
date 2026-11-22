# Carnet IA style guide

Every writer of a part reads this file. Edit it to change how the agent writes, without touching
the code (it is the agent's procedural memory).

## The skeleton of a note

Every note has the same skeleton, so a reader always knows where they are:

1. **Header** (front matter): title, one-sentence subtitle, `image: /assets/visuals/<slug>.svg`, `order`.
2. **Synthesis visual**: `::: {.synthesis}` with the SVG and a one-sentence caption (illustrator + editor).
3. **In 30 seconds**: `::: {.in30}`, exactly 3 bullets of 25 words max. Never "This page explains…" (editor).
4. **Concept cards**: 3 or 4 `::: {.concept}` cards in `::: {.concepts}`, not repeating the bullets (editor).
5. **Parts**: one idea per `##`, each with an example, a diagram or a comparison (writers).
6. **Margin notes**: warnings and definitions in the margin, at most one per part (writers).
7. **Remember**: a green `callout-tip`, 3 to 5 bullets a reader can apply (editor).
8. **Sources**: `## Sources {.sources}`, folded on the site as "Sources (n)" (code).

The header, the visual, In 30 seconds, the cards, Remember, the sources and the menus
are built by the editor, the illustrator and code: writers only write their part.

## Tone
- **English**, plain, for a reader who is learning. Short sentences, active voice.
- Explain a term the first time it appears.
- No anecdotes about the author's own debugging (failed cells, kernel restarts, missing keys…).

## Content
- Only knowledge that lasts: concepts, patterns, current APIs.
- Keep the source's important details: numbers, conditions, caveats, steps, named tools.
- **Code is always the current, working version.** If the source uses an old API, write the current one.
- No quizzes or self-check questions.
- Never invent facts, numbers, function names or URLs. Never cite this website or its repository.
- Examples from the source go inside the part they illustrate.

## Visual and concrete
- Each part has a concrete example (real names, inputs and outputs, numbers) in an example box.
- Prefer showing over telling: a diagram for a flow, a table for a comparison, steps for a procedure,
  a before/after for a good and a bad practice.
- Use `###` sub-parts when needed, never deeper.
- One idea per part: a part never repeats what another part, the cards or In 30 seconds say.

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

Diagram: a ```` ```{mermaid} ```` block (flowchart or sequenceDiagram; avoid subgraphs). Do not draw
again what the synthesis visual already shows.

Margin notes, right after the paragraph they relate to (at most one per part; on phones they come
back into the text):
```
::: {.column-margin .watch}
A pitfall, in one or two sentences.
:::

::: {.column-margin .define label="Runtime"}
The code around the model: it reads the reply, runs the action, keeps the history.
:::
```

**Never** a `## Watch out` or `### Watch out` heading on its own. A second warning in the same part
goes in a `::: {.callout-warning}` with `## Watch out` as its first line, inside the part.

Code over 12 lines: a numbered, folded step with a short title (only the last step of a part is
shown open; `open="true"` or `open="false"` changes it):
````
::: {.code-step title="The runtime parses the action and loops"}
```python
...
```
:::
````

## Products and vendors
- Concept pages are **vendor-neutral**: explain the idea, not one product. A product may appear in an
  example box, named as an example.
- Tool cards (shown in each theme's "Tools in practice") describe a product factually: who makes it, what it does, how to use it, its limits.
  Attribute the maker's claims ("NVIDIA states that…"); no marketing words.
