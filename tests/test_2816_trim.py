"""v2.8.14 inlet trim: unit tests over a simulated inbound body.
Filter.inlet is async -> run in a loop. Spill dir is the real mounted path so
we also prove the file lands where the assistant's own read_file can see it.
"""
import pathlib
import asyncio, json, os, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import importlib.util

spec = importlib.util.spec_from_file_location("ufx", str(pathlib.Path(__file__).resolve().parent.parent / "unified_filter.py"))
uf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uf)

os.makedirs(os.environ.get("UF_SPILL_TEST") or str(pathlib.Path(__file__).resolve().parent / "_spill_test"), exist_ok=True)
SPILL = os.environ.get("UF_SPILL_TEST") or str(pathlib.Path(__file__).resolve().parent / "_spill_test")
f = uf.Filter()
f.valves.tool_history_spill_dir = SPILL
f.valves.debug_halluc_audit = False

ok = 0
fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
        print("PASS", name)
    else:
        fail += 1
        print("FAIL", name, extra)


async def run_inlet(body):
    return await f.inlet(body, __user__={"id": "t"}, __metadata__={"chat_id": "c"})


def big(n, marker="X"):
    return marker * n


# ---- T1: oversized older tool output is capped, spill written ----
async def t1():
    body = {
        "messages": [
            {"role": "system", "content": "sys"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call_a", "type": "function", "function": {"name": "view_chat", "arguments": "{\"chat_id\":\"x\"}"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": big(50000)},
            {"role": "user", "content": "continue"},
        ]
    }
    out = await run_inlet(body)
    msg = out["messages"][2]
    # This is the only tool block in the body, so it is the newest one and gets the
    # newest cap (40000), not the 12000 older-block cap. The old "< 20000" expectation
    # was only true because of the _stub head+tail floor bug that made every cap above
    # 6000 a dead knob. Now the cap is the budget, so assert against the real one.
    cap = f.valves.tool_history_newest_char_budget
    check("T1 capped under newest budget", len(msg["content"]) <= cap, f'len={len(msg["content"])} cap={cap}')
    check("T1 actually shrank", len(msg["content"]) < 50000, f'len={len(msg["content"])}')
    check("T1 mark present", f.TRIM_MARK in msg["content"])
    check("T1 spill referenced", ".txt" in msg["content"])
    files = os.listdir(SPILL) if os.path.isdir(SPILL) else []
    check("T1 spill file exists", any(x.startswith("call_a") for x in files), str(files))
    if files:
        p = os.path.join(SPILL, [x for x in files if x.startswith("call_a")][0])
        check("T1 spill full text", len(open(p).read()) == 50000)
    check("T1 tool pairing kept", out["messages"][2].get("tool_call_id") == "call_a")
    check("T1 head+tail kept", msg["content"].endswith("X") and "XXXXX" in msg["content"])


# ---- T2: under budget -> untouched ----
async def t2():
    small = big(300, "Y")
    body = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": small},
            {"role": "user", "content": "go"},
        ]
    }
    out = await run_inlet(body)
    check("T2 untouched", out["messages"][1]["content"] == small)


# ---- T3: idempotent - trimmed history re-sent is not re-trimmed/spilled ----
async def t3():
    body = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c2", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c2", "content": big(60000)},
            {"role": "user", "content": "go"},
        ]
    }
    first = (await run_inlet(body))["messages"][1]["content"]
    before_files = len(os.listdir(SPILL))
    body2 = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "c2", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c2", "content": first},
            {"role": "user", "content": "go"},
        ]
    }
    second = (await run_inlet(body2))["messages"][1]["content"]
    check("T3 idempotent", second == first)
    check("T3 no new spill", len(os.listdir(SPILL)) == before_files)


# ---- T4: assistant tool_calls arguments stay valid JSON after trim ----
async def t4():
    huge_args = json.dumps({"content": big(30000, "Z")})
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c3", "function": {"name": "write_file", "arguments": huge_args}}],
            },
            {"role": "tool", "tool_call_id": "c3", "content": "written"},
            {"role": "user", "content": "go"},
        ]
    }
    out = await run_inlet(body)
    args = out["messages"][0]["tool_calls"][0]["function"]["arguments"]
    try:
        parsed = json.loads(args)
        check("T4 args valid JSON", True)
        check("T4 args flagged trimmed", parsed.get("unified_filter_trimmed") is True)
        check("T4 shorter", len(args) < len(huge_args))
    except Exception as e:
        check("T4 args valid JSON", False, repr(e))


