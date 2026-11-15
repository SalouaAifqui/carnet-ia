# Carnet IA style guide

The agent reads this file before writing and before reviewing. Edit it to change how pages are written.

## Language and tone
- Write in **English**, plainly, for a reader who is learning.
- Short sentences, active voice. Explain a term the first time it appears.
- No anecdotes about the author's own debugging (failed cells, kernel restarts, missing keys…).

## Organisation: our concepts, not the source's structure
- The site is organised by **concept**, following our own reasoning. Never mirror the structure of a
  course or an article: no page per lesson, no folder per course.
- New material is **merged into the concept page it belongs to** whenever one exists. A new page is
  only for a concept the site doesn't cover yet.
- Examples from the source (a demo agent, a case study…) go **inside the section they illustrate**,
  introduced with "**Example:**". Never a separate "Examples" page or section.
- Courses and articles appear only in the Sources section.
- Never cite or use as an example this website (Carnet IA) or its repository.

## Content
- Only knowledge that lasts: concepts, patterns, current APIs.
- **Code examples are always the current, working version.** Never show deprecated APIs as the way to do it.
  If the source uses an old API, write the current one.
- Facts added from complementary research must stay consistent with the main source.
- Do not invent facts, numbers, function names or URLs.

## Keep pages digestible
- **At most 4 main parts (`##`)** per page, not counting `Remember` and `Sources`.
  Details go in sub-parts (`###`) inside them. Never go deeper than `###`.
- Give main parts short, plain titles that show the page's logic at a glance
  (e.g. "From text to vectors", "Inside the transformer", "Generating faster").
- When updating a page, fit new material into its existing parts instead of adding new `##` parts.

## Make it visual and concrete
Pages must not be walls of text. A reader should understand the idea from the visuals and the
examples alone, then read the prose for details.

- **Every main section has a concrete example**: real names, real inputs and outputs, numbers,
  a short scenario ("Asked *X*, the agent calls *Y* with *Z* and answers *W*"). Abstract
  statements alone are not enough.
- **Where examples come from**, in this order: the source; examples already used on the site
  (reuse the site's running examples, such as the email assistant or the research assistant,
  so pages connect); research findings from reliable sources. Never invent facts or numbers
  presented as real.
- **At least three different visual elements per page**, chosen to fit the content:
  - a ```` ```{mermaid} ```` diagram (flowchart for a process, sequenceDiagram for exchanges);
  - a table to compare options or map concepts;
  - concept cards (below);
  - an example box, a before/after comparison, or numbered steps (below);
  - a `::: {.callout-tip}` or `::: {.callout-warning}`.
- Prefer showing over telling: a diagram instead of a paragraph describing a flow, a table
  instead of a list of "X does…, Y does…", a before/after instead of "you should avoid…".

### Visual components (Quarto markdown)

Example box: put each concrete example in one, including its code:
```
::: {.example}
**A title for the example.** The scenario, in two or three sentences.

(optional code block)
:::
```

Before/after or side-by-side comparison:
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
(`.bad` / `.good` are optional: use plain `{.col}` for neutral options.)

Numbered steps, for a procedure:
```
::: {.steps}
1. **First step**: what happens.
2. **Second step**: what happens.
:::
```

## Page structure
Use this structure (Quarto markdown), in this order, skipping sections that don't apply. No quiz.

1. A one-paragraph summary in a `::: {.tldr}` block.
2. A diagram in a ```` ```{mermaid} ```` block when there is a flow or architecture to show.
3. Concept cards, right after the summary and without a heading:
   ```
   ::: {.concepts}
   ::: {.concept}
   `Name`

   One or two sentences.
   :::
   :::
   ```
4. Sections with explanations, each with its concrete example, tables, diagrams and ```` ```python ```` code blocks.
5. A `::: {.callout-tip}` block titled `## Remember` with 3–6 bullet points.
6. Optionally a `::: {.callout-warning}` block titled `## Watch out` for general pitfalls.

Do **not** write a front matter block, the topic pills or the Sources section: the agent's code adds them.
