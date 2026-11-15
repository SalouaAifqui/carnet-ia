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

## Content
- Only knowledge that lasts: concepts, patterns, current APIs.
- **Code examples are always the current, working version.** Never show deprecated APIs as the way to do it.
  If the source uses an old API, write the current one.
- Facts added from complementary research must stay consistent with the main source.
- Do not invent facts, numbers, function names or URLs.

## Page structure
Use this structure (Quarto markdown), in this order, skipping sections that don't apply. No quiz.

1. A one-paragraph summary in a `::: {.tldr}` block.
2. A diagram in a ```` ```{mermaid} ```` block when there is a flow or architecture to show.
3. `## Key ideas` as concept cards:
   ```
   ::: {.concepts}
   ::: {.concept}
   `Name`

   One or two sentences.
   :::
   :::
   ```
4. Sections with explanations, tables and ```` ```python ```` code blocks.
5. A `::: {.callout-tip}` block titled `## Remember` with 3–6 bullet points.
6. Optionally a `::: {.callout-warning}` block titled `## Watch out` for general pitfalls.

Do **not** write a front matter block, the topic pills or the Sources section: the agent's code adds them.
