#!/usr/bin/env python3
"""3단계 — ① 스키마로 제한한 추출 + ② 정제·병합.

  python build_graph.py               # 전체 60건
  python build_graph.py --limit 5     # 적은 문서로 빠르게 확인
  python build_graph.py --no-cache    # 캐시 무시하고 다시 추출

단계
  1. 로드      data/docs/*.md
  2. 추출      config.json 의 관계 7종으로 제한해 LLM 이 삼중항을 뽑는다
               (문서별 결과를 .cache/extract/ 에 남겨 재실행이 공짜가 되게 한다)
  3. 정규화    별칭 치환 -> 불용 노드 제거 -> 스키마 위반 제거 -> fuzzy 병합
               never_merge 쌍은 fuzzy 병합에서 제외한다
  4. 저장      output/graph.graphml · output/triples.json · output/build_report.json

정규화 전후 건수를 찍는다 — 무엇이 합쳐지고 무엇이 버려졌는지가 REPORT 2절의 재료다.
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

import networkx as nx
from dotenv import load_dotenv
from rapidfuzz import fuzz

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache", "extract")
load_dotenv(os.path.join(HERE, ".env"))


# ──────────────────────────────────────────────────────────── 추출

def build_prompt(cfg):
    """스키마를 프롬프트에 박아 넣는다. 스키마 밖의 것은 뽑지 말라고 못 박는다."""
    rels = "\n".join(
        f"  - {r['name']}: {r['from']} → {r['to']}  ({r['desc']})"
        for r in cfg["schema"]["relations"]
    )
    types = " · ".join(cfg["schema"]["node_types"])
    return f"""너는 한국어 위키백과 문서에서 지식 그래프의 삼중항을 뽑는 도구다.

노드 타입은 이것뿐이다: {types}

관계는 이것뿐이다:
{rels}

규칙
- 문서에 **명시적으로 쓰여 있는 것만** 뽑는다. 추론하거나 상식으로 채우지 않는다.
- 위 목록에 없는 관계는 만들지 않는다. 애매하면 뽑지 않는다.
- 개체 이름은 문서에 나온 표기를 그대로 쓴다. 《》 같은 괄호는 벗긴다.
- '작가' '소설' '문학' 같은 일반명사는 노드로 만들지 않는다.
- **이 문서의 주인공을 가리킬 때는 반드시 아래에 주어지는 '표준 표기' 를 쓴다.**
  본문에 전체 이름(예: '비디아다르 수라지프라사드 나이폴')이 나와도 표준 표기('V. S. 나이폴')로 적는다.
- 주인공이 아닌 다른 사람은 본문에 나온 대로, 가장 완전한 형태로 쓴다.
- 국적은 나라 이름으로 쓴다 (예: '칠레의 시인' → NATIONALITY → '칠레').
- 상 이름은 문서에 적힌 그대로 쓴다. 표기를 임의로 통일하지 않는다 (통일은 뒷단계가 한다).

출력은 JSON 하나. 다른 말은 쓰지 않는다:
{{"triples": [{{"subject": "...", "relation": "...", "object": "...", "evidence": "근거가 된 원문 문장"}}]}}"""


def canonical_title(title):
    """'한강 (작가)' → '한강'. 위키 제목의 동음이의 주석을 벗겨 표준 표기로 삼는다."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()


def extract_doc(client, model, prompt, title, text, max_chars=12000):
    body = text[:max_chars]
    canon = canonical_title(title)
    resp = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user",
             "content": f"문서 제목: {title}\n이 문서 주인공의 표준 표기: {canon}\n\n{body}"},
        ],
    )
    data = json.loads(resp.choices[0].message.content)
    usage = resp.usage
    return data.get("triples", []), (usage.prompt_tokens, usage.completion_tokens)


def extract_all(cfg, docs, use_cache=True):
    from openai import OpenAI

    client = OpenAI()
    model = cfg["llm"]["extract_model"]
    prompt = build_prompt(cfg)
    os.makedirs(CACHE, exist_ok=True)
    pkey = hashlib.sha1(prompt.encode()).hexdigest()[:8]

    raw, tok_in, tok_out, n_cached = [], 0, 0, 0
    for i, (title, text) in enumerate(docs, 1):
        key = hashlib.sha1(f"{pkey}|{model}|{title}|{len(text)}".encode()).hexdigest()[:16]
        cpath = os.path.join(CACHE, f"{key}.json")
        if use_cache and os.path.exists(cpath):
            triples = json.load(open(cpath, encoding="utf-8"))
            n_cached += 1
        else:
            for attempt in range(3):
                try:
                    triples, (ti, to) = extract_doc(client, model, prompt, title, text)
                    tok_in += ti
                    tok_out += to
                    break
                except Exception as e:
                    if attempt == 2:
                        print(f"\n  ✗ {title}: {type(e).__name__}: {e}")
                        triples = []
                        break
                    time.sleep(2 ** attempt)
            json.dump(triples, open(cpath, "w", encoding="utf-8"), ensure_ascii=False)
        for t in triples:
            t["doc"] = title
        raw.extend(triples)
        print(f"\r  추출 {i}/{len(docs)}  (캐시 {n_cached})  누적 삼중항 {len(raw):,}",
              end="", flush=True)
    print()
    return raw, tok_in, tok_out


