#!/usr/bin/env python3
"""평가셋 자체검사 — 근거가 정말 원문에 있는지 대조한다.

  python verify_goldenset.py

검사 항목
  1. evidence 의 quote 가 해당 원문 파일에 글자 그대로 있는가
  2. evidence 가 가리키는 문서가 실제로 존재하는가
  3. 멀티홉 문항의 근거가 문서 2건 이상에 걸쳐 있는가
     (한 문서로 답이 나오면 멀티홉을 증명하지 못한다)
  4. 거절 문항(hops=0)의 핵심어가 코퍼스에 정말 없는가
  5. 홉 수 분포가 stats 와 맞는가

이 검사를 통과해야 평가셋을 믿고 채점할 수 있다.
"""
import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "data", "docs")


def main():
    gs = json.load(open(os.path.join(HERE, "data", "goldenset.json"), encoding="utf-8"))
    items = gs["items"]
    errors, warnings = [], []

    for it in items:
        qid, hops = it["id"], it["hops"]
        docs_cited = set()

        for ev in it["evidence"]:
            path = os.path.join(DOCS, ev["doc"])
            if not os.path.exists(path):
                errors.append(f"Q{qid}: 문서 없음 — {ev['doc']}")
                continue
            docs_cited.add(ev["doc"])
            text = open(path, encoding="utf-8").read()
            if ev["quote"] not in text:
                errors.append(
                    f"Q{qid}: 근거가 원문에 없음 — {ev['doc']}\n"
                    f"      찾은 문장: {ev['quote'][:70]}…"
                )

        # 멀티홉인데 근거가 한 문서뿐이면 멀티홉을 증명하지 못한다
        if hops >= 2 and len(docs_cited) < 2:
            errors.append(
                f"Q{qid}: {hops}홉 문항인데 근거가 {len(docs_cited)}개 문서뿐 "
                f"— 한 문서로 답이 나오면 멀티홉이 아니다"
            )
        if hops == 0 and it["evidence"]:
            errors.append(f"Q{qid}: 거절 문항인데 근거가 붙어 있다")
        if hops > 0 and not it["evidence"]:
            errors.append(f"Q{qid}: 근거가 비어 있다")
        if hops > 0 and len(it["expected_path"]) != hops:
            errors.append(
                f"Q{qid}: hops={hops} 인데 expected_path 간선이 "
                f"{len(it['expected_path'])}개다"
            )

    # 거절 문항의 핵심어가 코퍼스에 정말 없는지
    corpus = {
        f: open(os.path.join(DOCS, f), encoding="utf-8").read()
        for f in os.listdir(DOCS) if f.endswith(".md")
    }
    hits = [f for f, t in corpus.items() if "무라카미" in t]
    if hits:
        errors.append(f"Q11: '무라카미' 가 코퍼스에 있다 — {hits}")
    both = [f for f, t in corpus.items() if "한강" in t and "포크너" in t]
    if both:
        errors.append(f"Q12: 한강과 포크너가 같은 문서에 있다 — {both}")
    # Q14 는 '연도는 알아듣지만 그 해 수상자가 없다' 를 시험한다.
    # 코퍼스에 1994년 수상자가 들어오면 문항이 무의미해지므로 감시한다.
    try:
        import networkx as nx
        G = nx.read_graphml(os.path.join(HERE, "output", "graph.graphml"),
                            force_multigraph=True)
        y94 = [n for n, d in G.nodes(data=True) if d.get("nobel_year") == 1994]
        if y94:
            errors.append(f"Q14: 1994년 수상자가 그래프에 생겼다 — {y94}. 문항을 바꿔야 한다")
    except FileNotFoundError:
        warnings.append("graph.graphml 이 없어 Q14 전제는 확인하지 못했다")

    # 홉 분포
    dist = Counter(str(i["hops"]) if i["hops"] else "거절" for i in items)
    declared = gs["stats"]["by_hops"]
    if dict(dist) != declared:
        warnings.append(f"홉 분포가 stats 와 다름: 실제 {dict(dist)} / 선언 {declared}")
    if gs["stats"]["n_questions"] != len(items):
        warnings.append(f"문항 수 불일치: 실제 {len(items)} / 선언 {gs['stats']['n_questions']}")

    # 출력
    n_ev = sum(len(i["evidence"]) for i in items)
    n_docs = len({e["doc"] for i in items for e in i["evidence"]})
    print(f"문항 {len(items)}건 · 근거 {n_ev}개 · 인용 문서 {n_docs}건")
    print(f"홉 분포: {dict(dist)}")
    print(f"코퍼스: {len(corpus)}건\n")

    for w in warnings:
        print(f"⚠️  {w}")
    for e in errors:
        print(f"❌ {e}")

    if errors:
        print(f"\n실패 {len(errors)}건 — 평가셋을 고쳐야 합니다.")
        return 1
    print("✅ 모든 근거가 원문과 일치합니다."
          + ("" if not warnings else f" (경고 {len(warnings)}건)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
