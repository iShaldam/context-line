#!/usr/bin/env python3
"""Replay your own Claude Code transcripts under two what-ifs:
 - context-mode-like: big tool results (>=10KB) shrink 90%
 - context-line-like: session cut to a fresh one when context passes 150k
Cost units are relative to 1 uncached input token: read 0.1, write 2.0 (1h) / 1.25 (5m).
Main-chain turns only (subagent transcripts are separate files and are skipped).
Prints aggregates only. Env: REPLAY_SKIP=substr,substr skips project folders whose
name contains one; REPLAY_CM_KB / REPLAY_CM_SHRINK tune the context-mode what-if;
REPLAY_OVERHEAD_TOKENS adds a per-session cost for a tool's own definitions.
"""
import glob, json, os, sys
from datetime import datetime

LINE = 150_000
HANDOFF = 3_000
BIG_CHARS = int(float(os.environ.get('REPLAY_CM_KB', 10)) * 1000)
CM_SHRINK = float(os.environ.get('REPLAY_CM_SHRINK', 0.90))
OVERHEAD = int(os.environ.get('REPLAY_OVERHEAD_TOKENS', 0))
SKIP = [x for x in os.environ.get('REPLAY_SKIP', '').split(',') if x]
IMG_TOK = 1500  # tokens per screenshot, estimate
CPT = 3.6  # chars per token estimate for tool results
TTL = 3600


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def load(path):
    turns = {}   # message id -> dict
    order = []
    results = []  # (timestamp, tokens) of tool results
    for l in open(path, errors="ignore"):
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("isSidechain"):
            continue
        t = d.get("type")
        if t == "assistant":
            m = d.get("message", {})
            u = m.get("usage") or {}
            mid = m.get("id") or d.get("requestId") or d.get("uuid")
            if "input_tokens" not in u:
                continue
            cc = u.get("cache_creation") or {}
            w1 = cc.get("ephemeral_1h_input_tokens", 0)
            w5 = cc.get("ephemeral_5m_input_tokens", 0)
            if not (w1 or w5):
                w1 = u.get("cache_creation_input_tokens", 0)
            rec = dict(ts=ts(d["timestamp"]), inp=u.get("input_tokens", 0),
                       rd=u.get("cache_read_input_tokens", 0), w1=w1, w5=w5,
                       out=u.get("output_tokens", 0))
            if mid not in turns:
                order.append(mid)
            turns[mid] = rec
        elif t == "user":
            c = d.get("message", {}).get("content")
            if isinstance(c, list):
                n = 0
                ni = 0
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        x = b.get("content")
                        if isinstance(x, list):
                            n += sum(len(i.get("text", "")) for i in x if isinstance(i, dict))
                            ni += sum(1 for i in x if isinstance(i, dict) and i.get("type") == "image")
                        elif isinstance(x, str):
                            n += len(x)
                if n or ni:
                    results.append((ts(d["timestamp"]), n, ni))
    seq = sorted((turns[i] for i in order), key=lambda r: r["ts"])
    return seq, sorted(results)


def cost(r):
    return r["inp"] + 0.1 * r["rd"] + 2.0 * r["w1"] + 1.25 * r["w5"]


tot = dict(turns=0, cost=0.0, tok=0, over_turns=0, over_cost=0.0, over_tok=0,
           bigres_tokens=0, allres_tokens=0, cm_saved=0.0, cl_saved=0.0, cl_cuts=0,
           cold_turns=0, cold_write_tok=0, cold_cost=0.0, cold_over_turns=0,
           cold_over_write_tok=0, cold_over_cost=0.0, out=0, sessions=0, img_tokens=0, overhead=0.0)

