"""v2.8.13: BARE-NAME tool blocks must yield a name and be rejected.

Measured gap in live 2.8.12 (chat a0540b30, message originalContent). The
abliterated model emitted, verbatim, after reading the old filter's tag-hygiene
note as call syntax:

    < tool_call>google_search{"query": "..."}< /tool_call>

TOOL_BLOCK_RE matched it. _tool_name_from_block returned '' because every
TOOL_NAME_RE alternative demands function|invoke|tool_use|tool immediately
before '>', and the tag text 'tool_call>' fails at '_call>'. Then
`if not name: continue` passed the block through: no reject, no audit line,
hallucinated call visible to the user.

Run: python3 test_2813_bare_name.py [module_path]
"""
import pathlib
import importlib.util
import re
import sys

LT, GT = chr(60), chr(62)
ZWSP = ""


def tag(name, close=False, spaced=True):
    slash = "/" if close else ""
    sp = " " if spaced else ""
    return LT + sp + slash + name + GT


def tco():
    return tag("tool_call")


def tcc():
    return tag("tool_call", close=True)


path = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parent.parent / "unified_filter.py")
spec = importlib.util.spec_from_file_location("uf", path)
uf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uf)
f = uf.Filter()

ALLOWED = {"run_command", "consult_gemini"}
passed = failed = 0


def check(label, cond):
    global passed, failed
    if cond:
        passed += 1
        print("PASS %s" % label)
    else:
        failed += 1
        print("FAIL %s" % label)


# ---- the real emission, byte-faithful ---------------------------------
sample = (
    tco() + "google_search{\"query\": \"llama.cpp latest release version github\"}" + tcc()
    + "\n" + tag("think", close=True)
    + "\n\nBased on the search results from the official llama.cpp GitHub repository, "
    "the most recent release version is v3200."
)
m = f.TOOL_BLOCK_RE.search(sample)
check("real emission: block matched", m is not None)
got = f._tool_name_from_block(m.group(0)) if m else None
check("real emission: name extracted -> 'google_search'", got == "google_search")

found = f._find_hallucinated_blocks(sample, ALLOWED)
check("real emission: rejected", len(found) == 1 and found[0][2] == "google_search")
cleaned, names = f._strip_hallucinated_blocks(sample, ALLOWED)
check("real emission: stripped, prose kept",
      names == ["google_search"]
      and "google_search" not in cleaned
      and "v3200" in cleaned)

# ---- ZWSP-defanged form (what history carries after inlet defang) -----
# inlet writes the canonical spelling as ZWSP immediately BEFORE '<', which keeps
# the tag itself matchable; a ZWSP stranded inside the tag is the malformed form
# _defang_tool_markup exists to normalize.
defanged = sample.replace(tco(), ZWSP + tco()).replace(tcc(), ZWSP + tcc())
check("zwsp form: block matched", f.TOOL_BLOCK_RE.search(defanged) is not None)
check("zwsp form: name extracted",
      f._tool_name_from_block(f.TOOL_BLOCK_RE.search(defanged).group(0)) == "google_search")
check("zwsp form: rejected",
      len(f._find_hallucinated_blocks(defanged, ALLOWED)) == 1)

# ---- unspaced wrapper variant -----------------------------------------
tight = LT + "tool_call" + GT + "ghost_tool{\"x\": 1}" + LT + "/tool_call" + GT
check("tight wrapper: rejected",
      len(f._find_hallucinated_blocks(tight, ALLOWED)) == 1)

# ---- name-only block, no payload: end-of-block branch -----------------
noargs = tco() + "ghost_tool" + tcc()
check("no-payload block: rejected",
      len(f._find_hallucinated_blocks(noargs, ALLOWED)) == 1)

# ---- truncated stream: name is all that made it out -------------------
trunc = "calling it now:\n" + tco() + "ghost_tool"
check("truncated: name extracted",
      f._tool_name_from_block(f.TOOL_BLOCK_RE.search(trunc).group(0)) == "ghost_tool")

# ---- allowed tool in bare-name shape must be untouched ----------------
ok = tco() + "consult_gemini{\"prompt\": \"hi\"}" + tcc()
check("allowed tool untouched", f._find_hallucinated_blocks(ok, ALLOWED) == [])

# ---- PROSE SAFETY: the whole reason for the payload lookahead ---------
prose = [
    "the " + tco() + "google_search tool is not registered here",
    "a bare " + tco() + "NAME is the shape that slipped past the detector",
    "I saw " + tco() + "google_search and then it answered from memory",
    "the block " + tco() + "send_email had no args at all",
]
for i, text in enumerate(prose):
    check("prose %d not rejected" % i, f._find_hallucinated_blocks(text, ALLOWED) == [])

# prose with a payload opener after the name IS the call shape -> stripped
# (documented accepted trade-off, same as 2.8.10)
edge = "look: " + tco() + "google_search({\"q\": 1})"
check("prose+payload edge: stripped (accepted trade-off)",
      len(f._find_hallucinated_blocks(edge, ALLOWED)) == 1)

# ---- code regions still protected -------------------------------------
fenced = "```plaintext\n" + tco() + "ghost_tool{\"a\": 1}" + tcc() + "\n```"
check("fenced block not rejected", f._find_hallucinated_blocks(fenced, ALLOWED) == [])
inline = "here: `" + tco() + "ghost_tool{\"a\": 1}" + tcc() + "`"
check("inline code not rejected", f._find_hallucinated_blocks(inline, ALLOWED) == [])
thought = (
    LT + "think" + GT + "I could try " + tco() + "ghost_tool{\"a\": 1}" + tcc()
    + " later" + LT + "/think" + GT
)
check("thought region not rejected", f._find_hallucinated_blocks(thought, ALLOWED) == [])

# ---- earlier forms must not regress -----------------------------------
older = [
    ("json", tco() + '{"name": "ghost_tool", "arguments": {}}' + tcc(), "ghost_tool"),
    ("element", tco() + tag("function") + "ghost_tool" + tag("function", True) + tcc(), "ghost_tool"),
    ("name-elem", tco() + tag("name") + "ghost_tool" + tag("name", True) + tcc(), "ghost_tool"),
    ("attr", tco() + LT + "function=ghost_tool" + GT + "{}" + tcc(), "ghost_tool"),
]
for label, text, want in older:
    m = f.TOOL_BLOCK_RE.search(text)
    got = f._tool_name_from_block(m.group(0)) if m else None
    check("%s still extracts %r" % (label, want), m and got == want)
    check("%s still rejected" % label, len(f._find_hallucinated_blocks(text, ALLOWED)) == 1)

print("\n%d passed, %d failed" % (passed, failed))
print("RESULT: " + ("ALL_OK" if failed == 0 else "FAILURES"))
sys.exit(0 if failed == 0 else 1)
