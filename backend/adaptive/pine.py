"""Explicit Pine v5/v6 compiler subset. Unknown statements fail with a line number."""

import re

from fastapi import HTTPException

from backend.adaptive.models import Program

EXAMPLE = """//@version=6
strategy("SMA crossover", overlay=true)
fast = ta.sma(close, 5)
slow = ta.sma(close, 20)
if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
if ta.crossunder(fast, slow)
    strategy.close("Long")
"""


def parse(source):
    numbered = [
        (i, line.rstrip())
        for i, line in enumerate(source.strip().splitlines(), 1)
        if line.strip() and (not line.lstrip().startswith("//") or line.strip().startswith("//@version"))
    ]

    def fail(i, reason):
        raise HTTPException(
            422,
            f"Pine line {i}: {reason}. Supported: v5/v6 long-only SMA/EMA crossover, integer inputs, named signals and simple plots. Other semantics are rejected.",
        )

    if len(numbered) < 8:
        fail(1, "incomplete strategy")
    if not re.fullmatch(r"//@version=[56]", numbered[0][1]):
        fail(1, "version must be 5 or 6")
    if not re.fullmatch(r'strategy\("[^"\n]{1,100}",\s*overlay\s*=\s*true\)', numbered[1][1]):
        fail(numbered[1][0], "unsupported strategy options")
    constants, series, signals, actions, seen = {}, {}, {}, {}, set()
    pending = None
    for i, line in numbered[2:]:
        if pending:
            pattern = (
                r'\s{4}strategy\.entry\("([^"\n]+)",\s*strategy\.long\)'
                if pending[0] == "up"
                else r'\s{4}strategy\.close\("([^"\n]+)"\)'
            )
            m = re.fullmatch(pattern, line)
            if not m:
                fail(i, "expected one indented long entry/close")
            if pending[0] in actions:
                fail(i, "duplicate action")
            actions[pending[0]] = (pending[1], pending[2], m[1])
            pending = None
            continue
        if m := re.fullmatch(r'(\w+)\s*=\s*(?:input\.int\((\d+),\s*"[^"\n]*"\)|(\d+))', line):
            if m[1] in seen:
                fail(i, "duplicate variable")
            seen.add(m[1])
            constants[m[1]] = int(m[2] or m[3])
            continue
        if m := re.fullmatch(r"(\w+)\s*=\s*ta\.(sma|ema)\(close,\s*(\w+)\)", line):
            if m[1] in seen:
                fail(i, "duplicate variable")
            n = int(m[3]) if m[3].isdigit() else constants.get(m[3])
            if n is None or not 2 <= n <= 100:
                fail(i, "unsupported moving average length")
            seen.add(m[1])
            series[m[1]] = (m[2], n)
            continue
        if m := re.fullmatch(r"(\w+)\s*=\s*ta\.cross(over|under)\((\w+),\s*(\w+)\)", line):
            if m[1] in seen:
                fail(i, "duplicate variable")
            seen.add(m[1])
            signals[m[1]] = ("up" if m[2] == "over" else "down", m[3], m[4])
            continue
        if m := re.fullmatch(r"if ta\.cross(over|under)\((\w+),\s*(\w+)\)", line):
            pending = ("up" if m[1] == "over" else "down", m[2], m[3])
            continue
        if m := re.fullmatch(r"if (\w+)", line):
            pending = signals.get(m[1])
            if pending is None:
                fail(i, "unknown condition")
            continue
        if m := re.fullmatch(r'plot\((\w+)(?:,\s*"[^"\n]*")?\)', line):
            if m[1] not in series:
                fail(i, "unknown plot series")
            continue
        fail(i, "unsupported statement")
    if pending or set(actions) != {"up", "down"} or actions["up"] != actions["down"]:
        fail(numbered[-1][0], "entry and exit must use the same pair and order ID")
    f, s, _ = actions["up"]
    if f not in series or s not in series or series[f][0] != series[s][0]:
        fail(1, "matching SMA or EMA series required")
    kind, fast = series[f]
    slow = series[s][1]
    if not 2 <= fast <= 50 or not fast < slow <= 100:
        fail(1, "require fast < slow, fast <=50, slow <=100")
    return {
        "program": Program(kind=kind + "_cross", fast=fast, slow=slow).model_dump(),
        "graph": {
            "nodes": [
                {"id": "fast", "label": f"{kind.upper()} {fast}"},
                {"id": "slow", "label": f"{kind.upper()} {slow}"},
                {"id": "entry", "label": "Cross above → long"},
                {"id": "exit", "label": "Cross below → close"},
            ],
            "edges": [["fast", "entry"], ["slow", "entry"], ["fast", "exit"], ["slow", "exit"]],
        },
        "notes": [
            "Imported entry/exit rules; configure capital, fees, slippage and guardrails separately.",
            "Input defaults are compiled; plots are display-only. Learning filters entry separation at 0, 5, 10 bps.",
            "EMA starts at the first available close; finite warmup can differ from TradingView. No certified broker-emulator equivalence.",
        ],
    }


def export(program):
    if program.kind not in ("sma_cross", "ema_cross"):
        raise HTTPException(422, "Pine export currently supports reviewed SMA/EMA crossover programs")
    kind = program.kind.split("_")[0]
    source = (
        EXAMPLE.replace("SMA crossover", kind.upper() + " crossover")
        .replace("ta.sma", "ta." + kind)
        .replace("close, 5)", f"close, {program.fast})")
        .replace("close, 20)", f"close, {program.slow})")
    )
    # All fields, including otherwise-unused fields, must retain canonical defaults.
    if parse(source)["program"] != program.model_dump():
        raise HTTPException(422, "Reset unused program fields before exporting this crossover")
    return {
        "source": source,
        "program": program.model_dump(),
        "meaning": "Signal rules only; Tracy risk, costs and learned probabilities are in the Bundle",
    }