# ──────────────────────────────────────────────────────────── 정규화

def clean_name(s):
    s = re.sub(r"[《》〈〉<>「」『』\"']", "", str(s)).strip()
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,.·")


def normalize(raw, cfg):
    """별칭 치환 → 불용 노드 제거 → 스키마 위반 제거 → fuzzy 병합.

    각 단계에서 무엇이 몇 건 사라졌는지 세어 돌려준다.
    """
    nrm = cfg["normalize"]
    alias = nrm["alias_map"]
    stop = set(nrm["stopword_nodes"])
    allowed_rel = {r["name"] for r in cfg["schema"]["relations"]}
    never = [set(p) for p in nrm.get("never_merge", [])]
    dropped = Counter()

    # 1) 이름 정리 + 별칭 치환
    step1 = []
    for t in raw:
        s, r, o = (clean_name(t.get("subject")), str(t.get("relation", "")).strip(),
                   clean_name(t.get("object")))
        if not s or not o:
            dropped["빈 값"] += 1
            continue
        s, o = alias.get(s, s), alias.get(o, o)
        if s == o:
            dropped["자기 자신을 가리킴"] += 1
            continue
        step1.append({**t, "subject": s, "relation": r, "object": o})

    # 2) 스키마 밖 관계 제거
    step2 = []
    for t in step1:
        if t["relation"] not in allowed_rel:
            dropped[f"스키마 밖 관계({t['relation']})"] += 1
            continue
        step2.append(t)

    # 3) 일반명사 노드 제거
    step3 = []
    for t in step2:
        if t["subject"] in stop or t["object"] in stop:
            dropped["일반명사 노드"] += 1
            continue
        if len(t["subject"]) < 2 or len(t["object"]) < 2:
            dropped["한 글자 노드"] += 1
            continue
        step3.append(t)

    # 3.5) 문서 제목으로 끌어오기 — 프롬프트가 표준 표기를 놓친 경우의 안전망.
    #      각 문서는 한 인물에 대한 것이고, 그 문서 제목이 그 인물의 표준 표기다.
    #      같은 문서에서 나온 이름이 제목과 성씨를 공유하면 제목 표기로 통일한다.
    title_pulls = []
    for t in step3:
        doc = t.get("doc")
        if not doc:
            continue
        canon_doc = canonical_title(doc)
        for field in ("subject", "object"):
            name = t[field]
            if name == canon_doc or len(name) < 3:
                continue
            # 성씨(마지막 어절)를 공유하고, 한쪽이 다른 쪽보다 길면 같은 사람으로 본다
            a, b = name.split(), canon_doc.split()
            if a and b and a[-1] == b[-1] and fuzz.partial_ratio(name, canon_doc) >= 60:
                title_pulls.append((name, canon_doc))
                t[field] = canon_doc
    dropped_pulls = Counter(f"{a} → {b}" for a, b in title_pulls)

    # 4) fuzzy 병합 — 표기가 흔들린 같은 개체를 하나로.
    #    등장 횟수가 많은 표기를 대표로 삼는다. never_merge 쌍은 건드리지 않는다.
    freq = Counter()
    for t in step3:
        freq[t["subject"]] += 1
        freq[t["object"]] += 1
    names = [n for n, _ in freq.most_common()]
    canon, merges = {}, []
    thr = nrm["fuzzy_threshold"]
    for name in names:
        best, best_score = None, 0
        for rep in dict.fromkeys(canon.values()):
            if any({name, rep} == p for p in never):
                continue
            score = fuzz.ratio(name, rep)
            if score > best_score:
                best, best_score = rep, score
        if best and best_score >= thr:
            canon[name] = best
            merges.append((name, best, best_score))
        else:
            canon[name] = name

    final = []
    for t in step3:
        final.append({
            **t,
            "subject": canon.get(t["subject"], t["subject"]),
            "object": canon.get(t["object"], t["object"]),
        })

    # 5) 중복 삼중항 합치기 (근거 문서는 모아 둔다)
    bucket = defaultdict(lambda: {"docs": [], "evidence": []})
    for t in final:
        k = (t["subject"], t["relation"], t["object"])
        b = bucket[k]
        if t.get("doc") and t["doc"] not in b["docs"]:
            b["docs"].append(t["doc"])
        ev = (t.get("evidence") or "").strip()
        if ev and ev not in b["evidence"]:
            b["evidence"].append(ev)
    deduped = [
        {"subject": s, "relation": r, "object": o, "docs": v["docs"],
         "evidence": v["evidence"][:3]}
        for (s, r, o), v in bucket.items()
    ]

    stats = {
        "raw": len(raw),
        "after_alias": len(step1),
        "after_schema_filter": len(step2),
        "after_stopword_filter": len(step3),
        "after_dedup": len(deduped),
        "dropped": dict(dropped),
        "title_pulls": dict(dropped_pulls),
        "fuzzy_merges": [{"from": a, "to": b, "score": s} for a, b, s in merges],
    }
    return deduped, stats


