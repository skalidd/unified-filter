"""Verify _dedupe_continuation is wired into the installed class correctly:
staticmethod, two positional args, and actually referenced in the outlet path.
Run inside the container against the module that was installed.
"""
import pathlib
import importlib.util
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parent.parent / "unified_filter.py")

spec = importlib.util.spec_from_file_location("uf283", SRC)
mod = importlib.util.module_from_spec(spec)
sys.modules["uf283"] = mod
spec.loader.exec_module(mod)

UF = mod.Filter
fn = UF._dedupe_continuation
print("resolved:", fn)
print("is staticmethod-style (callable, unbound):", callable(fn))

# call with no instance at all -> proves staticmethod wiring
got = fn("already shown text here that is long enough to match",
         "already shown text here that is long enough to match")
print("no-instance call result:", repr(got))
assert got == "", "dedup did not drop a full duplicate"

kept = fn("prior displayed text of some length", "totally new sentence about something else")
assert kept == "totally new sentence about something else", f"legit text mangled: {kept!r}"

src = open(SRC, encoding="utf-8").read()
wired = "_dedupe_continuation(\n                accumulated_display, self._defang_visible_text(latest_chunk)" in src
print("outlet wires dedupe around defanged_chunk:", wired)
assert wired, "outlet does not call _dedupe_continuation"
print("anti-echo instruction in heal prompt:", "Continue with ONLY NEW text" in src)

# valves still parse
v = UF.Valves
print("valve fields:", [f for f in v.model_fields])
print("WIRING_OK")
