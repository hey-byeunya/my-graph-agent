#!/usr/bin/env python3
"""4단계 — 시작 개체 찾기 → n홉 확장 → 근거만으로 답변 (LangGraph).

  python agent.py "한강이 받은 국제 부커상을 받은 다른 수상자는?"
  python agent.py                 # 대화형
  python agent.py --json "..."    # 결과를 JSON 으로

State 흐름
  find_seed → expand → answer → (근거 부족이면) widen → expand → answer → …
  widen 을 widen_to_hops 까지 써도 부족하면 거절한다.

기록
  실행마다 output/runs.jsonl 에 질문·경로·근거·답변을 한 줄씩 append 한다.
"""
import argparse
import json
import os
import re
import sys
import time
from collections import deque
from typing import Annotated, TypedDict

import networkx as nx
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(HERE, ".env"))


# ──────────────────────────────────────────────────────────── State

class AgentState(TypedDict, total=False):
    question: str
    hops: int              # 지금 몇 홉까지 펼쳤는가
    seeds: list            # 질문에서 찾은 시작 개체
    evidence: list         # [{subject, relation, object, docs, evidence}]
    path: list             # 실제로 탄 경로 ["한강 -WON-> 국제 부커상", …]
    visited: list
    answer: str
    sufficient: bool
    refused: bool
    notes: list            # 사람이 읽을 진행 기록
    widened: int


# ──────────────────────────────────────────────────────────── 에이전트