# ──────────────────────────────────────────────────────────── 그래프

def to_graph(triples, cfg):
    G = nx.MultiDiGraph()
    # 노드 타입은 관계가 정한다 — AUTHORED 의 주어는 Laureate, 목적어는 Work.
    # triples 는 스키마 필터를 이미 통과했으므로 여기서 못 찾는 관계는 없다.
    rel_to = {r["name"]: (r["from"], r["to"]) for r in cfg["schema"]["relations"]}
    for t in triples:
        st, ot = rel_to[t["relation"]]
        for name, typ in ((t["subject"], st), (t["object"], ot)):
            if name not in G:
                G.add_node(name, type=typ)
        G.add_edge(t["subject"], t["object"], key=t["relation"], relation=t["relation"],
                   docs="|".join(t["docs"]), evidence=" ⏐ ".join(t["evidence"])[:900])
    return G


def main():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    ddir = os.path.join(HERE, cfg["corpus"]["dir"])
    files = sorted(f for f in os.listdir(ddir) if f.endswith(".md"))
    if args.limit:
        files = files[: args.limit]
    docs = []
    for f in files:
        text = open(os.path.join(ddir, f), encoding="utf-8").read()
        docs.append((f[:-3].replace("_", " "), text))
    print(f"문서 {len(docs)}건 · 모델 {cfg['llm']['extract_model']}\n")

    raw, ti, to = extract_all(cfg, docs, use_cache=not args.no_cache)
    print(f"\n원시 삼중항 {len(raw):,}건  (토큰 in {ti:,} / out {to:,})")

    triples, stats = normalize(raw, cfg)
    print("\n정규화")
    print(f"  원시                 {stats['raw']:,}")
    print(f"  별칭 치환 후         {stats['after_alias']:,}")
    print(f"  스키마 필터 후       {stats['after_schema_filter']:,}")
    print(f"  일반명사 제거 후     {stats['after_stopword_filter']:,}")
    print(f"  중복 합친 후         {stats['after_dedup']:,}")
    if stats["dropped"]:
        print("  버린 사유:")
        for k, v in sorted(stats["dropped"].items(), key=lambda x: -x[1]):
            print(f"    {v:5,}  {k}")
    if stats["title_pulls"]:
        print(f"  문서 제목으로 통일 {len(stats['title_pulls'])}종:")
        for k, v in list(stats["title_pulls"].items())[:10]:
            print(f"    {k}  ({v}건)")
    if stats["fuzzy_merges"]:
        print(f"  표기 병합 {len(stats['fuzzy_merges'])}건 (상위 10):")
        for m in stats["fuzzy_merges"][:10]:
            print(f"    {m['from']}  →  {m['to']}  ({m['score']:.0f})")

    G = to_graph(triples, cfg)
    out = os.path.join(HERE, "output")
    os.makedirs(out, exist_ok=True)
    nx.write_graphml(G, os.path.join(out, "graph.graphml"))
    json.dump(triples, open(os.path.join(out, "triples.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    deg = sorted(G.degree, key=lambda x: -x[1])
    by_type = Counter(d.get("type", "?") for _, d in G.nodes(data=True))
    by_rel = Counter(d["relation"] for _, _, d in G.edges(data=True))

    print(f"\n그래프: 노드 {G.number_of_nodes():,} · 엣지 {G.number_of_edges():,}")
    print(f"  노드 타입: {dict(by_type)}")
    print(f"  관계별:    {dict(by_rel)}")
    print("  차수 상위 12 (허브 후보):")
    for n, d in deg[:12]:
        print(f"    {d:4d}  {n}  [{G.nodes[n].get('type')}]")

    report = {
        "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "n_docs": len(docs),
        "model": cfg["llm"]["extract_model"],
        "tokens": {"in": ti, "out": to},
        "normalize": stats,
        "graph": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
            "by_node_type": dict(by_type),
            "by_relation": dict(by_rel),
            "top_degree": [{"node": n, "degree": d,
                            "type": G.nodes[n].get("type")} for n, d in deg[:25]],
        },
    }
    json.dump(report, open(os.path.join(out, "build_report.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n저장 → output/graph.graphml · triples.json · build_report.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
