"""Hallucinated-tool detection tests for unified filter v2.8.6.
Run: python3 test_halluc_286.py [module_path]
No httpx needed for these unit cases (pure functions).
Design rule from v2.8.4: duplicated text is ugly, deleted text is corrupting -
when ambiguous, do NOT strip.
"""
import pathlib
import importlib.util
import json
import sys

LT, GT = chr(60), chr(62)
TC_OPEN = LT + "tool_call" + GT
TC_CLOSE = LT + "/tool_call" + GT
ZWSP = "\u200b"

path = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parent.parent / "unified_filter.py")
spec = importlib.util.spec_from_file_location("uf", path)
uf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uf)
f = uf.Filter()

ALLOWED = {"run_command", "read_file", "write_file", "replace_file_content", "grep_search"}

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS {name}")
    else:
        failed += 1
        print(f"FAIL {name} {extra}")


def strip(text):
    return f._strip_hallucinated_blocks(text, ALLOWED)


# ---- positive: real observed shapes ----
t1 = (
    "Found a real defect in the blueprint. Fixing it before answering.\n"
    + TC_OPEN
    + "\n"
    + LT + "function=replace_file_path_note" + GT
    + "\n"
    + LT + "parameter=x" + GT
    + "\ny\n"
    + LT + "/parameter" + GT
    + "\n"
    + LT + "/function" + GT
    + "\n"
    + TC_CLOSE
)
cleaned, names = strip(t1)
check("TC1 xml shape stripped", names == ["replace_file_path_note"] and "function=replace_file_path_note" not in cleaned and "defect in the blueprint" in cleaned, (names, cleaned))

t2 = TC_OPEN + "\n" + LT + "function=read" + GT + "\n" + LT + "/function" + GT + TC_CLOSE
cleaned, names = strip(t2)
check("TC2 empty-args hallucinated name stripped", names == ["read"] and cleaned == "", (names, repr(cleaned)))

t3 = (
    "prose before\n"
    + TC_OPEN
    + "\n"
    + LT + "function=ask_user_question" + GT
    + "\n"
    + LT + "parameter=questions" + GT
    + "\n[{\"a\": 1}]\n"
    + LT + "/parameter" + GT
    + "\n"
    + LT + "/function" + GT
    + "\n"
    + TC_CLOSE
    + "\nprose after"
)
cleaned, names = strip(t3)
check("TC3 params kept inside block, prose outside kept", names == ["ask_user_question"] and "prose before" in cleaned and "prose after" in cleaned and "ask_user_question" not in cleaned)

# valid tool name -> untouched
t4 = (
    TC_OPEN
    + "\n"
    + LT + "function=run_command" + GT
    + "\n"
    + LT + "parameter=command" + GT
    + "\nls -la\n"
    + LT + "/parameter" + GT
    + "\n"
    + LT + "/function" + GT
    + "\n"
    + TC_CLOSE
)
cleaned, names = strip(t4)
check("TC4 active tool not stripped", names == [] and cleaned == t4)

# JSON shape
t5 = TC_OPEN + '{"name": "run_terminal", "arguments": {"cmd": "ls"}}' + TC_CLOSE
cleaned, names = strip(t5)
check("TC5 json shape stripped", names == ["run_terminal"] and cleaned == "", (names, repr(cleaned)))

t5b = TC_OPEN + '{"name": "grep_search", "arguments": {"query": "x"}}' + TC_CLOSE
cleaned, names = strip(t5b)
check("TC6 json shape active tool kept", names == [] and cleaned == t5b)

# unclosed block at end of content (turn ended mid-call)
t7 = "text then\n" + TC_OPEN + "\n" + LT + "function=no_such_tool" + GT + "\n" + LT + "parameter=foo" + GT
cleaned, names = strip(t7)
check("TC7 unclosed tail block stripped", names == ["no_such_tool"] and cleaned == "text then" and "function=no_such_tool" not in cleaned, repr(cleaned))

# ---- negative: must NOT touch ----
n1 = "We write `< tool_call>` and `< /think>` with a space so the parser stays safe."
cleaned, names = strip(n1)
check("NC1 spaced prose tags untouched", names == [] and cleaned == n1)

n2 = "The bug looks like this:\n```\n<tool_call>\n<function=replace_file_path_note>\n</function>\n</tool_call>\n```\nand that is the shape."
cleaned, names = strip(n2)
check("NC2 fenced example untouched", names == [] and cleaned == n2)

