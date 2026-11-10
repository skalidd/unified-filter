# Change history

Every version was a response to a failure actually observed in daily use.
The design trail survives as inline `v2.8.x` comments throughout
`unified_filter.py` — the comment above each block says what broke and why
the fix looks the way it does.

## 2.8.21 — mid-turn context overflow fix
The trim pass (2.8.14) only ran on the *first* request of a turn. OWU's
tool loop re-issues follow-up requests with fresh, untrimmed tool results
attached — a single `grep -r` dump could blow the context window mid-turn
even though history trimming had already run. The inlet now also runs on
those follow-up (`filter_type='request'`) dispatches. A stale claim in the
trim docstring (2.8.14–2.8.20) is corrected in place.

## 2.8.20 — re-tag only
Code-identical to 2.8.19. Kept as a numbered step because it was deployed
as one.

## 2.8.19 — heal visibility fix
A successful heal landed in the database but the browser still showed the
broken reply. Cause: the frontend events handler works on a detached clone
of the message and writes that clone back after the outlet update arrives
(upstream issue #32994). Fix: after a heal modifies a turn, fire a
`chat:reload` event after a short delay (`post_heal_reload_seconds`) so the
client refetches and the healed body paints.

## 2.8.18 — temporary diagnostic probe
A valve was added to test the write-back race by delaying the outlet. The
experiment disproved the emit-timing theory (2s and 12s delays both left a
blank bubble). The probe is **removed from this published build**; 2.8.19's
reload fix is the one that worked.

## 2.8.17 — spill-directory garbage collection
The spill directory was an append-only ledger that grew forever. Now a
rolling inventory: `tool_history_spill_keep` caps how many spilled files
survive, re-used spills get their mtime touched (recency = still in use),
and any file still quoted by a live message is protected from deletion.
Cleanup runs once per trim pass, not per spill write.

## 2.8.16 — trim budget fix
`keep = min(cap, head + tail)` made every cap above head+tail a dead knob —
the newest-gets-more-headroom rule never had any effect. Caught by the trim
test suite, not by eye. The cap is now the real budget: the tail keeps its
configured amount, the head absorbs the remaining room, and the stub mark
plus spill pointer is reserved so results stay inside the cap.

## 2.8.15 — three heal fixes (A, B, C)
- **A**: reject and cutoff-heal used to be `if / elif`, making the two
  failure modes mutually exclusive. A real turn had a plaintext call AND a
  truncated reasoning item; reject won the `if` and the heal never ran. Now
  evaluated independently, merged into one instruction when both fire.
- **B**: tool bindings forwarded into heal sub-calls caused the model to
  emit more dead calls. Sub-calls now run with no tools bound; the old
  forwarding branches are gone.
- **C**: a continuation that came back empty burned a loop iteration in
  total silence. Every sub-call is now logged (`debug_halluc_audit`), and
  both empty-reply signatures get a standing WARNING.

## 2.8.14 — context-blowout defense (inlet trim + spill)
History replay hands the filter already-flattened OpenAI-format messages,
so oversized `role: tool` results and oversized `tool_calls.arguments` from
previous turns went into every prompt whole. Now they're capped before the
prompt is sent: full text spills to disk (content-addressed filename), the
in-context block becomes head+tail plus a stub naming the spill path, so
the model can re-read the full text in slices. Per-message budget, newest
message gets a bigger budget, plus a total budget for the whole pass.
Tool-call pairing (`tool_call_id`) is never broken.

## 2.8.13 — bare-name hallucination shape
Real emissions used the bare tag `tool_call>` with no name. All 2.8.10
alternatives required one of `function|invoke|tool_use|tool` immediately
before `>`, so `tool_call>` matched the block regex, extracted an empty
name, and passed through untouched — no rejection, no audit line. A bare
name now matches and is checked like any other.

## 2.8.12 — tag-hygiene prompt removed
The tag-hygiene note that was appended to the last user message is gone:
it was redundant with the per-model system prompt, and it actively harmed
non-chat models — one small model read the note as call syntax and
invented a tool that had never been registered. The defanging regexes stay;
only the injected prompt text was removed.

## 2.8.11 — sub-call binding proof
The retry path's assumption about tool bindings was proven with a runtime
check instead of trusted. (Superseded by 2.8.15 fix B.)

## 2.8.10 — hallucination-shape alternatives
Additional plaintext-call shapes recognized. (Partially superseded by
2.8.13.)

## 2.8.9 — root cause of duplicated narration
OWU stores `content` as the join of every output item, and it keeps each
interim bridge line as its own item. When the outlet rewrote the FINAL
item with the whole cumulative display, that item became a copy of
everything before it and bridge lines rendered twice. The final item now
receives only its own text plus filter-produced deltas. Also: trailing
incomplete reasoning items are marked completed, and Gate-3 timeline
ordering keeps earlier message items intact.

## 2.8.8 — collapsed echo bridge lines
Models sometimes open the final answer by replaying the interim narration
lines verbatim. Now the replayed copy is dropped — safe because every
removed span still exists verbatim as its own output item, so only a copy
is ever cut, never the only copy.

## 2.8.7 — hallucination rejection hardened
Spaced tag forms (`< tool_call>`, `< function=x>`) are detected, and
plaintext tool markup from a continuation sub-call is stripped even when
it names an active tool (the sub-call has no tools bound, so any call it
emits is dead on arrival).

## 2.8.6 — hallucinated-tool-call rejection
When the model emits a plain-text tool-call block naming a tool that is
not active this session: the block is stripped from the visible message,
a short rejection note replaces it, and the model is told to continue in
prose. An allowlist valve exists for names you want to let through.

## 2.8.5 — message-cutoff heal trigger
Truncated final-message *prose* used to go unhealed because the reasoning
item completed first. New trigger, deliberately narrow: final content item
is a non-empty message, no unanswered tool call, and the text ends on a
non-terminal character or inside an unclosed code fence.

## 2.8.4 — seam-anchored echo dedupe
2.8.3's dedupe was found — by an external reviewer model's adversarial
review — to delete genuinely new text; all 6 of its cases reproduced as
failures against the real function (repeated table/code headers, closing
fences, indented code bodies, coincidental prefixes). Lesson recorded in
the code: duplicated text is ugly, deleted text is corrupting. 2.8.4
anchors to the seam: a block counts as an echo only when it matches the
END of what was already streamed. Ambiguous cases duplicate rather than
delete.

## 2.8.3 — dedupe attempt
First attempt at dropping continuation echoes. Superseded within the same
day by 2.8.4 (see above).

## 2.8.2 — display-only failure notes
Heal-failure notes are display-only and name the exception type; plaintext
tool markup is defanged with zero-width characters in healed text and
normalized in inlet history so replayed markup can't prime the model.

## 2.8.1 — heal data preservation
Heals keep in-turn answered tool results (`function_call` +
`function_call_output` items) so the continuation sees data the tools
already fetched before the reasoning death. Stops `[Thought]`/`[Tool Call]`
format priming.

## 2.8 — structured-output heal
Detects mid-reasoning cutoffs from the structured `output[]` items using
the reasoning item's own status, plus a parked-tool-call check (a turn can
hold many already-answered calls). Continuation runs as a sub-call through
the OWU API; results are written back into the structured output.

## Earlier line (pre-2.8)
The filter began life as several smaller filters (thought-block handling,
plaintext command execution, tool-tag defanging) that were merged into one
"unified" filter; the name stuck through every rewrite.