# ---- T5: newest tool result gets the bigger cap ----
async def t5():
    # Pin the total budget above the fixture sum. At the default 60000 a 20000+50000
    # pair trips the total pass, which pulls BOTH blocks down to the same size and
    # masks the per-block newest-gets-more-headroom rule this test is about.
    f.valves.tool_history_total_char_budget = 400000
    body = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "o1", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "o1", "content": big(20000, "O")},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "n1", "function": {"name": "t", "arguments": "{}"}}]},
            # Newest cap is 40000, so this block has to clear THAT number or it is
            # correctly left whole and the "both trimmed" assertion is meaningless.
            {"role": "tool", "tool_call_id": "n1", "content": big(50000, "N")},
            {"role": "user", "content": "go"},
        ]
    }
    out = await run_inlet(body)
    old, new = out["messages"][1]["content"], out["messages"][3]["content"]
    check("T5 both trimmed", f.TRIM_MARK in old and f.TRIM_MARK in new)
    check("T5 newest kept more", len(new) > len(old), f"new={len(new)} old={len(old)}")
    f.valves.tool_history_total_char_budget = 60000


# ---- T6: list-shaped tool content with an image part keeps the image ----
async def t6():
    body = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "im", "function": {"name": "t", "arguments": "{}"}}]},
            {
                "role": "tool",
                "tool_call_id": "im",
                "content": [
                    # Only tool block in the body = newest = 40000 cap, so 25000 was
                    # never eligible for a trim. Sized past the newest cap instead.
                    {"type": "input_text", "text": big(50000, "T")},
                    {"type": "input_image", "image_url": "http://x/y.png"},
                ],
            },
            {"role": "user", "content": "go"},
        ]
    }
    out = await run_inlet(body)
    parts = out["messages"][1]["content"]
    check("T6 text part trimmed", f.TRIM_MARK in parts[0]["text"])
    check("T6 image part intact", parts[1].get("image_url") == "http://x/y.png")


# ---- T7: subcall path untouched (no trim) ----
async def t7():
    sentinel = uf.SELF_CALL_SENTINEL
    body = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "s1", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "s1", "content": big(50000, "S")},
            {"role": "user", "content": sentinel + "please continue"},
        ]
    }
    out = await run_inlet(body)
    check("T7 subcall not trimmed", len(out["messages"][1]["content"]) == 50000)


# ---- T8: valve off = no trim at all ----
async def t8():
    f.valves.trim_oversized_tool_history = False
    body = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "v1", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "v1", "content": big(50000, "V")},
            {"role": "user", "content": "go"},
        ]
    }
    out = await run_inlet(body)
    check("T8 valve off", len(out["messages"][1]["content"]) == 50000)
    f.valves.trim_oversized_tool_history = True


# ---- T9: total-budget pass pulls an over-total set under the cap ----
async def t9():
    f.valves.tool_history_char_budget = 0  # disable pass 1, total pass only
    f.valves.tool_history_total_char_budget = 30000
    body = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "m1", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "m1", "content": big(14000, "1")},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "m2", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "m2", "content": big(14000, "2")},
            {"role": "user", "content": "go"},
        ]
    }
    out = await run_inlet(body)
    total = sum(len(m["content"]) for m in out["messages"] if m["role"] == "tool")
    check("T9 total under cap", total <= 30000 + 4000, f"total={total}")
    f.valves.tool_history_char_budget = 12000
    f.valves.tool_history_total_char_budget = 60000


# ---- T10: event emitter called once when trimming, zero when not ----
async def t10():
    events = []

    async def emit(ev):
        events.append(ev)

    body = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "e1", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "e1", "content": big(60000, "E")},
            {"role": "user", "content": "go"},
        ]
    }
    await f.inlet(body, __user__={"id": "t"}, __metadata__={}, __event_emitter__=emit)
    check("T10 notice emitted", len(events) == 1 and events[0]["type"] == "notice", str(events))
    events.clear()
    body2 = {
        "messages": [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "e2", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "e2", "content": "tiny"},
            {"role": "user", "content": "go"},
        ]
    }
    await f.inlet(body2, __user__={"id": "t"}, __metadata__={}, __event_emitter__=emit)
    check("T10 no notice when clean", len(events) == 0)


async def main():
    for t in (t1, t2, t3, t4, t5, t6, t7, t8, t9, t10):
        try:
            await t()
        except Exception as e:
            check(f"{t.__name__} raised", False, repr(e))
    print(f"\n{ok} passed, {fail} failed")
    return fail


sys.exit(asyncio.run(main()))
