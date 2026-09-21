#!/usr/bin/env python3
"""채점기가 잘못 센 문항을 사람이 고쳐 적는 자리.

`evaluate.py` 의 채점은 **정답 문자열이 답에 들어 있는가**만 본다. 그 규칙이
틀리게 세는 문항이 하나 있어(Q3 — 4절), 기준을 `goldenset.json` 의
`manual_regrade` 에 적어 두고 여기서 성적표에 반영한다.

한 곳에서만 계산해 `evaluate.py`(성적표 기록)와 `app.py`(데모 화면)가 같은
숫자를 쓴다. 원점수는 지우지 않는다 — `eval.json` 의 `by_hops`·`overall` 은
채점기가 낸 그대로 두고, 보정치는 `regraded` 에 따로 담는다.
"""
import statistics


def regrade(evaluation, goldenset):
    """원점수 성적표에 manual_regrade 를 얹은 {by_hops, overall, items} 를 만든다.

    고칠 문항이 없으면 None 을 돌려준다 — 부를 쪽에서 원점수를 그대로 쓰면 된다.
    """
    rules = {r["id"]: r for r in goldenset.get("manual_regrade", [])}
    if not rules:
        return None

    items = []
    for it in evaluation["items"]:
        rule = rules.get(it["id"])
        items.append({**it, "graph_score": rule["score"], "regraded": True,
                      "raw_graph_score": it["graph_score"], "regrade_why": rule["why"]}
                     if rule else it)

    by_hops = {}
    for key, group in _by_hops(items).items():
        graphs = [i["graph_score"] for i in group]
        basics = [i["basic_score"] for i in group if i["basic_score"] is not None]
        recalls = [i["path_recall"] for i in group if i["path_recall"] is not None]
        by_hops[key] = {
            "n": len(group),
            "graph": round(statistics.mean(graphs), 3),
            "basic": round(statistics.mean(basics), 3) if basics else None,
            "path_recall": round(statistics.mean(recalls), 3) if recalls else None,
        }

    basics = [i["basic_score"] for i in items if i["basic_score"] is not None]
    return {
        "applied": sorted(rules),
        "by_hops": by_hops,
        "overall": {"graph": round(statistics.mean(i["graph_score"] for i in items), 3),
                    "basic": round(statistics.mean(basics), 3) if basics else None},
        "items": items,
    }


ORDER = ["1홉", "2홉", "3홉", "거절"]


def _by_hops(items):
    """원점수 성적표와 같은 칸 이름·같은 순서를 쓴다(evaluate.py 의 order)."""
    groups = {}
    for it in items:
        key = f"{it['hops']}홉" if it["hops"] else "거절"
        groups.setdefault(key, []).append(it)
    return {k: groups[k] for k in ORDER if k in groups}
