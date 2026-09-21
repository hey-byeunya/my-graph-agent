#!/usr/bin/env python3
"""5단계 — 홉 수별 채점 + basic RAG 대조 + 실패 층 분류.

  python evaluate.py               # 3회 반복 (불안정한 문항을 드러낸다)
  python evaluate.py --repeat 1    # 빠르게 한 번만
  python evaluate.py --only 3 6    # 특정 문항만

채점은 goldenset.json 의 grading_policy 를 그대로 따른다 (사전 정의).
  정답 1.0 · 부분정답 0.5 · 오답 0
  거절 문항은 '모른다' 고 해야 정답, 지어내면 0

실패 층 분류 — 틀린 건이 어디서 깨졌는가
  색인  기대 삼중항이 그래프에 아예 없다 (추출 단계에서 놓쳤다)
  탐색  그래프엔 있는데 근거 풀에 들어오지 않았다 (반경·허브·상한 문제)
  생성  근거 풀에 있는데 답이 틀렸거나 거절했다 (LLM 문제)

결과 → output/eval.json
"""
import argparse
import json
import os
import statistics
import sys
import time
from collections import defaultdict


HERE = os.path.dirname(os.path.abspath(__file__))
REFUSAL_WORDS = ("찾지 못", "없습니다", "모르", "근거가 없", "확인할 수 없")


def squash(s):
    """공백을 지우고 비교한다.

    basic RAG 가 《파리 대왕》 으로 답했는데 기대 정답이 '파리대왕' 이라 오답이 된 적이
    있다. 띄어쓰기 차이로 대조군을 불리하게 채점하면 비교가 무의미해진다.
    양쪽에 똑같이 적용한다.
    """
    return "".join(str(s).split())


# ──────────────────────────────────────────────────────────── 채점

def score_item(item, answer, refused):
    """goldenset 의 grading_policy 대로 채점한다. (점수, 사유) 반환."""
    if item["hops"] == 0:
        # refused 플래그를 먼저 본다. 문구 매칭은 프롬프트를 고칠 때마다 깨지므로
        # 보조 수단으로만 남긴다 (대조군이 문구로만 거절을 표현하는 경우 대비).
        ok = refused or any(w in answer for w in REFUSAL_WORDS)
        return (1.0, "옳게 거절") if ok else (0.0, "근거 없는데 답을 지어냄")

    if refused or not answer:
        return 0.0, "답하지 못함"

    refs = item["reference"] if isinstance(item["reference"], list) else [item["reference"]]
    flat = squash(answer)
    hit = [r for r in refs if squash(r) in flat]
    if not hit:
        return 0.0, f"기대 정답이 답변에 없음 (기대: {refs[0]})"

    # 복수 정답 문항은 '둘 이상' 이 정답, 하나만이면 부분정답
    if len(refs) > 1 and "둘 이상" in item.get("grading", ""):
        return (1.0, f"{len(hit)}개 맞힘") if len(hit) >= 2 else (0.5, "하나만 맞힘")
    return 1.0, "정답"


def step_matched(step, evidence):
    """기대 경로의 한 걸음이 근거에 있는가 — **양 끝이 다 맞아야** 한다.

    한쪽 끝만 보면 안 된다. '칠레 -~NATIONALITY-> 가브리엘라 미스트랄' 이라는 걸음이
    '네루다 -NATIONALITY-> 칠레' 하나로 충족돼 버리기 때문이다. 그러면 브릿지를
    건너지 못한 실행도 경로를 탔다고 잘못 세게 된다.
    """
    subj, rel, obj = step
    rel = rel.lstrip("~")          # 방향 표시는 채점에서 무시한다 (양방향 탐색이므로)
    A = {p.strip() for p in subj.split("/") if p.strip()} - {"작품"}
    B = {p.strip() for p in obj.split("/") if p.strip()} - {"작품"}
    for e in evidence:
        if e["relation"] != rel:
            continue
        s, o = e["subject"], e["object"]
        # 한쪽이 비어 있으면(예: '작품') 그 끝은 와일드카드
        a_ok = (not A) or s in A or o in A
        b_ok = (not B) or s in B or o in B
        if a_ok and b_ok and (not A or not B or {s, o} & A != {s, o} & B):
            return True
    return False


def path_recall(item, used_evidence):
    """기대 경로의 각 걸음이 실제로 쓴 근거에 들어왔는가."""
    steps = item["expected_path"]
    if not steps:
        return None, []
    detail = [{"step": f"{s} -{r}-> {o}"[:70], "hit": step_matched((s, r, o), used_evidence)}
              for s, r, o in steps]
    return sum(d["hit"] for d in detail) / len(detail), detail