n3 = "The old shape was <tool_call><function=read></function></tool_call> inline in backticks."
n3 = n3.replace("was <tool_call>", "was `" + TC_OPEN) + "`"
cleaned, names = strip(n3)
check("NC3 inline-code example untouched", names == [] and cleaned == n3, repr(cleaned))

n4 = "Summary of the fix:\n- reject bogus names\n- allowlist valve\n"
cleaned, names = strip(n4)
check("NC4 no tags no match", names == [] and cleaned == n4)

n5 = (
    TC_OPEN
    + "\n"
    + LT + "function=ghost_tool" + GT
    + "\n"
    + LT + "parameter=command" + GT
    + "\nls -la\n"
    + LT + "/parameter" + GT
    + "\n"
    + LT + "/function" + GT
    + "\n"
    + TC_CLOSE
    + "\n"
    + TC_OPEN
    + "\n"
    + LT + "function=run_command" + GT
    + "\n"
    + LT + "/function" + GT
    + "\n"
    + TC_CLOSE
)
cleaned, names = strip(n5)
check("NC5 mixed: only hallucinated block removed", names == ["ghost_tool"] and "run_command" in cleaned and "ghost_tool" not in cleaned, repr(cleaned))

# ZWSP-defanged stored rows still detected
t8 = TC_OPEN.replace(LT, LT + ZWSP) + "\n" + LT + "function=replace_file_status_note" + GT + "\n" + LT + "/function" + GT + "\n" + TC_CLOSE.replace(LT, LT + ZWSP)
cleaned, names = strip(t8)
check("TC8 ZWSP-defanged block detected", names == ["replace_file_status_note"], (names, repr(cleaned)))

# name extraction: function name= "x" attribute style
t9 = LT + "invoke name=\"nonexistent_tool\"" + GT + LT + "arg name=\"q\"" + GT + "hi" + LT + "/invoke" + GT
cleaned, names = strip(t9)
check("TC9 invoke-name attr shape", names == ["nonexistent_tool"], (names, repr(cleaned)))

# active set resolution
meta = {"tools": {"run_command": {"name": "run_command"}, "query_gemini": {"name": "query_gemini"}}}
names_set = f._active_tool_names(meta)
check("TC10 metadata dict tool map parsed", names_set == {"run_command", "query_gemini"}, names_set)

meta2 = {"tools": [{"type": "function", "spec": {"name": "alpha"}}, {"type": "function", "function": {"name": "beta"}}]}
names_set2 = f._active_tool_names(meta2)
check("TC11 list-style tools parsed", names_set2 == {"alpha", "beta"}, names_set2)

f.valves.hallucinated_tool_allowlist = "ask_user, delete_memory"
names_set3 = f._active_tool_names({})
check("TC12 allowlist valve merged", names_set3 == {"ask_user", "delete_memory"}, names_set3)

# empty metadata -> empty allowed set (feature must self-disable upstream)
check("TC13 empty metadata yields empty set", f._active_tool_names(None) == {"ask_user", "delete_memory"} and f._active_tool_names({}) == {"ask_user", "delete_memory"})
f.valves.hallucinated_tool_allowlist = ""

# output-item scrub
items = [
    {"type": "message", "content": [{"type": "output_text", "text": "narration\n" + t1.split("Found")[0] + TC_OPEN + LT + "function=ghost" + GT + LT + "/function" + TC_CLOSE}]},
    {"type": "reasoning", "content": [{"type": "text", "text": "think about " + TC_OPEN + " nothing " + TC_CLOSE}]},
    {"type": "message", "content": [{"type": "output_text", "text": "tail prose"}]},
]
removed = f._scrub_hallucinated_in_output(items, ALLOWED)
check("TC14 output scrub hits message item only", removed == ["ghost"] and "ghost" not in json.dumps(items), (removed, json.dumps(items)))
check("TC15 output scrub leaves reasoning untouched", "think about" in json.dumps(items))

# code-region scanner: unclosed fence swallows trailing text
n6 = "prose\n```\nsome code with " + TC_OPEN + " inside\nno close"
cleaned, names = strip(n6)
check("NC6 unclosed fence region skipped", names == [] and cleaned == n6)

# thinking-block region skipped
n7 = LT + "think" + GT + "internal " + TC_OPEN + LT + "function=ghost" + GT + LT + "/function" + TC_CLOSE + LT + "/think" + GT + " done"
n7 = n7.replace(LT + "think" + GT, LT + ZWSP + "think" + GT)  # defanged style stored
cleaned, names = strip(n7)
check("NC7 thought-region skipped", names == [] and cleaned == n7, (names, repr(cleaned)))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
