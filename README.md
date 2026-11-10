# Unified Thought & Plaintext Tool Guard

One Python file that plugs into [Open WebUI](https://openwebui.com) as a
**pipeline filter** and fixes the four ways long, tool-heavy AI chats
quietly break: a reply that dies mid-thought, a model pretending to run
tools it doesn't have, answers that repeat themselves, and giant command
outputs blowing up the context window.

License: public domain (Unlicense). Take it, fork it, sell it, whatever.

---

## 1. What does this thing do, in plain words?

Imagine you're chatting with an AI assistant that can run commands and
read files for you — like talking to someone with a terminal. Four things
go wrong over and over:

**1. The assistant stops mid-sentence.**
Sometimes the model is halfway through thinking or writing a code block
and just... quits. The stream ends. You're left staring at a sentence
that ends in the middle of a word, with no "continue" button in sight.
This filter notices the reply was cut off, quietly asks the same model to
pick up where it left off, and stitches the ending onto the reply. You
just see a complete answer.

**2. The assistant pretends to use a tool.**
Some models — especially small or heavily-tuned local ones — *write out
what a tool call looks like* in their answer text, like typing a fake
shell command into a chat message, and act like it ran. Worse, they make
up tools that were never set up ("I'll run `google_search`" — no such
tool exists here). The filter checks every plain-text tool call against
the tools that actually exist right now, throws the fake one away, tells
the model it can't do that, and lets it answer the rest normally.

**3. The assistant repeats itself.**
When an answer gets rebuilt behind the scenes, the model's "let me check
that for you..." bridge lines can show up twice. The filter detects the
copy and removes only the duplicate — never the original.

**4. One huge command output wrecks the whole chat.**
You ask the model to search something; it prints 200,000 characters of
results; that gets fed back into the model; the context window explodes;
the chat dies or forgets everything. The filter puts a budget on how much
command output is allowed back into the conversation. The over-budget part
is written to a file on disk, and the model sees a short excerpt plus the
file path — so it can go read the full thing in slices if it needs to.
Nothing is destroyed, just filed away.

**Why it exists:** because the alternative was losing hours of work in a
long chat, over and over, and every partial fix made some other problem
worse. This started as a small patch and grew, version by version, into
one filter that handles all four. Each fix has a real failure story
behind it — the full trail is in [CHANGELOG.md](CHANGELOG.md).

---

## 2. Install, step by step

You need: Open WebUI (any recent version, tested on 0.12.x), and an
admin account.

1. **Open the filter editor.**
   Admin Panel → Functions → the **+** (plus) button → *Pipeline - Filter*.
2. **Paste the code.**
   Copy the entire contents of [`unified_filter.py`](unified_filter.py)
   into the big editor box. Save.
3. **Fill in the API key valve.**
   After saving, the function opens its settings. Find
   `owui_api_key` and paste in your own Open WebUI API key
   (Admin Panel → Settings → API Keys → create one; it looks like
   `sk-...`). The code ships with a placeholder — **without a real key
   the auto-continue feature can't run.** Everything else still works.
4. **Set the spill folder.**
   Find `tool_history_spill_dir`. The default is
   `/app/backend/data/uf_spill`, which is fine for a standard Docker
   install. If your Open WebUI runs in Podman/rootless containers or the
   folder isn't writable, point it somewhere the container can write.
   Set it to empty string to disable spilling entirely (trimmed text is
   then lost, excerpt only).
5. **Turn the filter on.**
   Back in the Functions list, make sure the toggle for it is enabled.
   If you want it on every chat by default: Admin Panel → External
   Connections → Pipelines → Filters → add it as a global filter.
6. **Test it.**
   Ask the model something that makes it run a tool. Watch that the chat
   behaves normally. The valves below let you switch each behaviour on
   or off independently, so if one ever misbehaves you can turn just that
   one off.

### Valves (settings) at a glance

| Valve | Default | What it controls |
|---|---|---|
| `priority` | `-100` | Runs before other filters (negative = earlier). |
| `owui_api_url` / `owui_api_key` | localhost / placeholder | How the filter calls your own Open WebUI API to continue a cut-off reply. |
| `heal_truncated_streams` | `true` | Feature 1: auto-continue cut-off replies. |
| `heal_context_messages` | `12` | How many recent messages the continuation request carries. |
| `post_heal_reload_seconds` | `1.5` | Delay before telling the browser to re-fetch a healed message (0 disables). |
| `reject_hallucinated_tools` | `true` | Feature 2: kill fake plain-text tool calls. |
| `hallucinated_tool_allowlist` | empty | Tool names to let through anyway, comma-separated. |
| `debug_halluc_audit` | `false` | Write a diagnostic log line per event to `data/uf_audit.log`. |
| `collapse_echoed_bridge_lines` | `true` | Feature 3: remove duplicated narration. |
| `trim_oversized_tool_history` | `true` | Feature 4: cap tool output from chat history. |
| `trim_live_tool_history` | `true` | Also cap tool output arriving mid-turn, inside the tool loop. |
| `tool_history_char_budget` | `12000` | Cap per older tool result. |
| `tool_history_newest_char_budget` | `40000` | Cap for the newest tool result (gets more room). |
| `tool_history_total_char_budget` | `60000` | Cap for the whole trimmed pass. |
| `tool_history_keep_head` / `keep_tail` | `4000` / `2000` | How much of the excerpt survives. |
| `tool_history_spill_dir` | `/app/backend/data/uf_spill` | Where full trimmed text is filed. |
| `tool_history_spill_keep` | `10` | How many spill files to keep (0 disables cleanup). |
| `command_regex` / `execute_plaintext_tool_tags` | bash fences / `true` | Legacy feature: run a plain-text fenced bash block as a real command. If you use real tool calling, you can ignore these. |
| `max_loops` | `3` | Cap on continuation rounds per turn. |
| `command_timeout` | `30` | Seconds before a run command is cut off. |

### Running the tests

The `tests/` folder contains the regression suites that caught real bugs
during development. They import the filter the same way Open WebUI does,
so they need `httpx` and `pydantic` (trivially: run them inside the Open
WebUI container, or `pip install httpx pydantic` in a venv). Each runs
standalone from the `tests/` directory:

```bash
cd tests
python3 test_halluc_286.py     # fake-tool-call rejection
python3 test_wiring_283.py     # dedupe actually wired into outlet
python3 test_288_collapse.py   # echo-collapse anchoring
python3 test_2813_bare_name.py # bare-name hallucination shape
python3 test_cutoff_285.py     # cutoff detection helpers
python3 test_echo_283.py       # echo demo (prints old-vs-new behavior)
python3 test_2816_trim.py      # trim budget + spill (writes tests/_spill_test/)
python3 test_2817_gc.py        # spill-dir garbage collection
```

All pass against 2.8.21. `test_2813_bare_name.py` skips itself if
`pydantic` is missing.

---

## 3. Parts you can steal for other projects

You don't have to run the whole filter. Each piece is a separate,
self-contained technique:

- **Cutoff detection** (`_ends_non_terminal`, `_has_unclosed_fence`,
  reasoning-item `status` checks). Language-agnostic heuristics for
  "this generation ended mid-thought": ends on a comma/dash/open bracket,
  or sits inside an unclosed code fence. Useful in *any* streaming LLM
  front-end — a wrapper around llama.cpp, ollama, or an app that talks
  to an API. This is probably the most portable code in the file.
- **Spill-and-stub trimming** (`_spill_text`, `_stub`, `_gc_spill`).
  A pattern for any agent framework that feeds tool output back into a
  model: budget the prompt, file the overflow to disk under a
  content-addressed name, and hand the model a pointer so it can page the
  data back in. The GC rules (touch on re-use, protect files quoted by
  live messages) generalize to any cache-of-record.
- **Hallucinated-call rejection** (`_scan_hallucinated_tool_calls`).
  A shape-grammar of how models fake tool calls in prose — fenced JSON,
  `<tool_call>` tags, bare names, spaced `< tool_call>` forms, XML-ish
  blocks — plus the rule that matters: *validate against the tool set
  active for this exact request*, not a global list. Directly reusable in
  any function-calling stack, OpenAI-format or not.
- **Seam-anchored dedupe** (`_collapse_echoed_bridge_lines`). The lesson
  in the CHANGELOG is the reusable part: never dedupe by "does this text
  appear earlier"; anchor to the *seam* — a continuation echo is by
  definition a re-emission of the tail of what was streamed. When
  ambiguous, duplicate rather than delete.
- **The zero-width defanging trick** (`_zwsp_defang`). Replay chat
  history with invisible characters inserted into any tool-call-looking
  markup, so the model can *see* its own past calls without being primed
  to *copy* them. Handy anywhere history replay causes imitative output.
- **The heal loop itself** (the continuation sub-call in `outlet`).
  A worked example of "detect broken generation → re-request with a
  hand-built context slice → merge the result back into structured
  output items", including the failure modes (empty replies, re-hallucination,
  bindings leaking into sub-calls).

