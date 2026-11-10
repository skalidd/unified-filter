"""Regression test for the v2.8.3 continuation-echo fix, driving the real outlet
loop with a MOCKED sub-call (no model inference).

Scenario (the real 20:51:39 shape from chat b2ee2d58): a turn whose visible text
was streamed, followed by an INCOMPLETE trailing reasoning item -> the outlet
heals via sub-call, and the sub-call re-emits text already displayed plus one
genuinely new sentence.

Under 2.8.2 the duplicate block landed in `content` and the trailing message
item. Under 2.8.3 only the new sentence should survive.

A control pass re-runs the same scenario with _dedupe_continuation neutered to
prove the assertions actually detect the bug (guards against a vacuous test).
"""
import pathlib
import asyncio
import copy
import importlib.util
import json
import re
import sys

SRC = sys.argv[1] if len(sys.argv) > 1 else str(pathlib.Path(__file__).resolve().parent.parent / "unified_filter.py")
LT, GT = chr(60), chr(62)
RAW = re.compile(LT + r"(/?)(tool_call|function_call|think|thought)" + GT)

spec = importlib.util.spec_from_file_location("ufx", SRC)
mod = importlib.util.module_from_spec(spec)
sys.modules["ufx"] = mod
spec.loader.exec_module(mod)

ALREADY = (
    "Reading the outlet heal block before patching:\n"
    "The fourteen hits are all in the start_tag and end_tag metadata fields, "
    "not leaked text, so real pollution is far smaller than estimated."
)
NEW_TAIL = "The echo fix is a prefix-overlap dedup applied before appending healed text."
ECHOED = ALREADY + "\n" + NEW_TAIL


def txt_item(t, mid="m0"):
    return {"type": "message", "id": mid, "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": t}]}


def reasoning_item(status="incomplete", rid="r0"):
    return {"type": "reasoning", "id": rid, "status": status,
            "summary": [{"type": "summary_text", "text": "I will patch the dedup next."}]}


def make_body():
    return {
        "model": "mock-model",
        "messages": [
            {"role": "user", "content": "fix the echo bug please"},
            {"role": "assistant", "content": ALREADY,
             "output": [txt_item(ALREADY), reasoning_item("incomplete")]},
        ],
    }


def run_case(label, neuter):
    flt = mod.Filter()
    flt.valves.owui_api_key = "sk-mock-not-real"
    flt.valves.heal_truncated_streams = True

    calls = []

    async def fake_call(payload, headers):
        calls.append(payload)
        return {"choices": [{"message": {"content": ECHOED}}]}

    flt._call_owui_async = fake_call

    if neuter:
        flt._dedupe_continuation = staticmethod(lambda d, n: n)

    events = []

    async def emitter(ev):
        events.append(ev)

    out = asyncio.run(flt.outlet(make_body(), None, None, __event_emitter__=emitter))
    final = out["messages"][-1]
    content = final["content"]
    items = final.get("output") or []
    msg_text = "\n".join(
        "".join(p.get("text", "") for p in (i.get("content") or []))
        for i in items if i.get("type") == "message"
    )
    return label, calls, content, items, msg_text


def check(label, calls, content, items, msg_text):
    ok = True
    print(f"\n--- {label} ---")
    print("sub-calls:", len(calls), "| item types:", [i.get("type") for i in items])
    print("content repr:", repr(content[:200]))

    if not calls:
        print("FAIL heal sub-call never fired - scenario did not exercise the loop")
        return False

    dup_lines = [ln for ln in dict.fromkeys(content.splitlines())
                 if ln.strip() and content.count(ln) > 1]
    if dup_lines:
        print("FAIL duplicated lines in content:", [d[:50] for d in dup_lines[:3]])
        ok = False
    else:
        print("PASS no duplicated lines in content")

    if msg_text.count(ALREADY) > 1 or msg_text.count(NEW_TAIL) > 1:
        print("FAIL duplicate block in message items:", repr(msg_text[:160]))
        ok = False
    else:
        print("PASS message items not duplicated")

    if NEW_TAIL not in content:
        print("FAIL new sentence dropped from content")
        ok = False
    else:
        print("PASS new sentence kept")

    for name, blob in (("content", content), ("message items", msg_text)):
        hits = RAW.findall(blob)
        if hits:
            print(f"FAIL raw markup in {name}: {hits[:4]}")
            ok = False
        else:
            print(f"PASS clean of raw markup: {name}")

    incomplete = [i for i in items if isinstance(i, dict)
                  and i.get("type") == "reasoning"
                  and i.get("status") in ("incomplete", "in_progress", "failed")]
    if incomplete:
        print("FAIL reasoning left incomplete:", [i.get("id") for i in incomplete])
        ok = False
    else:
        print("PASS trailing reasoning status flipped")

    return ok


neutralised = run_case("CONTROL (dedup neutered = 2.8.2 behaviour)", neuter=True)
fixed = run_case("FIXED (v2.8.3)", neuter=False)

print("\n" + "=" * 70)
control_ok = check(*neutralised)
fixed_ok = check(*fixed)

print("\n" + "=" * 70)
if control_ok:
    print("VACUOUS: the control passed, so these assertions do not detect the echo bug")
    sys.exit(2)
print("control correctly FAILS (echo bug reproduced with dedup neutered)")

if not fixed_ok:
    print("ECHO_TEST_FAILED")
    sys.exit(1)
print("ECHO_TEST_OK  (2.8.2 shape fails, 2.8.3 passes)")
