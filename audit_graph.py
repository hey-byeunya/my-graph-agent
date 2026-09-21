#!/usr/bin/env python3
"""색인 층 점검 — 평가셋의 기대 경로가 그래프에 실제로 깔려 있는가.

  python audit_graph.py

탐색이나 생성을 탓하기 전에, 삼중항이 애초에 뽑히기는 했는지 본다.
여기서 빠진 것은 나중에 틀려도 '색인 실패' 로 분류된다.

검사
  1. 평가셋에 등장하는 개체가 그래프에 노드로 있는가
  2. 각 문항의 브릿지 노드가 있고, 기대하는 이웃들이 붙어 있는가
  3. 허브 차수 분포 — never_traverse / fanout 상한을 정할 근거
"""
import json
import os
import sys

import networkx as nx

HERE = os.path.dirname(os.path.abspath(__file__))


def load():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    gs = json.load(open(os.path.join(HERE, "data", "goldenset.json"), encoding="utf-8"))
    G = nx.read_graphml(os.path.join(HERE, "output", "graph.graphml"),
                        force_multigraph=True)
    return cfg, gs, G


def main():
    cfg, gs, G = load()
    print(f"그래프: 노드 {G.number_of_nodes():,} · 엣지 {G.number_of_edges():,}\n")

    # ── 1. 허브 분포 (탐색 기준을 정하는 근거)
    deg = sorted(G.degree, key=lambda x: -x[1])
    print("차수 상위 15")
    for n, d in deg[:15]:
        t = G.nodes[n].get("type", "?")
        mark = "  ← 통과 금지" if n in cfg["traverse"]["never_traverse"] else ""
        cap = "  ← fanout 상한 대상" if t in cfg["traverse"]["cap_fanout_node_types"] else ""
        print(f"  {d:4d}  {n:32s} [{t}]{mark}{cap}")
    bridge_types = set(cfg["traverse"]["cap_fanout_node_types"])
    bridge_deg = [d for n, d in G.degree if G.nodes[n].get("type") in bridge_types]
    if bridge_deg:
        bridge_deg.sort(reverse=True)
        print(f"\n다리 노드(언어·국가·갈래·사조) 차수: "
              f"최대 {bridge_deg[0]} · 중앙값 {bridge_deg[len(bridge_deg)//2]} · "
              f"개수 {len(bridge_deg)}")

    # ── 2. 문항별 색인 점검
    print("\n" + "=" * 72)
    print("문항별 색인 점검")
    print("=" * 72)
    missing_total, ok_total = 0, 0
    per_item = []

    for it in gs["items"]:
        qid, hops = it["id"], it["hops"]
        if hops == 0:
            print(f"\nQ{qid} [거절] {it['question'][:50]}")
            # 거절 문항은 오히려 '없어야' 한다
            names = ["무라카미 하루키"] if qid == 11 else ["한강", "윌리엄 포크너"]
            present = [n for n in names if n in G]
            print(f"  그래프에 있는 개체: {present or '없음'}  "
                  f"(있어도 둘을 잇는 근거가 없어야 정상)")
            per_item.append({"id": qid, "hops": 0, "status": "N/A"})
            continue

        print(f"\nQ{qid} [{hops}홉] {it['question'][:50]}")
        gaps = []

        # 기대 경로에 등장하는 개체가 노드로 있는가
        for step in it["expected_path"]:
            subj, rel, obj = step
            for name in (subj, obj):
                for part in [p.strip() for p in name.split("/")]:
                    if part in ("작품",) or not part:
                        continue
                    if part not in G:
                        gaps.append(f"노드 없음: {part}")

        # 브릿지에 기대 이웃이 붙어 있는가
        bridge = it.get("bridge")
        if bridge:
            if bridge not in G:
                gaps.append(f"브릿지 노드 없음: {bridge}")
            else:
                d = G.degree(bridge)
                refs = it["reference"] if isinstance(it["reference"], list) else [it["reference"]]
                inbound = {u for u, _, _ in G.in_edges(bridge, keys=True)}
                # 기대 정답은 브릿지에서 (hops-1) 걸음 안에 있어야 한다.
                # 2홉 문항이면 브릿지의 직접 이웃, 3홉이면 그 이웃의 이웃까지.
                reach = nx.single_source_shortest_path_length(
                    G.to_undirected(as_view=True), bridge, cutoff=hops - 1)
                found = [r for r in refs if r in reach]
                lost = [r for r in refs if r not in reach]
                print(f"  브릿지 '{bridge}' 차수 {d} · 직접 이웃 {len(inbound)}개 "
                      f"· {hops - 1}걸음 이내 {len(reach)}개")
                print(f"  기대 정답 중 닿는 것: {found or '없음'}")
                if not found:
                    gaps.append(f"브릿지에서 {hops - 1}걸음 안에 정답이 없음: "
                                f"{', '.join(lost[:5])}")
                elif lost:
                    print(f"  (못 닿는 것: {', '.join(lost[:5])})")

        if gaps:
            missing_total += 1
            for g in gaps:
                print(f"  ❌ {g}")
        else:
            ok_total += 1
            print("  ✅ 색인 이상 없음")
        per_item.append({"id": qid, "hops": hops,
                         "status": "OK" if not gaps else "MISSING", "gaps": gaps})

    print("\n" + "=" * 72)
    n_scored = sum(1 for p in per_item if p["status"] != "N/A")
    print(f"색인 통과 {ok_total}/{n_scored}  ·  결손 {missing_total}건")
    json.dump(per_item, open(os.path.join(HERE, "output", "index_audit.json"), "w",
                             encoding="utf-8"), ensure_ascii=False, indent=2)
    print("기록 → output/index_audit.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
