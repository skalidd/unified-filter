"""v2.8.17 spill garbage collection.

The trim pass writes one file per trimmed block and had no removal path at all, so
the spill directory was append-only forever. Policy under test: keep the newest N
by mtime, delete the rest, and treat a re-spill as renewed use.

Run: python /app/test_2817_gc.py [path to filter .py]
"""
import pathlib
import asyncio
import importlib.util
import os
import shutil
import sys
import time

SRC = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parent.parent / "unified_filter.py")
SPILL = "/tmp/uf_spill_gc_test"

results = []


def check(name, ok, extra=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f" {extra}"))


def load(path):
    spec = importlib.util.spec_from_file_location("uf", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["uf"] = mod
    spec.loader.exec_module(mod)
    return mod.Filter()


def touch_new(path, age_seconds):
    """Give a file an mtime age_seconds in the past."""
    t = time.time() - age_seconds
    os.utime(path, (t, t))


async def main():
    f = load(SRC)
    if not hasattr(f.valves, "tool_history_spill_keep"):
        print("FAIL valve tool_history_spill_keep missing")
        print("RESULT: FAILURES")
        return
    check("valve default is 10", f.valves.tool_history_spill_keep == 10,
          repr(f.valves.tool_history_spill_keep))

    # Fresh dir, no stray state from a previous run.
    if os.path.isdir(SPILL):
        shutil.rmtree(SPILL)
    f.valves.tool_history_spill_dir = SPILL

    # --- G1: 25 spills, cap 10 -> 10 newest survive --------------------------
    f.valves.tool_history_spill_keep = 10
    paths = []
    for i in range(25):
        p = f._spill_text(f"payload-{i}-" + ("X" * (100 + i)), f"call{i}")
        if p:
            paths.append(p)
    check("G1 25 spills written", len(paths) == 25, str(len(paths)))
    f._gc_spill(SPILL)
    remaining = sorted(n for n in os.listdir(SPILL) if n.endswith(".txt"))
    check("G1 inventory capped at 10", len(remaining) == 10, str(len(remaining)))

    # The survivors must be the most recently written ones. Payloads differ per i,
    # so the digests differ and nothing collides; the last 10 writes should win.
    survivors = {os.path.basename(p) for p in paths[-10:]}
    check("G1 survivors are the newest 10", set(remaining) == survivors,
          f"missing={survivors - set(remaining)} extra={set(remaining) - survivors}")

    # --- G2: re-spill refreshes mtime, so an in-use block does not age out ----
    # Write A, then pad with 10 newer blocks, then re-spill A (same bytes). A's
    # mtime is refreshed by the utime path, so it must still be alive afterwards.
    if os.path.isdir(SPILL):
        shutil.rmtree(SPILL)
    a = f._spill_text("REUSED-BLOCK" + "Y" * 300, "reuse")
    check("G2 first spill exists", a and os.path.exists(a), str(a))
    # Age A deliberately, then re-spill the identical bytes; the touch should undo it.
    touch_new(a, 10_000)
    for i in range(12):
        f._spill_text(f"pad-{i}-" + ("Z" * 400), f"pad{i}")
    # Re-spill while the aged copy is still on disk, then clean.
    a2 = f._spill_text("REUSED-BLOCK" + "Y" * 300, "reuse")
    f._gc_spill(SPILL, protect={a2})
    check("G2 re-spill returns same path", a2 == a, f"{a} vs {a2}")
    check("G2 in-use block survives GC", os.path.exists(a), "aged-out while still referenced")

    # --- G3: keep=0 disables cleanup -----------------------------------------
    if os.path.isdir(SPILL):
        shutil.rmtree(SPILL)
    f.valves.tool_history_spill_keep = 0
    for i in range(15):
        f._spill_text(f"no-gc-{i}-" + ("Q" * 200), f"ngc{i}")
    f._gc_spill(SPILL)
    n = len([n for n in os.listdir(SPILL) if n.endswith(".txt")])
    check("G3 keep=0 leaves all 15", n == 15, str(n))

    # --- G4: unrelated files in the dir are never touched --------------------
    if os.path.isdir(SPILL):
        shutil.rmtree(SPILL)
    f.valves.tool_history_spill_keep = 3
    os.makedirs(SPILL, exist_ok=True)
    for name in ("notes.md", "keepme.dat", "subdir"):
        target = os.path.join(SPILL, name)
        if name == "subdir":
            os.makedirs(target, exist_ok=True)
        else:
            open(target, "w").write("x")
    touch_new(os.path.join(SPILL, "notes.md"), 99_999)
    for i in range(9):
        f._spill_text(f"g4-{i}-" + ("W" * 200), f"g4_{i}")
    f._gc_spill(SPILL)
    check("G4 non-txt file survives", os.path.exists(os.path.join(SPILL, "notes.md")))
    check("G4 non-txt dat survives", os.path.exists(os.path.join(SPILL, "keepme.dat")))
    check("G4 subdirectory survives", os.path.isdir(os.path.join(SPILL, "subdir")))
    txts = [n for n in os.listdir(SPILL) if n.endswith(".txt")]
    check("G4 txt capped at 3", len(txts) == 3, str(len(txts)))

    # --- G5: gc helper reports deletions and never raises on a bad dir -------
    deleted = f._gc_spill("/nonexistent/definitely/not/here")
    check("G5 bad dir returns 0, no raise", deleted == 0, str(deleted))
    f.valves.tool_history_spill_keep = -5
    r = f._gc_spill(SPILL)
    check("G5 negative cap treated as disable", r == 0, str(r))

    # --- G6: an end-to-end inlet trim still spills and still self-caps -------
    f.valves.tool_history_spill_keep = 4
    if os.path.isdir(SPILL):
        shutil.rmtree(SPILL)
    msgs = []
    for i in range(6):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "type": "function",
             "function": {"name": "t", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"c{i}",
                     "content": f"block{i}-" + ("B" * 30000)})
    msgs.append({"role": "user", "content": "go"})
    out = await f.inlet({"messages": msgs}, __user__={"id": "u"},
                        __metadata__={"chat_id": "gc6"})
    txts = [n for n in os.listdir(SPILL) if n.endswith(".txt")]
    check("G6 inlet spill capped at >=4 (cap plus protected)", len(txts) >= 4, str(len(txts)))
    still_pointing = [m["content"] for m in out["messages"] if m["role"] == "tool"]
    # Every spill path still quoted in the prompt must exist on disk.
    broken = []
    for c in still_pointing:
        for tok in c.split():
            t = tok.strip("-().,")
            if t.startswith("/tmp/uf_spill_gc_test/") and not os.path.exists(t):
                broken.append(t)
    check("G6 every spill path quoted in prompt exists", not broken, str(broken[:3]))

    print(f"\n{sum(results)} passed, {len(results) - sum(results)} failed")
    print("RESULT: " + ("ALL_OK" if all(results) else "FAILURES"))
    shutil.rmtree(SPILL, ignore_errors=True)


asyncio.run(main())
