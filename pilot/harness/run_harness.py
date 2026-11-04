"""SyncSL 시범 서비스 검증 하네스.

실제 서버(FastAPI + WebSocket)를 띄우고, 가상 운영 콘솔(STT 시뮬레이터)과 가상 태블릿 N대를 붙여
기독교·천주교·불교 시나리오를 흘려보낸 뒤 지표를 재고 게이트로 판정한다.

  python -m harness.run_harness            # 전체 (약 1~2분)
  python -m harness.run_harness --quick    # realistic 프로필만

결과: harness/out/report.json, harness/out/report.html
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
import websockets

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from app.agent import AgentStats, validate          # noqa: E402
from app.corpus import Corpus                       # noqa: E402
from app.main import create_app                     # noqa: E402
from harness.metrics import gloss_scores, mean, pct  # noqa: E402
from harness.stt_sim import SimulatedSTT, cer       # noqa: E402

PAUSE_S = 1.2            # 문장 사이 쉼 (가상 시계)


# ---------------------------------------------------------------- 가짜 AI Agent (장애 주입용)
class FaultyAgent:
    """지연(0.2~2.5초)과 엉터리 출력(25%)을 일부러 내는 Agent. 정확도가 아니라
    '느리거나 틀린 Agent가 자막을 막거나 잘못된 gloss를 내보내지 않는가'를 본다."""

    def __init__(self, timeout_s=1.5, seed=3):
        self.timeout_s, self.rng, self.stats = timeout_s, random.Random(seed), AgentStats()

    def refine(self, text, domain, draft, hits, allowed):
        self.stats.calls += 1
        lat = self.rng.uniform(0.2, 2.5)
        time.sleep(min(lat, self.timeout_s))
        self.stats.latencies_ms.append(min(lat, self.timeout_s) * 1000)
        if lat > self.timeout_s:
            self.stats.timeouts += 1
            return None
        out = ["할렐루야빔", "XYZ", "로켓", "우주선"] if self.rng.random() < 0.25 else \
            [g for g in draft if not g.startswith("FS:")] or draft
        ok = validate(out, allowed, draft)
        if ok is None:
            self.stats.rejected += 1
        else:
            self.stats.accepted += 1
        return ok


# ---------------------------------------------------------------- 서버
class ServerThread:
    def __init__(self, app):
        s = socket.socket(); s.bind(("127.0.0.1", 0)); self.port = s.getsockname()[1]; s.close()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port,
                                                    log_level="warning", ws_ping_interval=None))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.02)
        return self

    def __exit__(self, *a):
        self.server.should_exit = True
        self.thread.join(5)


class Viewer:
    def __init__(self, url):
        self.url, self.msgs, self.ws, self.task, self.last_seq = url, [], None, None, 0

    async def connect(self, since=0):
        self.ws = await websockets.connect(f"{self.url}&since={since}", max_size=2**22)
        self.task = asyncio.create_task(self._recv())

    async def _recv(self):
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                m["_recv"] = time.time()
                self.msgs.append(m)
                self.last_seq = max(self.last_seq, m.get("seq", 0))
        except websockets.ConnectionClosed:
            pass

    async def close(self):
        await self.ws.close()
        await self.task


# ---------------------------------------------------------------- 한 시나리오 실행
OPERATOR_TAP_S = 1.0     # 운영자가 듣고 '상위 문장 10개' 버튼을 누르기까지 걸린다고 가정한 시간


async def run_scenario(port, vclock, scenario, profile, n_viewers, reconnect, seed=7, assist=False):
    room = f"{scenario['domain']}-{profile}-{n_viewers}"
    base = f"ws://127.0.0.1:{port}"
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/rooms/{room}/session",
                                 json.dumps({"domain": scenario["domain"]}).encode(),
                                 {"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()

    viewers = [Viewer(f"{base}/ws/viewer?room={room}") for _ in range(n_viewers)]
    for v in viewers:
        await v.connect()
    op = await websockets.connect(f"{base}/ws/operator?room={room}", max_size=2**22)
    stt = SimulatedSTT(profile, seed)
    utts = scenario["utterances"]
    records, reconnect_info = [], None
    drop_at = len(utts) // 2 if reconnect else -1
    gap_seqs = []

    for i, u in enumerate(utts):
        if i == drop_at:
            v0_since = viewers[0].last_seq
            await viewers[0].close()
        out = stt.run(u["text"])
        vclock["t"] += out.speech_s
        tapped = False
        if assist and u["category"] == "fixed":
            sugg = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/rooms/{room}/suggest").read())
            hit = next((s for s in sugg if s["text"] == u["text"]), None)
            if hit:
                tapped = True
                out.final_latency_s, out.final = OPERATOR_TAP_S, u["text"]
                vclock["t"] += OPERATOR_TAP_S
                t_send = time.time()
                packets = [json.loads(urllib.request.urlopen(urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/rooms/{room}/phrase/{hit['order']}", b"{}",
                    {"Content-Type": "application/json"})).read())]
        if not tapped:
            for ptxt in out.partials:                     # 말하는 동안 partial 자막
                await op.send(json.dumps({"type": "partial", "text": ptxt}))
            vclock["t"] += out.final_latency_s
            t_send = time.time()
            await op.send(json.dumps({"type": "final", "text": out.final, "t_speech_end": t_send}))
            ack = json.loads(await op.recv())
            while ack.get("type") != "ack":
                ack = json.loads(await op.recv())
            packets = ack["packets"]
        want = max(p["seq"] for p in packets) if packets else 0
        in_gap = reconnect and drop_at <= i < drop_at + 2
        live = [v for v in viewers if not (in_gap and v is viewers[0])]
        t_wait = time.time()
        while any(v.last_seq < want for v in live) and time.time() - t_wait < 5:
            await asyncio.sleep(0.005)
        if in_gap:
            gap_seqs += [p["seq"] for p in packets]
        if reconnect and i == drop_at + 1:
            await viewers[0].connect(since=v0_since)
            await asyncio.sleep(0.2)
            got = [m["seq"] for m in viewers[0].msgs if m.get("replay")]
            reconnect_info = {"missed": gap_seqs, "replayed": got,
                              "recovered": set(gap_seqs[-3:]).issubset(set(got))}
        vclock["t"] += PAUSE_S

        def delivery(mtype, seqs):
            ds = []
            for v in live:
                for m in v.msgs:
                    if m.get("type") == mtype and m.get("seq") in seqs and not m.get("replay"):
                        ds.append(m["_recv"] - t_send)
            return ds
        sign_seqs = {p["seq"] for p in packets}
        cap_seqs = {s - 1 for s in sign_seqs}         # caption.final은 sign 바로 앞 seq
        d_sign, d_cap = delivery("sign", sign_seqs), delivery("caption.final", cap_seqs)
        pred = [g for p in packets for g in p["glosses"]]
        items = [it for p in packets for it in p["playlist"] if it["kind"] != "marker"]
        records.append({
            **u, "profile": profile, "tapped": tapped, "stt_final": out.final, "cer": cer(u["text"], out.final),
            "pred": " ".join(pred), "modes": [p["mode"] for p in packets],
            "confidence": min((p["confidence"] for p in packets), default=0),
            **gloss_scores(pred, u["gold"].split()),
            "stt_latency_s": out.final_latency_s,
            "deliver_sign_ms": [d * 1000 for d in d_sign], "deliver_cap_ms": [d * 1000 for d in d_cap],
            "e2e_sign_s": out.final_latency_s + (max(d_sign) if d_sign else 9),
            "e2e_cap_s": out.final_latency_s + (max(d_cap) if d_cap else 9),
            "kinds": [it["kind"] for it in items], "sign_ms": sum(p["total_ms"] for p in packets),
            "lag_ms": max((p["start_in_ms"] for p in packets), default=0),
            "rate": max((p["rate"] for p in packets), default=1), "flush": any(p["flush"] for p in packets),
            "broadcast_glosses": pred,
        })

    await asyncio.sleep(0.3)
    order_ok, dup = True, 0
    for v in viewers:
        seqs = [m["seq"] for m in v.msgs if m.get("type") == "sign" and not m.get("replay")]
        dup += len(seqs) - len(set(seqs))
        order_ok &= seqs == sorted(seqs)
    expected = {m["seq"] for v in viewers[1:] for m in v.msgs if m.get("type") == "sign"}
    complete = all({m["seq"] for m in v.msgs if m.get("type") == "sign"} >= expected for v in viewers[1:])
    for v in viewers:
        await v.close()
    await op.close()
    return records, {"order_ok": order_ok, "duplicates": dup, "complete": complete,
                     "reconnect": reconnect_info, "viewers": n_viewers}


# ---------------------------------------------------------------- 실행 계획
async def main_async(quick: bool):
    corpus = Corpus.load()
    scenarios = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "scenarios").glob("*.json"))]
    profiles = ["realistic"] if quick else ["clean", "realistic", "noisy"]
    runs = []

    vclock = {"t": 0.0}
    app = create_app(corpus, agent=None, clock=lambda: vclock["t"])
    with ServerThread(app) as srv:
        for prof in profiles:
            for sc in scenarios:
                recs, deliv = await run_scenario(srv.port, vclock, sc, prof, 3, reconnect=(prof == "realistic"))
                runs.append({"name": f"{sc['domain']}/{prof}", "kind": "quality", "profile": prof,
                             "domain": sc["domain"], "records": recs, "delivery": deliv})
        for sc in scenarios:
            recs, deliv = await run_scenario(srv.port, vclock, sc, "realistic", 3, reconnect=False, seed=7, assist=True)
            runs.append({"name": f"{sc['domain']}/operator-assist", "kind": "assist", "profile": "realistic",
                         "domain": sc["domain"], "records": recs, "delivery": deliv})
        recs, deliv = await run_scenario(srv.port, vclock, scenarios[0], "realistic", 30, reconnect=False, seed=11)
        runs.append({"name": f"{scenarios[0]['domain']}/load-30", "kind": "load", "profile": "realistic",
                     "domain": scenarios[0]["domain"], "records": recs, "delivery": deliv})
        processing = list(app.state.pipe.timings_ms)
        playback = {k: {"flushes": c.flushes, "catchups": c.catchups} for k, c in app.state.pipe.clocks.items()}

    agent = FaultyAgent()
    vclock2 = {"t": 0.0}
    app2 = create_app(corpus, agent=agent, clock=lambda: vclock2["t"])
    allowed = app2.state.pipe.translator.allowed_vocab(app2.state.pipe.session("x"))
    with ServerThread(app2) as srv:
        sc = next(s for s in scenarios if s["domain"] == "catholic")
        recs, deliv = await run_scenario(srv.port, vclock2, sc, "noisy", 3, reconnect=False, seed=5)
        runs.append({"name": "catholic/agent-fault", "kind": "agent", "profile": "noisy", "domain": "catholic",
                     "records": recs, "delivery": deliv})
    leaked = sorted({g for r in recs for g in r["broadcast_glosses"]
                     if g not in allowed and not g.startswith("FS:") and not g.isdigit()})
    agent_info = {"calls": agent.stats.calls, "accepted": agent.stats.accepted,
                  "rejected": agent.stats.rejected, "timeouts": agent.stats.timeouts, "leaked_tokens": leaked}
    return runs, processing, playback, agent_info, corpus


def summarize(runs, processing, playback, agent_info, corpus):
    def sel(kind="quality", profile=None, category=None, split=None, domain=None):
        out = []
        for r in runs:
            if r["kind"] != kind or (profile and r["profile"] != profile) or (domain and r["domain"] != domain):
                continue
            out += [x for x in r["records"] if (not category or x["category"] == category)
                    and (not split or x["split"] in split)]
        return out

    def quality(recs):
        return {"n": len(recs), "exact": mean([r["exact"] for r in recs]),
                "order_f1": mean([r["order_f1"] for r in recs]), "cer": mean([r["cer"] for r in recs])}

    table = {}
    for prof in ("clean", "realistic", "noisy"):
        for cat, split in (("fixed", ["fixed"]), ("paraphrase", ["dev"]), ("paraphrase", ["holdout"]),
                           ("free", ["dev"]), ("free", ["holdout"])):
            recs = sel(profile=prof, category=cat, split=split)
            if recs:
                table[f"{prof}|{cat}|{split[0]}"] = quality(recs)
    by_domain = {f"{d}|{c}": quality(sel(profile="realistic", category=c, domain=d,
                                         split=["fixed", "holdout"]))
                 for d in ("protestant", "catholic", "buddhist") for c in ("fixed", "paraphrase", "free")}

    real = sel(profile="realistic")
    fixed_real = sel(profile="realistic", category="fixed")
    kinds = [k for r in fixed_real for k in r["kinds"]]
    kinds_all = [k for r in real for k in r["kinds"]]
    load = [r for x in runs if x["kind"] == "load" for r in x["records"]]
    agent_recs = [r for x in runs if x["kind"] == "agent" for r in x["records"]]
    lat = {
        "e2e_caption_p95_s": pct([r["e2e_cap_s"] for r in real], .95),
        "e2e_sign_p95_s": pct([r["e2e_sign_s"] for r in real], .95),
        "e2e_sign_p50_s": pct([r["e2e_sign_s"] for r in real], .5),
        "deliver_sign_p95_ms": pct([d for r in real for d in r["deliver_sign_ms"]], .95),
        "processing_p95_ms": pct(processing, .95),
        "load30_deliver_p95_ms": pct([d for r in load for d in r["deliver_sign_ms"]], .95),
        "agent_caption_deliver_p95_ms": pct([d for r in agent_recs for d in r["deliver_cap_ms"]], .95),
        "agent_sign_deliver_p95_ms": pct([d for r in agent_recs for d in r["deliver_sign_ms"]], .95),
        "playback_lag_p95_s": (pct([r["lag_ms"] for r in real], .95) or 0) / 1000,
        "sign_vs_speech_ratio": mean([r["sign_ms"] / 1000 / max(0.3, len(r["text"].replace(' ', '')) / 5.5)
                                      for r in real]),
    }
    assist = [r for x in runs if x["kind"] == "assist" for r in x["records"] if r["category"] == "fixed"]
    lat["assist_tap_rate"] = mean([float(r["tapped"]) for r in assist])
    lat["assist_fixed_exact"] = mean([r["exact"] for r in assist])
    tmpl = [r for r in real if r["category"] != "fixed" and "template" in r["modes"]]
    tmpl_wrong = [r for r in tmpl if r["order_f1"] < 0.8]
    lat["template_on_nonfixed"] = len(tmpl)
    lat["template_wrong_rate"] = len(tmpl_wrong) / max(1, len(tmpl))
    cov = {"fixed_clip": kinds.count("clip") / max(1, len(kinds)),
           "all_clip": kinds_all.count("clip") / max(1, len(kinds_all)),
           "all_fingerspell": kinds_all.count("fingerspell") / max(1, len(kinds_all)),
           "all_card": kinds_all.count("card") / max(1, len(kinds_all))}
    deliveries = [r["delivery"] for r in runs]
    recon = [r["delivery"]["reconnect"] for r in runs if r["delivery"]["reconnect"]]

    q = lambda k, f="order_f1": (table.get(k) or {}).get(f) or 0
    gates = [
        ("G1", "정형 문장 정확 일치율 (realistic STT)", q("realistic|fixed|fixed", "exact"), ">=", 0.85),
        ("G1b", "정형 문장 정확 일치율 (운영자 '상위 10문장' 원탭 병행)", lat["assist_fixed_exact"], ">=", 0.95),
        ("G2", "변형 문장 순서 F1 (holdout, realistic)", q("realistic|paraphrase|holdout"), ">=", 0.70),
        ("G3", "자유 발화(설교·강론·법문) 순서 F1 (holdout, realistic)", q("realistic|free|holdout"), ">=", 0.70),
        ("G4", "한국어 자막 종단 지연 p95 (초)", lat["e2e_caption_p95_s"], "<=", 2.0),
        ("G5", "수어 패킷 종단 지연 p95 (초)", lat["e2e_sign_p95_s"], "<=", 2.0),
        ("G6", "서버 번역+재생계획 처리 p95 (ms)", lat["processing_p95_ms"], "<=", 50),
        ("G7", "방송 순서·중복·누락 (모든 태블릿)", float(all(d["order_ok"] and d["complete"] and d["duplicates"] == 0
                                                for d in deliveries)), ">=", 1.0),
        ("G8", "재접속 시 놓친 문장 복구", float(bool(recon) and all(r["recovered"] for r in recon)), ">=", 1.0),
        ("G9", "태블릿 30대 동시 전달 p95 (ms)", lat["load30_deliver_p95_ms"], "<=", 300),
        ("G10", "Agent 지연·오류 중 자막 전달 p95 (ms)", lat["agent_caption_deliver_p95_ms"], "<=", 300),
        ("G11", "Agent 엉터리 출력 방송 유출 (개수)", float(len(agent_info["leaked_tokens"])), "<=", 0),
        ("G12", "수어 재생 밀림 p95 (초)", lat["playback_lag_p95_s"], "<=", 3.0),
        ("G13", "정형 문장 실사 클립 등록 비율", cov["fixed_clip"], ">=", 0.80),
        ("G14", "템플릿 오적용 비율 (변형·자유 발화에 엉뚱한 검수 문장 적용)", lat["template_wrong_rate"], "<=", 0.10),
    ]
    gate_rows = [{"id": g, "name": n, "value": v, "op": op, "threshold": t,
                  "pass": (v is not None) and (v >= t if op == ">=" else v <= t)} for g, n, v, op, t in gates]
    worst = sorted([r for r in real if r["category"] != "fixed"], key=lambda r: r["order_f1"])[:12]
    fixed_fail = [r for r in fixed_real if not r["exact"]]
    return {"generated": time.strftime("%Y-%m-%d %H:%M"), "gates": gate_rows, "quality": table,
            "by_domain": by_domain, "latency": lat, "coverage": cov, "agent": agent_info,
            "playback": playback, "deliveries": [{"run": r["name"], **r["delivery"]} for r in runs],
            "examples_worst": [{k: r[k] for k in ("domain_text", "text", "stt_final", "gold", "pred", "order_f1", "category", "split")
                                if k in r} for r in worst],
            "fixed_failures": [{k: r[k] for k in ("text", "stt_final", "gold", "pred")} for r in fixed_fail],
            "counts": {"utterances": sum(len(r["records"]) for r in runs), "runs": len(runs),
                       "phrasebank": len(corpus.phrases), "lexicon_glosses": len(corpus.vocab),
                       "clips_registered": len(corpus.clips)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    runs, processing, playback, agent_info, corpus = asyncio.run(main_async(a.quick))
    rep = summarize(runs, processing, playback, agent_info, corpus)
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "runs.json").write_text(json.dumps(runs, ensure_ascii=False), encoding="utf-8")
    from harness.report import render
    (out / "report.html").write_text(render(rep), encoding="utf-8")
    for g in rep["gates"]:
        v = g["value"]
        print(f"{'PASS' if g['pass'] else 'FAIL'}  {g['id']:<4} {g['name']}: "
              f"{v if v is None else round(v, 3)} ({g['op']} {g['threshold']})")
    print("report:", out / "report.html")


if __name__ == "__main__":
    main()
