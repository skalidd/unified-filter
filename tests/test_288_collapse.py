"""v2.8.8 collapse_echoed_bridge: does it fix the dup without cutting prose?"""
import pathlib
import importlib.util
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parent.parent / "unified_filter.py")
spec = importlib.util.spec_from_file_location("uf288", SRC)
uf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uf)
f = uf.Filter()

cases = 0
fails = 0


def check(label, cond):
    global cases, fails
    cases += 1
    if not cond:
        fails += 1
    print(("PASS " if cond else "FAIL ") + label)


A = "I don't have that in front of me at the right level of detail — let me pull up what was recorded."
B = "Recorded detail found. Grounding the explanation in the actual code before I describe the fix path:"

# 1. Plain replay at the top of the final item is removed.
out = f._collapse_echoed_bridge(A + "\n" + B + "\nHere is the real answer.", [A, B])
check("C1 replay dropped, answer kept", out == "Here is the real answer.")

# 2. Interim line NOT echoed stays untouched (no invention of deletions).
out = f._collapse_echoed_bridge("Here is the real answer.", [A, B])
check("C2 no echo, no change", out == "Here is the real answer.")

# 3. Short interim line is not a candidate (too risky to cut).
short = "ok done"
out = f._collapse_echoed_bridge(short + "\nRest of text " * 10, [short])
check("C3 short interim line ignored", out == (short + "\nRest of text " * 10).strip())

# 4. Echo embedded mid-sentence is NOT spliced out (line-anchored only).
prose = "Note that " + A + " is what the model said earlier, and that matters."
out = f._collapse_echoed_bridge(prose, [A])
check("C4 mid-sentence echo left alone", out == prose)

# 5. A matching line inside a code fence must NOT be cut: in a fence that line
#    is code being shown, not narration being repeated.
fenced = "```python\n" + A + "\nprint(1)\n```"
out = f._collapse_echoed_bridge(fenced, [A])
check("C5 fenced line preserved", out == fenced)

# 6. All-echo input must not collapse to empty.
out = f._collapse_echoed_bridge(A, [A])
check("C6 total-echo keeps original rather than emptying", out == A)

# 7. Only the first copy is cut; a second verbatim copy survives.
out = f._collapse_echoed_bridge(A + "\nbody\n" + A, [A])
check("C7 only first copy cut", out.count(A) == 1)

print(f"\n{cases - fails} passed, {fails} failed")
print("RESULT:", "ALL_OK" if fails == 0 else "FAILURES")