root = os.path.expanduser("~/.claude/projects")
for d in sorted(os.listdir(root)):
    if any(x in d for x in SKIP):
        continue
    for f in glob.glob(os.path.join(root, d, "*.jsonl")):
        seq, results = load(f)
        if len(seq) < 3:
            continue
        tot["sessions"] += 1
        tot["overhead"] += OVERHEAD * (0.1 * len(seq) + 2.0)
        base = seq[0]["inp"] + seq[0]["rd"] + seq[0]["w1"] + seq[0]["w5"]
        ri = 0
        cm_cum = 0.0      # tokens of shrunk savings currently in context
        cl_off = 0.0      # tokens removed from context by cuts so far
        prev_ctx = None
        prev_ts = None
        for r in seq:
            ctx = r["inp"] + r["rd"] + r["w1"] + r["w5"]
            tot["turns"] += 1
            c = cost(r)
            tot["cost"] += c
            tot["tok"] += ctx
            tot["out"] += r["out"]
            over = ctx > LINE
            if over:
                tot["over_turns"] += 1
                tot["over_cost"] += c
                tot["over_tok"] += ctx
            # compaction / reset detection: context fell a lot
            if prev_ctx and ctx < 0.6 * prev_ctx:
                cm_cum = 0.0
                cl_off = 0.0
            # new tool results since previous turn
            new_saved = 0.0
            while ri < len(results) and results[ri][0] <= r["ts"]:
                tot["img_tokens"] += results[ri][2] * IMG_TOK
                tok = results[ri][1] / CPT
                tot["allres_tokens"] += tok
                if results[ri][1] >= BIG_CHARS:
                    tot["bigres_tokens"] += tok
                    s = CM_SHRINK * tok
                    cm_cum += s
                    new_saved += s
                ri += 1
            # context-mode what-if: read discount on all saved tokens in ctx, write
            # instead of read on the turn they first appear
            tot["cm_saved"] += 0.1 * (cm_cum - new_saved) + 2.0 * new_saved
            # context-line what-if
            eff = ctx - cl_off
            if eff > LINE:
                # cut: fresh session with base + handoff; one-time write of that base
                cut = eff - (base + HANDOFF)
                if cut > 0:
                    cl_off += cut
                    tot["cl_cuts"] += 1
                    tot["cl_saved"] -= 2.0 * (base + HANDOFF)  # fresh session writes its base once
            if cl_off > 0:
                tot["cl_saved"] += 0.1 * cl_off
            # cold resume (gap past TTL) — the cache rebuild the guard targets
            if prev_ts is not None and r["ts"] - prev_ts > TTL:
                tot["cold_turns"] += 1
                tot["cold_write_tok"] += r["w1"] + r["w5"]
                tot["cold_cost"] += 2.0 * (r["w1"] + r["w5"])
                if over:
                    tot["cold_over_turns"] += 1
                    tot["cold_over_write_tok"] += r["w1"] + r["w5"]
                    tot["cold_over_cost"] += 2.0 * (r["w1"] + r["w5"])
            prev_ctx = ctx
            prev_ts = r["ts"]

pct = lambda a, b: f"{100 * a / b:.1f}%" if b else "n/a"
print(f"sessions {tot['sessions']}  main-chain turns {tot['turns']:,}")
print(f"context tokens sent (all turns): {tot['tok']/1e6:.1f}M  cost units {tot['cost']/1e6:.1f}M")
print(f"turns above {LINE//1000}k: {tot['over_turns']:,} ({pct(tot['over_turns'], tot['turns'])} of turns), "
      f"{pct(tot['over_tok'], tot['tok'])} of tokens, {pct(tot['over_cost'], tot['cost'])} of cost")
print(f"tool results: {tot['allres_tokens']/1e6:.1f}M tokens entered context; "
      f"{pct(tot['bigres_tokens'], tot['allres_tokens'])} of that is in results >={BIG_CHARS//1000}KB")
print(f"screenshots (est {IMG_TOK} tok each): {tot['img_tokens']/1e6:.1f}M tokens entered context = {pct(tot['img_tokens'], tot['img_tokens']+tot['allres_tokens'])} of all tool-result tokens; context-mode can't shrink these")
print(f"WHAT-IF context-mode ({CM_SHRINK:.0%} off results >={BIG_CHARS//1000}KB): saves {pct(tot['cm_saved'], tot['cost'])} of cost"
      + (f", minus {pct(tot['overhead'], tot['cost'])} for its {OVERHEAD} tokens of tool definitions"
         f" = {pct(tot['cm_saved'] - tot['overhead'], tot['cost'])} net" if OVERHEAD else ""))
print(f"WHAT-IF context-line (cut to fresh at {LINE//1000}k, {tot['cl_cuts']} cuts): saves {pct(tot['cl_saved'], tot['cost'])} of cost")
print(f"cold resumes (idle >1h): {tot['cold_turns']:,} turns, {tot['cold_write_tok']/1e6:.1f}M tokens rewritten, "
      f"{pct(tot['cold_cost'], tot['cost'])} of cost; of those over the line: {tot['cold_over_turns']:,} turns, "
      f"{tot['cold_over_write_tok']/1e6:.1f}M tokens, {pct(tot['cold_over_cost'], tot['cost'])} of cost")
print(f"output tokens (same either way): {tot['out']/1e6:.1f}M")