class GraphAgent:
    def __init__(self, cfg=None, graph=None, quiet=True):
        self.cfg = cfg or json.load(
            open(os.path.join(HERE, "config.json"), encoding="utf-8"))
        self.G = graph if graph is not None else nx.read_graphml(
            os.path.join(HERE, "output", "graph.graphml"), force_multigraph=True)
        self.tv = self.cfg["traverse"]
        self.never = set(self.tv["never_traverse"])
        self.cap_types = set(self.tv["cap_fanout_node_types"])
        self.alias = self.cfg["normalize"]["alias_map"]
        self.quiet = quiet
        self._client = None
        self.token_in = self.token_out = 0
        # 긴 이름부터 맞춰야 '한강' 보다 '한강 (작가)' 류가 먼저 잡힌다
        self.node_names = sorted(self.G.nodes, key=len, reverse=True)
        self.app = self._build()

    # ── LLM
    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI()
        return self._client

    def _chat(self, system, user):
        r = self.client.chat.completions.create(
            model=self.cfg["llm"]["answer_model"],
            temperature=self.cfg["llm"]["temperature"],
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        self.token_in += r.usage.prompt_tokens
        self.token_out += r.usage.completion_tokens
        return json.loads(r.choices[0].message.content)

    # ── 노드 1: 시작 개체 찾기
    def find_seed(self, state: AgentState) -> AgentState:
        q = state["question"]
        # 질문에도 별칭 치환을 먹인다 — '맨부커상' 으로 물어도 '부커상' 노드를 찾게
        for a, b in self.alias.items():
            q = q.replace(a, b)

        seeds, taken = [], []
        for name in self.node_names:
            if len(name) < 2 or name in self.never:
                continue                      # 허브는 시작점으로도 쓰지 않는다
            if name not in q:
                continue
            if any(name in t for t in taken):  # 이미 잡은 더 긴 이름의 일부면 건너뛴다
                continue
            seeds.append(name)
            taken.append(name)
            if len(seeds) >= 4:
                break

        notes = [f"질문에서 찾은 시작 개체: {seeds or '없음'}"]
        if not seeds:
            notes.append("시작 개체가 없다 — 그래프에 없는 것을 묻고 있다")
        return {**state, "seeds": seeds, "hops": self.tv["max_hops"],
                "widened": 0, "notes": notes}

    # ── 노드 2: n홉 확장
    def expand(self, state: AgentState) -> AgentState:
        seeds, budget = state["seeds"], state["hops"]
        if not seeds:
            return {**state, "evidence": [], "path": [], "visited": []}

        evidence, path, visited = [], [], set(seeds)
        seen_edges = set()
        seed_set = set(seeds)
        frontier = deque((s, 0) for s in seeds)
        HARD_CAP = 600          # 폭주 방지. 선별은 아래에서 따로 한다

        while frontier:
            node, depth = frontier.popleft()
            if depth >= budget:
                continue
            # 이웃을 모은다 (양방향 — 역방향 탐색이 있어야 '같은 상을 받은 다른 사람' 이 풀린다)
            nbrs = []
            for u, v, k in self.G.out_edges(node, keys=True):
                nbrs.append((v, k, u, v))
            for u, v, k in self.G.in_edges(node, keys=True):
                nbrs.append((u, k, u, v))

            # 다리 노드(언어·국가 등)에서 뻗을 때는 이웃 수를 제한한다.
            # 차단이 아니라 '정렬 후 자르기' — 차수가 낮은 이웃부터 (구체적인 것 우선)
            if self.G.nodes[node].get("type") in self.cap_types:
                nbrs.sort(key=lambda x: self.G.degree(x[0]))
                nbrs = nbrs[: self.tv["max_neighbors_per_bridge"]]
            else:
                nbrs = nbrs[: self.tv["max_nodes_per_hop"]]

            for nbr, rel, u, v in nbrs:
                # 허브는 '경유' 하지 않는다. 하지만 '존재' 까지 지우지는 않는다 —
                # 'X -WON-> 노벨 문학상' 은 참인 사실이고 근거로 보여줘야 한다.
                # 막는 것은 노벨 문학상을 디딤돌 삼아 아무 수상자로나 건너뛰는 것뿐이다.
                hub = nbr in self.never
                ekey = (u, rel, v)
                if ekey in seen_edges:
                    continue
                seen_edges.add(ekey)
                data = self.G.edges[u, v, rel]
                evidence.append({
                    "subject": u, "relation": rel, "object": v,
                    "depth": depth,
                    "docs": [d for d in (data.get("docs") or "").split("|") if d],
                    "quote": (data.get("evidence") or "").split(" ⏐ ")[0][:300],
                })
                if not hub and nbr not in visited:
                    visited.add(nbr)
                    frontier.append((nbr, depth + 1))
                if len(evidence) >= HARD_CAP:
                    frontier.clear()
                    break

        # 상한을 넘으면 '먼저 찾은 순' 이 아니라 '질문에 가까운 순' 으로 남긴다.
        # 시작 개체에 직접 닿는 삼중항 → 얕은 것 → 차수 낮은(구체적인) 것 순.
        cap = self.tv["max_evidence_triples"]
        dropped = 0
        if len(evidence) > cap:
            def rank(e):
                touches_seed = e["subject"] in seed_set or e["object"] in seed_set
                far_end = e["object"] if e["subject"] in seed_set else e["subject"]
                return (0 if touches_seed else 1, e["depth"], self.G.degree(far_end))
            evidence.sort(key=rank)
            dropped = len(evidence) - cap
            evidence = evidence[:cap]

        for e in evidence:
            arrow = f"{e['subject']} -{e['relation']}-> {e['object']}"
            if arrow not in path:
                path.append(arrow)

        msg = f"{budget}홉 확장: 근거 삼중항 {len(evidence)}개 · 방문 노드 {len(visited)}개"
        if dropped:
            msg += f" (관련도 낮은 {dropped}개는 상한 {cap}에 맞춰 잘라냄)"
        notes = state["notes"] + [msg]
        return {**state, "evidence": evidence, "path": path,
                "visited": sorted(visited), "notes": notes}

    # ── 노드 3: 근거만으로 답변
    def answer(self, state: AgentState) -> AgentState:
        ev = state["evidence"]
        if not ev:
            return {**state, "answer": "", "sufficient": False,
                    "notes": state["notes"] + ["근거가 하나도 없다"]}

        lines = "\n".join(
            f"{i+1}. [{e['subject']}] -{e['relation']}-> [{e['object']}]"
            f"   (출처: {', '.join(e['docs']) or '?'})"
            for i, e in enumerate(ev)
        )
        alias_lines = "\n".join(f"  - '{a}' 는 '{b}' 와 같은 것이다"
                                for a, b in self.alias.items())
        system = (
            "너는 지식 그래프에서 뽑아 온 삼중항만 보고 질문에 답하는 도구다.\n\n"
            "지켜야 할 것\n"
            "- 아래 삼중항에 있는 것만 쓴다. 상식·추측·바깥 지식을 절대 보태지 않는다.\n"
            "- **여러 삼중항을 이어서 답한다.** 답이 한 삼중항에 통째로 들어 있는 경우는 "
            "드물다. A-관계->B 와 B-관계->C 를 이어 A 에서 C 를 끌어내는 것이 네 일이다.\n"
            "- 삼중항의 표기는 통일돼 있다. 질문의 표기가 달라도 같은 것으로 본다:\n"
            f"{alias_lines}\n"
            "- 질문에 연도·순서·'데뷔' 같은 부수 조건이 붙어 있고 그것을 삼중항으로 "
            "확인할 수 없더라도, 질문이 묻는 **핵심 관계**가 삼중항에 있으면 "
            "sufficient 를 true 로 두고 답한다. 대신 확인하지 못한 부분을 answer 에 "
            "한 마디로 밝힌다 (예: '다만 어느 것이 데뷔작인지는 근거에 없습니다').\n"
            "  핵심 관계가 여럿에 걸릴 때는 해당하는 것을 모두 답한다.\n\n"
            "거절해야 할 때\n"
            "- 질문이 묻는 핵심 관계 자체를 뒷받침하는 삼중항이 없으면 "
            "sufficient 를 false 로 두고 answer 는 비운다.\n"
            "- 두 개체 사이에 경로가 있다는 것만으로 관계가 있다고 하지 않는다. "
            "'A 와 B 가 함께 한 일' 을 물었다면 A 와 B 를 직접 잇는 삼중항이 있어야 한다.\n"
            "- 질문이 어떤 사실을 전제해도, 삼중항에 없으면 전제를 따르지 않는다.\n\n"
            "answer 는 한국어 두세 문장.\n"
            '출력은 JSON 하나로만 한다: {"answer": "...", "sufficient": true/false, '
            '"used": [답에 실제로 쓴 삼중항 번호], "reason": "판단 근거 한 문장"}'
        )
        user = f"질문: {state['question']}\n\n삼중항:\n{lines}"
        try:
            out = self._chat(system, user)
        except Exception as e:
            return {**state, "answer": "", "sufficient": False,
                    "notes": state["notes"] + [f"LLM 호출 실패: {e}"]}

        used = [i for i in out.get("used", []) if isinstance(i, int) and 1 <= i <= len(ev)]
        note = f"답변 시도 ({state['hops']}홉): " + (
            f"충분 — 삼중항 {used} 사용" if out.get("sufficient")
            else f"부족 — {out.get('reason', '')}")
        return {**state, "answer": out.get("answer", ""),
                "sufficient": bool(out.get("sufficient")),
                "used": used, "notes": state["notes"] + [note]}

    # ── 노드 4: 반경 넓히기
    def widen(self, state: AgentState) -> AgentState:
        new_hops = state["hops"] + 1
        return {**state, "hops": new_hops, "widened": state["widened"] + 1,
                "notes": state["notes"] + [f"근거가 부족해 {new_hops}홉으로 넓힌다"]}

    # ── 노드 5: 거절
    def refuse(self, state: AgentState) -> AgentState:
        if not state["seeds"]:
            msg = "질문에 나온 개체를 지식 그래프에서 찾지 못했습니다. 답할 근거가 없습니다."
        else:
            msg = (f"{state['hops']}홉까지 넓혀 봤지만, 질문에 답할 근거를 "
                   f"그래프에서 찾지 못했습니다. 지어내지 않겠습니다.")
        return {**state, "answer": msg, "refused": True,
                "notes": state["notes"] + ["거절"]}

    # ── 분기
    def _after_answer(self, state: AgentState) -> str:
        if state.get("sufficient"):
            return "done"
        if state["hops"] < self.tv["widen_to_hops"]:
            return "widen"
        return "refuse"

    def _after_seed(self, state: AgentState) -> str:
        return "expand" if state["seeds"] else "refuse"

    def _build(self):
        from langgraph.graph import StateGraph, START, END

        g = StateGraph(AgentState)
        g.add_node("find_seed", self.find_seed)
        g.add_node("expand", self.expand)
        g.add_node("answer", self.answer)
        g.add_node("widen", self.widen)
        g.add_node("refuse", self.refuse)

        g.add_edge(START, "find_seed")
        g.add_conditional_edges("find_seed", self._after_seed,
                                {"expand": "expand", "refuse": "refuse"})
        g.add_edge("expand", "answer")
        g.add_conditional_edges("answer", self._after_answer,
                                {"done": END, "widen": "widen", "refuse": "refuse"})
        g.add_edge("widen", "expand")
        g.add_edge("refuse", END)
        return g.compile()

    # ── 공개 API
    def ask(self, question, log=True, return_pool=False):
        t0 = time.time()
        final = self.app.invoke({"question": question, "notes": [], "refused": False})
        ev = final.get("evidence", [])
        used = final.get("used") or []
        # LLM 이 used 를 비워 보내면 근거·출처가 통째로 사라진다.
        # 답변 문장에 등장하는 개체를 담은 삼중항으로 되채운다.
        if not used and ev and not final.get("refused"):
            ans = final.get("answer", "")
            used = [i for i, e in enumerate(ev, 1)
                    if e["subject"] in ans or e["object"] in ans]
            if used:
                final.setdefault("notes", []).append(
                    f"LLM 이 사용 근거를 비워 보내, 답변에 등장하는 개체로 "
                    f"{len(used)}개를 되채웠다")
        result = {
            "question": question,
            "answer": final.get("answer", ""),
            "refused": bool(final.get("refused")),
            "hops_used": final.get("hops"),
            "widened": final.get("widened", 0),
            "seeds": final.get("seeds", []),
            # 답에 실제로 쓰인 근거의 경로. 전체 탐색 경로는 path_all 에 둔다.
            "path": [f"{ev[i-1]['subject']} -{ev[i-1]['relation']}-> {ev[i-1]['object']}"
                     for i in used] or final.get("path", [])[:10],
            "path_all": final.get("path", []),
            "evidence": [ev[i - 1] for i in used] if used else [],
            "evidence_pool": len(ev),
            "sources": sorted({d for i in used for d in ev[i - 1]["docs"]}) if used else [],
            "notes": final.get("notes", []),
            "elapsed": round(time.time() - t0, 2),
        }
        if return_pool:
            # 채점에서 '탐색 실패' 와 '생성 실패' 를 가르려면 풀 전체가 필요하다.
            # 근거 풀에 있는데 틀렸으면 생성, 풀에 없으면 탐색 문제다.
            result["pool"] = ev
        if log:
            self._log({k: v for k, v in result.items() if k != "pool"})
        return result

    def _log(self, result):
        path = os.path.join(HERE, "output", "runs.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **result},
                               ensure_ascii=False) + "\n")


# ──────────────────────────────────────────────────────────── CLI

def show(r):
    print()
    for n in r["notes"]:
        print(f"  · {n}")
    print(f"\n{r['answer']}\n")
    if r["evidence"]:
        print("  근거 삼중항")
        for e in r["evidence"]:
            print(f"    [{e['subject']}] -{e['relation']}-> [{e['object']}]"
                  f"  ({', '.join(e['docs'])})")
    if r["path"]:
        shown = r["path"][:8]
        print(f"\n  탄 경로 ({len(r['path'])}개 중 {len(shown)}개)")
        for p in shown:
            print(f"    {p}")
    if r["sources"]:
        print(f"\n  출처 문서: {', '.join(r['sources'])}")
    print(f"\n  ({r['hops_used']}홉 · 넓힌 횟수 {r['widened']} · {r['elapsed']}초)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="*")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    agent = GraphAgent()
    if args.question:
        r = agent.ask(" ".join(args.question))
        if args.json:
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            show(r)
        return 0

    print("질문을 입력하세요 (Ctrl-D 로 종료)\n")
    while True:
        try:
            q = input("> ").strip()
        except EOFError:
            print()
            return 0
        if q:
            show(agent.ask(q))


if __name__ == "__main__":
    sys.exit(main())
