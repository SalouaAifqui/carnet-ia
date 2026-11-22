--[[
Carnet IA reading layout, applied to every page at render time. The .qmd sources stay simple.

- Meta line under the title of a note: topic pill · Lesson n of N · x min read · Updated <date>.
  Numbers come from `_carnet/notes.json`, written by `_scripts/notes_index.py` (pre-render).
- `::: {.code-step title="…"}` around a code block → a numbered, folded <details>
  (title + language). Numbering restarts at each H2; only the last step of a section is open,
  unless a step says open="true" or open="false".
- `## Sources {.sources}` + its list → a folded "Sources (n)" block.
- `.lesson-meta` divs (kept in the sources for the agent) are dropped: the meta line replaces them.
]]

local data = nil

local function read_data()
  local dir = (quarto and quarto.project and quarto.project.directory) or "."
  local file = io.open(dir .. "/_carnet/notes.json", "r")
  if not file then return nil end
  local text = file:read("a")
  file:close()
  local ok, decoded = pcall(pandoc.json.decode, text, false)
  if ok then return decoded end
  return nil
end

local function current_key()
  local input = quarto and quarto.doc and quarto.doc.input_file
  local dir = quarto and quarto.project and quarto.project.directory
  if not input or not dir then return nil end
  local rel = input:sub(#dir + 2):gsub("\\", "/"):gsub("%.qmd$", "")
  return rel
end

local MONTHS = { "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" }

local function pretty_date(iso)
  local y, m, d = tostring(iso or ""):match("^(%d%d%d%d)-(%d%d)-(%d%d)")
  if not y then return nil end
  return string.format("%d %s %s", tonumber(d), MONTHS[tonumber(m)], y)
end

local function topic_class(note)
  return ({ llms = "t-llms", agents = "t-agents", evaluation = "t-eval", guardrails = "t-guardrails",
            toolbox = "t-tools" })[note.topic] or "t-agents"
end

local function pill_text(note)
  -- Lessons are numbered within a track, so the pill names the track.
  local topic = data.topics[note.topic]
  if topic and topic.tracks then return note.sectionTitle end
  return topic and topic.title or note.topic
end

local function escape(s)
  return (tostring(s):gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"):gsub('"', "&quot;"))
end

local function meta_line(note)
  local parts = { string.format('<span class="pill %s">%s</span>', topic_class(note), escape(pill_text(note))) }
  if note.lesson and note.of then
    table.insert(parts, string.format("<span>Lesson %d of %d</span>", note.lesson, note.of))
  end
  table.insert(parts, string.format("<span>%d min read</span>", note.minutes))
  local date = pretty_date(note.date)
  if date then table.insert(parts, string.format("<span>Updated %s</span>", date)) end
  local html = '<div class="note-meta ' .. topic_class(note) .. '">' ..
      table.concat(parts, '<span class="sep" aria-hidden="true">·</span>') .. '</div>'
  return pandoc.RawBlock("html", html)
end

-- ---------- code steps ----------

local function code_step_blocks(div, number, open)
  local code = nil
  for _, block in ipairs(div.content) do
    if block.t == "CodeBlock" then code = block break end
  end
  local lang = (code and code.classes[1]) or ""
  local title = div.attributes["title"] or ""
  local head = string.format(
    '<details class="code-step"%s><summary><span class="step-n">%d</span>' ..
    '<span class="step-title">%s</span><span class="step-lang">%s</span></summary>',
    open and " open" or "", number, escape(title), escape(lang))
  local out = { pandoc.RawBlock("html", head) }
  for _, block in ipairs(div.content) do table.insert(out, block) end
  table.insert(out, pandoc.RawBlock("html", "</details>"))
  return out
end

local function is_step(block)
  return block.t == "Div" and block.classes:includes("code-step")
end

local function transform_code_steps(blocks)
  -- Number per H2 section; the last step of each section is open by default.
  local out, section, pending = {}, {}, {}
  local function flush()
    local last = nil
    for i, block in ipairs(section) do if is_step(block) then last = i end end
    local n = 0
    for i, block in ipairs(section) do
      if is_step(block) then
        n = n + 1
        local flag = block.attributes["open"]
        local open = (flag == "true") or (flag ~= "false" and i == last)
        for _, b in ipairs(code_step_blocks(block, n, open)) do table.insert(out, b) end
      else
        table.insert(out, block)
      end
    end
    section = {}
  end
  for _, block in ipairs(blocks) do
    if block.t == "Header" and block.level <= 2 then flush() end
    table.insert(section, block)
  end
  flush()
  return out
end

-- ---------- sources ----------

local function fold_sources(blocks)
  for i, block in ipairs(blocks) do
    if block.t == "Header" and block.classes:includes("sources") then
      local list = blocks[i + 1]
      if list and (list.t == "BulletList" or list.t == "OrderedList") then
        local n = #list.content
        blocks[i] = pandoc.RawBlock("html",
          string.format('<details class="sources-fold" id="sources"><summary>Sources (%d)</summary>', n))
        table.insert(blocks, i + 2, pandoc.RawBlock("html", "</details>"))
      end
      return blocks
    end
  end
  return blocks
end

function Pandoc(doc)
  data = read_data()
  local blocks = {}
  for _, block in ipairs(doc.blocks) do
    if not (block.t == "Div" and block.classes:includes("lesson-meta")) then
      table.insert(blocks, block)
    end
  end
  blocks = transform_code_steps(blocks)
  blocks = fold_sources(blocks)

  local key = current_key()
  local note = data and key and data.notes and data.notes[key]
  if note then
    table.insert(blocks, 1, meta_line(note))
  end
  doc.blocks = blocks
  -- code steps nested in another block (e.g. inside an example): numbered 1, open
  return doc:walk({
    Div = function(div)
      if div.classes:includes("code-step") then return code_step_blocks(div, 1, true) end
    end
  })
end