def classify_failure(item, result, G):
    """틀린 건이 색인·탐색·생성 중 어디서 깨졌는지 가린다."""
    steps = item["expected_path"]
    if not steps:
        return "생성"           # 거절 문항에서 틀렸다면 지어낸 것 = 생성

    # ① 색인 — 기대 경로의 개체가 그래프에 있는가
    for subj, _rel, obj in steps:
        if _rel.lstrip("~") == "WON_IN_YEAR":
            # 연도는 노드가 아니라 속성이다 (audit_graph 와 같은 이유)
            if subj not in G or G.nodes[subj].get("nobel_year") is None:
                return "색인"
            continue
        for name in (subj, obj):
            for part in [p.strip() for p in name.split("/")]:
                if part and part != "작품" and part not in G:
                    return "색인"

    # ② 탐색 — 그래프엔 있는데 근거 풀에 들어왔는가
    pool = result.get("pool", [])
    for step in steps:
        if not step_matched(step, pool):
            return "탐색"

    # ③ 생성 — 근거는 다 있었다
    return "생성"


# ──────────────────────────────────────────────────────────── 본체

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--only", type=int, nargs="*")
    ap.add_argument("--no-basic", action="store_true", help="대조군을 건너뛴다")
    ap.add_argument("--max-hops", type=int,
                    help="반경을 바꿔 본다 (반경을 왜 그 값으로 정했는지 재는 용도)")
    ap.add_argument("--no-widen", action="store_true", help="근거가 부족해도 넓히지 않는다")
    ap.add_argument("--tag", default="", help="eval.json 에 남길 조건 이름")
    args = ap.parse_args()

    from agent import GraphAgent
    from rag_basic import BasicRAG

    gs = json.load(open(os.path.join(HERE, "data", "goldenset.json"), encoding="utf-8"))
    items = [i for i in gs["items"] if not args.only or i["id"] in args.only]
    agent = GraphAgent()
    if args.max_hops:
        agent.tv["max_hops"] = args.max_hops
        agent.tv["widen_to_hops"] = args.max_hops if args.no_widen else max(
            args.max_hops, agent.tv["widen_to_hops"])
    if args.no_widen:
        agent.tv["widen_to_hops"] = agent.tv["max_hops"]
    G = agent.G
    basic = None if args.no_basic else BasicRAG()

    print(f"문항 {len(items)}건 × {args.repeat}회"
          + ("" if args.no_basic else " · 대조군 basic RAG(BM25) 동시 실행")
          + f" · 반경 {agent.tv['max_hops']}홉"
          + (f" (넓히면 {agent.tv['widen_to_hops']}홉)"
             if agent.tv["widen_to_hops"] > agent.tv["max_hops"] else " (넓히지 않음)")
          + (f" · 조건 '{args.tag}'" if args.tag else "") + "\n")

    per_item = []
    for it in items:
        qid = it["id"]
        g_scores, b_scores, recalls, layers, samples = [], [], [], [], []
        for run in range(args.repeat):
            r = agent.ask(it["question"], log=False, return_pool=True)
            s, why = score_item(it, r["answer"], r["refused"])
            g_scores.append(s)
            rec, detail = path_recall(it, r["evidence"])
            if rec is not None:
                recalls.append(rec)
            if s < 1.0:
                layers.append(classify_failure(it, r, G))
            samples.append({"run": run + 1, "score": s, "why": why,
                            "answer": r["answer"][:200],
                            "hops_used": r["hops_used"], "widened": r["widened"],
                            "n_evidence": len(r["evidence"]),
                            "path": r["path"][:6],
                            "sources": r["sources"][:6],
                            "path_recall": rec, "path_detail": detail})
            if basic:
                br = basic.ask(it["question"])
                bs = score_item(it, br["answer"], br["refused"])[0]
                b_scores.append(bs)
                samples[-1]["basic"] = {
                    "score": bs, "answer": br["answer"][:200],
                    "retrieved": sorted(set(br["retrieved"])),
                }

        gm = statistics.mean(g_scores)
        bm = statistics.mean(b_scores) if b_scores else None
        stable = len(set(g_scores)) == 1
        rec_m = statistics.mean(recalls) if recalls else None

        mark = "✅" if gm == 1 else ("⚠️ " if gm > 0 else "❌")
        wob = "" if stable else f"  ⟲ 불안정 {g_scores}"
        rec_s = f" · 경로재현 {rec_m:.0%}" if rec_m is not None else ""
        base_s = f" · basic {bm:.2f}" if bm is not None else ""
        print(f"{mark} Q{qid:2d} [{it['hops']}홉] graph {gm:.2f}{base_s}{rec_s}{wob}")
        if gm < 1:
            print(f"      사유: {samples[-1]['why']} · 실패 층: "
                  f"{max(set(layers), key=layers.count) if layers else '-'}")

        # 대조군이 이기고 지는 이유를 설명하는 값:
        # 정답의 근거가 적힌 문서를 BM25 가 몇 개나 물어왔는가.
        # 전부 물어오면 basic RAG 도 푼다 — 멀티홉이라서 지는 게 아니다.
        ev_docs = {e["doc"][:-3].replace("_", " ") for e in it["evidence"]}
        retrieved = set(samples[0].get("basic", {}).get("retrieved", []))
        doc_recall = (len(ev_docs & retrieved) / len(ev_docs)) if ev_docs else None
        per_item.append({
            "id": qid, "hops": it["hops"], "question": it["question"],
            "basic_evidence_doc_recall": doc_recall,
            "graph_score": gm, "basic_score": bm, "path_recall": rec_m,
            "stable": stable, "scores": g_scores,
            "failure_layer": max(set(layers), key=layers.count) if layers else None,
            "runs": samples,
        })

    # ── 홉 수별로 갈라 보고 (평균 하나로 뭉치지 않는다)
    by_hop = defaultdict(list)
    for p in per_item:
        by_hop["거절" if p["hops"] == 0 else f"{p['hops']}홉"].append(p)

    order = ["1홉", "2홉", "3홉", "거절"]
    print("\n" + "=" * 68)
    print(f"{'홉':6s} {'문항':>4s} {'GraphRAG':>9s} {'basic RAG':>10s} {'경로 재현율':>11s}")
    print("-" * 68)
    summary = {}
    for k in order:
        rows = by_hop.get(k)
        if not rows:
            continue
        g = statistics.mean(r["graph_score"] for r in rows)
        b = [r["basic_score"] for r in rows if r["basic_score"] is not None]
        bstr = f"{statistics.mean(b):9.2f}" if b else "        -"
        recs = [r["path_recall"] for r in rows if r["path_recall"] is not None]
        rstr = f"{statistics.mean(recs):10.0%}" if recs else "         -"
        print(f"{k:6s} {len(rows):4d} {g:9.2f} {bstr} {rstr}")
        summary[k] = {"n": len(rows), "graph": round(g, 3),
                      "basic": round(statistics.mean(b), 3) if b else None,
                      "path_recall": round(statistics.mean(recs), 3) if recs else None}
    print("-" * 68)
    gall = statistics.mean(p["graph_score"] for p in per_item)
    ball = [p["basic_score"] for p in per_item if p["basic_score"] is not None]
    print(f"{'전체':6s} {len(per_item):4d} {gall:9.2f} "
          + (f"{statistics.mean(ball):9.2f}" if ball else "        -"))

    # ── 실패 층
    layers = [p["failure_layer"] for p in per_item if p["failure_layer"]]
    print("\n실패 층 분류: "
          + (", ".join(f"{L} {layers.count(L)}건" for L in ("색인", "탐색", "생성")
                       if layers.count(L)) or "실패 없음"))
    unstable = [p["id"] for p in per_item if not p["stable"]]
    if unstable:
        print(f"반복 실행에서 흔들린 문항: {unstable}  "
              f"(같은 입력·temperature 0 인데 결과가 달랐다)")

    out = {
        "evaluated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tag": args.tag,
        "traverse": {"max_hops": agent.tv["max_hops"],
                     "widen_to_hops": agent.tv["widen_to_hops"]},
        "repeat": args.repeat,
        "model": agent.cfg["llm"]["answer_model"],
        "by_hops": summary,
        "overall": {"graph": round(gall, 3),
                    "basic": round(statistics.mean(ball), 3) if ball else None},
        "failure_layers": {L: layers.count(L) for L in ("색인", "탐색", "생성")},
        # 토큰은 화면에만 찍고 버렸는데, 그러면 REPORT 의 비용 수치를 산출물로
        # 뒷받침할 수 없다. 이 실행에서 쓴 분량을 함께 남긴다.
        "tokens": {"graph": {"in": agent.token_in, "out": agent.token_out},
                   "basic": ({"in": basic.token_in, "out": basic.token_out}
                             if basic else None)},
        "unstable_items": unstable,
        "items": per_item,
    }
    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    name = f"eval_{args.tag}.json" if args.tag else "eval.json"
    json.dump(out, open(os.path.join(HERE, "output", name), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(f"\n기록 → output/{name}"
          f"  (토큰: graph in {agent.token_in:,}/out {agent.token_out:,}"
          + (f" · basic in {basic.token_in:,}/out {basic.token_out:,}" if basic else "") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
