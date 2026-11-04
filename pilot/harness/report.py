"""report.json → 한 장짜리 HTML 리포트."""
from html import escape


def _f(v, d=2):
    return "—" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))


def _bar(v, good=0.7):
    if v is None:
        return ""
    w = max(0, min(1, v)) * 100
    c = "#2da44e" if v >= good else ("#d29922" if v >= good - 0.2 else "#cf222e")
    return f'<span class="bar"><i style="width:{w:.0f}%;background:{c}"></i></span>'


def render(r: dict) -> str:
    gates = "".join(
        f'<tr class="{"ok" if g["pass"] else "ng"}"><td>{g["id"]}</td><td>{escape(g["name"])}</td>'
        f'<td class="n">{_f(g["value"], 3)}</td><td class="n">{g["op"]} {g["threshold"]}</td>'
        f'<td><b>{"통과" if g["pass"] else "미달"}</b></td></tr>' for g in r["gates"])
    names = {"fixed|fixed": "정형 문장", "paraphrase|dev": "변형 (dev)", "paraphrase|holdout": "변형 (holdout)",
             "free|dev": "자유 발화 (dev)", "free|holdout": "자유 발화 (holdout)"}
    qrows = ""
    for key, label in names.items():
        cells = ""
        for prof in ("clean", "realistic", "noisy"):
            q = r["quality"].get(f"{prof}|{key}")
            cells += (f'<td class="n">{_f(q["exact"])}</td><td class="n">{_f(q["order_f1"])} {_bar(q["order_f1"])}</td>'
                      if q else "<td>—</td><td>—</td>")
        qrows += f"<tr><td>{label}</td>{cells}</tr>"
    dom_names = {"protestant": "기독교", "catholic": "천주교", "buddhist": "불교"}
    drows = ""
    for d, dn in dom_names.items():
        if not r["by_domain"].get(f"{d}|fixed", {}).get("n"):
            continue                                    # 비활성 상황은 표에서 뺀다
        drows += "<tr><td>" + dn + "</td>" + "".join(
            f'<td class="n">{_f(r["by_domain"][f"{d}|{c}"]["order_f1"])} {_bar(r["by_domain"][f"{d}|{c}"]["order_f1"])}</td>'
            for c in ("fixed", "paraphrase", "free")) + "</tr>"
    cer_real = r["quality"].get("realistic|fixed|fixed", {}).get("cer")
    cer_noisy = r["quality"].get("noisy|fixed|fixed", {}).get("cer")
    L, C, A = r["latency"], r["coverage"], r["agent"]
    worst = "".join(
        f'<tr><td>{escape(x["category"])}/{escape(x["split"])}</td><td>{escape(x["text"])}<br><small>STT: {escape(x["stt_final"])}</small></td>'
        f'<td>{escape(x["gold"])}</td><td>{escape(x["pred"])}</td><td class="n">{_f(x["order_f1"])}</td></tr>'
        for x in r["examples_worst"])
    ff = "".join(f'<tr><td>{escape(x["text"])}<br><small>STT: {escape(x["stt_final"])}</small></td>'
                 f'<td>{escape(x["gold"])}</td><td>{escape(x["pred"])}</td></tr>' for x in r["fixed_failures"]) \
        or '<tr><td colspan="3">없음</td></tr>'
    passed = sum(g["pass"] for g in r["gates"])
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SyncSL 시범 서비스 하네스 검증 리포트</title><style>
body{{font-family:-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;max-width:1080px;margin:24px auto;padding:0 16px;color:#1f2328}}
h1{{font-size:22px}}h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #d0d7de;padding-bottom:4px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{border-bottom:1px solid #eaeef2;padding:6px 8px;text-align:left;vertical-align:top}}
th{{background:#f6f8fa}}td.n{{text-align:right;white-space:nowrap}}tr.ok td:last-child{{color:#1a7f37}}tr.ng td:last-child{{color:#cf222e}}tr.ng{{background:#fff5f5}}
.bar{{display:inline-block;width:70px;height:8px;background:#eaeef2;border-radius:4px;vertical-align:middle;margin-left:6px}}.bar i{{display:block;height:100%;border-radius:4px}}
.kpi{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.kpi div{{background:#f6f8fa;border-radius:10px;padding:10px}}.kpi b{{display:block;font-size:22px}}
small{{color:#656d76}}.note{{background:#fff8c5;padding:10px 12px;border-radius:8px;font-size:14px}}</style></head><body>
<h1>SyncSL 종교시설 시범 서비스 — 하네스 검증 리포트</h1>
<p><small>{r["generated"]} · 실행 {r["counts"]["runs"]}회 · 발화 {r["counts"]["utterances"]}건 · 문장 은행 {r["counts"]["phrasebank"]}문장 · gloss 어휘 {r["counts"]["lexicon_glosses"]}개 · 클립 등록 {r["counts"]["clips_registered"]}개</small></p>
<p class="note">게이트 {passed}/{len(r["gates"])} 통과. gold gloss는 개발자 초안이라 <b>농인 수어 전문가 검수 전 수치</b>입니다. STT는 시뮬레이터(오류율 realistic CER≈{_f(cer_real,3)}, noisy CER≈{_f(cer_noisy,3)})이므로 실제 현장 STT 지연·오류는 시범 운영에서 다시 재야 합니다.</p>
<div class="kpi"><div>수어 종단 지연 p50<b>{_f(L["e2e_sign_p50_s"])}초</b></div><div>수어 종단 지연 p95<b>{_f(L["e2e_sign_p95_s"])}초</b></div>
<div>서버 처리 p95<b>{_f(L["processing_p95_ms"],1)}ms</b></div><div>30대 전달 p95<b>{_f(L["load30_deliver_p95_ms"],1)}ms</b></div></div>
<h2>게이트 판정</h2><table><tr><th>ID</th><th>항목</th><th>측정값</th><th>기준</th><th>판정</th></tr>{gates}</table>
<h2>gloss 품질 (STT 프로필별)</h2><table><tr><th>문장 유형</th><th>clean 정확</th><th>clean 순서F1</th><th>realistic 정확</th><th>realistic 순서F1</th><th>noisy 정확</th><th>noisy 순서F1</th></tr>{qrows}</table>
<h2>종교별 순서 F1 (realistic, 정형+holdout)</h2><table><tr><th>상황</th><th>정형</th><th>변형</th><th>자유 발화</th></tr>{drows}</table>
<h2>표출 방식 · 재생</h2><table>
<tr><td>정형 문장 gloss 중 실사 클립</td><td class="n">{_f(C["fixed_clip"])}</td></tr>
<tr><td>전체 gloss 중 실사 클립 / 지문자 / 글자 카드</td><td class="n">{_f(C["all_clip"])} / {_f(C["all_fingerspell"])} / {_f(C["all_card"])}</td></tr>
<tr><td>수어 재생 길이 ÷ 말한 시간 (평균)</td><td class="n">{_f(L["sign_vs_speech_ratio"])}</td></tr>
<tr><td>재생 밀림 p95</td><td class="n">{_f(L["playback_lag_p95_s"])}초</td></tr>
<tr><td>방별 1.25배속·건너뜀 횟수</td><td>{escape(str(r["playback"]))}</td></tr></table>
<h2>AI Agent 장애 주입 (지연 0.2~2.5초, 엉터리 출력 25%)</h2><table>
<tr><td>호출 / 채택 / 거부 / 시간초과</td><td class="n">{A["calls"]} / {A["accepted"]} / {A["rejected"]} / {A["timeouts"]}</td></tr>
<tr><td>그동안 자막 전달 p95 / 수어 전달 p95</td><td class="n">{_f(L["agent_caption_deliver_p95_ms"],1)}ms / {_f(L["agent_sign_deliver_p95_ms"],1)}ms</td></tr>
<tr><td>어휘 밖 gloss 방송 유출</td><td class="n">{len(A["leaked_tokens"])}건</td></tr></table>
<h2>정형 문장 실패 (realistic)</h2><table><tr><th>문장 / STT</th><th>gold</th><th>예측</th></tr>{ff}</table>
<h2>가장 낮은 점수 12건 (realistic, 변형·자유)</h2><table><tr><th>유형</th><th>문장 / STT</th><th>gold</th><th>예측</th><th>F1</th></tr>{worst}</table>
</body></html>"""