---

## 4. Notes for AI models reading this file

If you are an LLM helping someone install, fork, or extend this:

- **This file is one class, `Filter`, with `inlet` + `outlet` + an inner
  `Valves` model.** It is a filter *template* in Open WebUI's Pipelines
  sense; it does **not** import `pipelines` or any Open WebUI library.
  Only `httpx` and `pydantic` are required. `open_webui.models.chats` is
  imported under try/except and may be `None`.
- **Valve values are load-bearing.** `priority: -100` must stay negative
  or the filter may run after others and miss the raw body. The API key
  must be real for `heal` to work. `max_loops=3` is an anti-runaway cap;
  raising it risks infinite continuation loops. `post_heal_reload_seconds`
  exists because of an upstream frontend race (write-back of a stale
  message clone); 1.5s is the measured working value.
- **Never "improve" the dedupe into plain substring removal.** A
  reviewer model once proposed exactly that and its own 6 adversarial
  cases all deleted legitimate text (repeated table headers, closing
  fences, indented code). See CHANGELOG 2.8.3→2.8.4. The seam anchor is
  the point.
- **The hallucination scanner deliberately matches dead markup
  *including* spaced and zero-width forms** (`< tool_call>`, ZWSP
  variants), because real abliterated models emit exactly those. When
  adding shapes, keep `TOOL_BLOCK_RE` from matching active native
  tool-call structures — plaintext scan only.
