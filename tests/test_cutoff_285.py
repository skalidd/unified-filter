"""Trigger-precision tests for v2.8.5 _is_message_cutoff.
Runs INSIDE the container (httpx is container-only). argv[1] = module path."""
import pathlib
import importlib.util, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parent.parent / "unified_filter.py")
spec = importlib.util.spec_from_file_location("uf", SRC)
uf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uf)
F = uf.Filter()

def msg(text, status="completed"):
    return {"type": "message", "id": "m1", "status": status, "role": "assistant",
            "content": [{"type": "output_text", "text": text}]}

def reasoning(status="completed", text="because i said so"):
    return {"type": "reasoning", "id": "r1", "status": status,
            "content": [{"type": "reasoning_text", "text": text}]}

def fcall(cid="c1", status="completed"):
    return {"type": "function_call", "id": "fc1", "call_id": cid, "status": status,
            "name": "run_command"}

def fout(cid="c1", status="completed"):
    return {"type": "function_call_output", "id": "fo1", "call_id": cid,
            "status": status, "output": "ok"}

def compaction():
    return {"type": "open_webui:context_compaction", "id": "cc", "status": None}

CASES = [
    # (name, items, visible_text, last_msg, expected)
    ("real repro: reasoning done + comma tail",
     [reasoning(), msg("Pattern so far: `low` ok, `medium` ok,")], 
     "Pattern so far: `low` ok, `medium` ok,", {}, True),
    ("unclosed fence",
     [reasoning(), msg("Here is the patch:\n```python\ndef f():")],
     "Here is the patch:\n```python\ndef f():", {}, True),
    ("open bracket",
     [reasoning(), msg("In regex, open a character class with [")],
     "In regex, open a character class with [", {}, True),
    ("message item marked incomplete",
     [reasoning(), msg("So the answer is", status="incomplete")],
     "So the answer is", {}, True),
    ("trailing comma even though status completed",
     [reasoning(), msg("I checked A, B,")], "I checked A, B,", {}, True),

    # ---- must NOT fire ----
    ("normal complete turn",
     [reasoning(), msg("Done. Everything is green.")], "Done. Everything is green.", {}, False),
    ("legit semicolon one-liner (false positive)",
     [reasoning(), msg("Kill it with `kill -9 $PID;`")], "Kill it with `kill -9 $PID;`", {}, False),
    ("legit trailing colon handoff (false positive)",
     [reasoning(), msg("Paste your stack trace below:")], "Paste your stack trace below:", {}, False),
    ("legit markdown hr / dash (false positive)",
     [reasoning(), msg("Read from stdin by passing -")], "Read from stdin by passing -", {}, False),
    ("legit em-dash",
     [reasoning(), msg("The cause was a race —")], "The cause was a race —", {}, False),
    ("balanced fences",
     [reasoning(), msg("```python\nx=1\n```\nThat is all.")], "```python\nx=1\n```\nThat is all.", {}, False),
    ("fence parity trick: 4-backtick wrapper containing ```",
     [reasoning(), msg("````text\nhere is a fence: ```\n````")],
     "````text\nhere is a fence: ```\n````", {}, False),
    ("code string containing ``` (line-leading not counted)",
     [reasoning(), msg('x = "```".split()')], 'x = "```".split()', {}, False),
    ("turn ends on function_call_output (zero-token cutoff: out of scope)",
     [reasoning(), fcall(), fout()], "earlier prose", {}, False),
    ("turn ends on unanswered tool call",
     [reasoning(), msg("Querying the user table"), fcall()], "Querying the user table", {}, False),
    ("orphan call in step 1 but final prose answered (must still heal, not blocked)",
     [reasoning(), fcall(cid="dead1"), fout(cid="dead1", status="failed"), reasoning(),
      msg("So the file is missing,")],
     "So the file is missing,", {}, True),
    ("turn ends on reasoning (v2.8.4 territory, not ours)",
     [msg("prose"), reasoning(status="incomplete")], "prose", {}, False),
    ("context_compaction appended after message: must still see the message (reviewer case 2)",
     [reasoning(), msg("So the fix is to lower the threshold,")], 
     "So the fix is to lower the threshold,", {}, True),
    ("context_compaction after a COMPLETE message: must not fire",
     [reasoning(), msg("So the fix is done.")], "So the fix is done.", {}, False),
    ("empty output items -> False", [], "whatever,", {}, False),
    ("message empty text -> False", [reasoning(), msg("   ")], "   ", {}, False),
    ("ends on closing punctuation only",
     [reasoning(), msg("Verdict: safe.")], "Verdict: safe.", {}, False),
    ("ends on emoji",
     [reasoning(), msg("All set 🙂")], "All set 🙂", {}, False),
    ("ends on markdown table row",
     [reasoning(), msg("| a | b |")], "| a | b |", {}, False),
    ("ends on bold/italic marker",
     [reasoning(), msg("the **real** cause")], "the **real** cause", {}, False),
]

fails = 0
for name, items, vis, last, want in CASES:
    got = F._is_message_cutoff(last, items, vis)
    ok = got == want
    if not ok:
        fails += 1
    print(f"{'ok ' if ok else 'FAIL'} {name}: got {got} want {want}")
print(f"\n{len(CASES)-fails}/{len(CASES)} pass")

# _ends_non_terminal / _has_unclosed_fence directly
print("\n-- ends_non_terminal")
for t, w in [("a,", True), ("a", False), ("a;", False), ("a -", False), ("a —", False),
             ("a [", True), ("a (", True), ("a {", True), ("a:", False), ("a,\n\n  ", True)]:
    g = uf.Filter._ends_non_terminal(t)
    print(("ok " if g == w else "FAIL"), repr(t), g, w)
print("\n-- unclosed_fence")
for t, w in [("```py\nx", True), ("```py\nx\n```", False),
             ("````text\n```\n````", False), ('x = "```"', False),
             ("text\n```a\n```\nmore\n```b", True)]:
    g = uf.Filter._has_unclosed_fence(t)
    print(("ok " if g == w else "FAIL"), repr(t), g, w)