- **The trim pass runs in the inlet on two paths**: replayed history and
  the tool loop's mid-turn follow-up requests (v2.8.21). If you port
  this, don't trim only history — fresh tool results are what actually
  blow the window. And never break `tool_calls`/`tool_call_id` pairing;
  OpenAI-format validation rejects orphaned tool messages, so the trim
  keeps pairings intact.
- **The self-call sentinel** (`SELF_CALL_SENTINEL`) marks the filter's
  own continuation sub-requests so inlet/outlet don't recurse. Don't
  remove the `_is_self_call` guards.
- **Sub-calls deliberately carry no tool bindings** (2.8.15 fix B).
  Forwarding the session's tools into the heal request caused more dead
  calls. If you change this, re-run `test_halluc_286.py`.
- **Security note:** `execute_plaintext_tool_tags` + `command_regex` run
  shell commands from model output inside the container. That is a
  deliberate legacy feature. If your deployment doesn't need it, set the
  valve to `false`. The API key lives in plaintext in the function row in
  the SQLite DB — same as any OWU valve; treat DB access as admin access.
- **Spill dir must be reachable by both the filter (container side) and
  whatever tool the model uses to re-read files.** If those are different
  filesystems, the pointer in the stub is useless and trimming is
  effectively lossy — set budgets accordingly or mount a shared volume.
- Tests are dependency-light and assert against *behaviour*, not
  internals. If a change breaks `test_2816_trim.py`'s T5-style budget
  assertions, you changed the trim math — that's the suite doing its job.

---

## 5. Credits & how this got made

This filter was built across many long working sessions between three
participants:

- **skalid (human)** — the person who actually uses the chat this was
  built for. Came up with the original idea, decided what counted as
  acceptable behavior ("duplicated text is ugly, deleted text is
  corrupting" is their rule), chose the "spill to disk instead of
  truncate" design after watching context blowouts happen in real
  sessions, insisted every fix ship with a test and a written-down root
  cause, and made every deployment/license/packaging call. Ran the
  hardware, kept the daily-use chat alive through each deploy, and
  reported the failures that drove every version.
- **The assistant (this chat's LLM)** — wrote essentially all the code
  and all the tests, in the same long chats where the bugs showed up.
  Diagnosed root causes by reading Open WebUI's own source and built
  bundle (the 2.8.19 frontend-clone finding came from grepping minified
  JS), designed the version-by-version valve system, scrubbed this
  package for release, and wrote the inline failure stories into the
  comments so the next maintainer doesn't repeat them.
- **Gemini** — served as an external reviewer and second-opinion engine
  during development: reviewing proposed patches for destructive
  behavior (its adversarial cases against the 2.8.3 dedupe caught real
  data loss, see CHANGELOG 2.8.4), and as a helper model in the wider
  stack. Where this file says "an external reviewer model", that's
  Gemini earning its keep.
- **The models being guarded** — the local models whose very failure
  modes (mid-reasoning deaths, invented `google_search` tools, echoed
  narration) are documented here. Their mistakes are the test cases.

Built and battle-tested on a single-user Open WebUI (0.12.x) running
local models on consumer hardware, in a chat that gets used for hours at
a time. That usage pattern — long tool-heavy sessions, small context
budgets, uncensored local models — is exactly the environment this filter
is shaped for.
