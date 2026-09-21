#!/usr/bin/env python3
"""4단계 — 시작 개체 찾기 → n홉 확장 → 근거만으로 답변 (LangGraph).

  python agent.py "한강이 받은 국제 부커상을 받은 다른 수상자는?"
  python agent.py                 # 대화형
  python agent.py --json "..."    # 결과를 JSON 으로
  python agent.py --mermaid       # 구조도 (Mermaid) 출력

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
from typing import TypedDict

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
    widened: int           # widen 을 몇 번 썼는가
    used: list             # 답변이 실제로 인용한 근거 번호
    asked_year: int        # 질문이 연도로 물었다면 그 연도
    year_seeds: list       # 연도 조회로 얻은 시드 (연도 근거를 붙일 대상)


# ──────────────────────────────────────────────────────────── 에이전트

class GraphAgent:
    def __init__(self, cfg=None, graph=None):
        self.cfg = cfg or json.load(
            open(os.path.join(HERE, "config.json"), encoding="utf-8"))
        self.G = graph if graph is not None else nx.read_graphml(
            os.path.join(HERE, "output", "graph.graphml"), force_multigraph=True)
        self.tv = self.cfg["traverse"]
        self.never = set(self.tv["never_traverse"])
        self.cap_types = set(self.tv["cap_fanout_node_types"])
        self.alias = self.cfg["normalize"]["alias_map"]
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

        seeds, taken, year_seeds = [], [], []
        bridged = []
        for name in self.node_names:
            if len(name) < 2 or name in self.never:
                continue                      # 허브는 시작점으로도 쓰지 않는다
            if self.G.nodes[name].get("type") in self.cap_types:
                # 언어·국가·갈래·사조는 '다리' 지 출발점이 아니다.
                # 여기서 출발하면 첫 홉부터 fanout 상한에 걸려 정답이 잘려나간다
                # ("프랑스에서 노벨상 탄 작가?" 가 프랑스 노드에서 출발한 적이 있다).
                if name in q:
                    bridged.append(name)
                continue
            if name not in q:
                continue
            if any(name in t for t in taken):  # 이미 잡은 더 긴 이름의 일부면 건너뛴다
                continue
            seeds.append(name)
            taken.append(name)
            if len(seeds) >= 4:
                break

        notes = [f"질문에서 찾은 시작 개체: {seeds or '없음'}"]
        if bridged and not seeds:
            # 다리만 잡혔다면 출발점이 없는 것과 같다. 조용히 넘어가지 않고 알린다.
            notes.append(f"질문에 {', '.join(bridged)} 같은 다리 개체만 있다 — "
                         f"출발점으로 쓰지 않는다 (거기서 뻗으면 이웃이 상한에 잘린다)")

        # 연도로 묻는 질문 — 수상 연도는 관계가 아니라 노드 속성이라 이름 매칭에 걸리지 않는다.
        # 속성을 뒤져 그 해 수상자를 시작 개체로 삼는다.
        #
        # 단, **이름을 하나도 못 찾았을 때만** 쓴다. 질문 속 연도가 노벨상 연도라는
        # 보장이 없기 때문이다 — "이시구로가 1989년 맨부커상을 받은 작품은?" 에서
        # 1989 는 부커상 연도인데, 그 해 노벨상 수상자(카밀로 호세 셀라)를 끌어와
        # 근거를 오염시킨다. 이름이 있으면 그쪽이 훨씬 확실한 시작점이다.
        year, by_year = self._year_lookup(q)
        if year == "decade":
            notes.append("연대(예: 1990년대)로 물었다 — 이 그래프는 수상 연도를 "
                         "한 해 단위로만 담고 있어 연대 질문은 받지 않는다")
            year = None
        if year and seeds:
            notes.append(f"질문에 {year}년이 있지만 시작 개체를 이름으로 찾았으므로 "
                         f"연도 조회는 쓰지 않는다")
        elif year:
            if by_year:
                for name in by_year:
                    if name not in seeds:
                        seeds.append(name)
                        year_seeds.append(name)
                notes.append(f"{year}년 수상자를 속성에서 찾음: {', '.join(by_year)}")
            else:
                notes.append(
                    f"{year}년을 질문에서 읽었지만, 그 해 수상자 문서가 코퍼스에 없다")

        if not seeds:
            notes.append("시작 개체가 없다 — 그래프에 없는 것을 묻고 있다")
        return {**state, "seeds": seeds, "hops": self.tv["max_hops"],
                "widened": 0, "asked_year": year, "year_seeds": year_seeds,
                "notes": notes}

    def _year_lookup(self, question):
        """질문의 연도와, 그 해에 수상한 사람들을 돌려준다.

        연도를 노드로 만들지 않았기 때문에(허브가 되므로) 이 조회가 필요하다.
        config 의 excluded_relations_note 가 말하는 '속성 조회' 가 이것이다.
        """
        # '1990년대' 는 한 해가 아니라 10년이다. 단년으로 읽으면 1990년 수상자를
        # 그 연대 전체의 답인 양 내놓게 된다 — 실제로 그렇게 답한 적이 있다.
        if re.search(r"(1[89]\d{2}|20[0-2]\d)\s*년\s*대", question):
            return "decade", []
        m = re.search(r"(1[89]\d{2}|20[0-2]\d)\s*년", question)
        if not m:
            return None, []
        year = int(m.group(1))
        winners = sorted(n for n, d in self.G.nodes(data=True)
                         if d.get("nobel_year") == year)
        return year, winners

    # ── 노드 2: n홉 확장
    def expand(self, state: AgentState) -> AgentState:
        # 시드가 없으면 여기까지 오지 않는다 (_after_seed 가 refuse 로 보낸다)
        seeds, budget = state["seeds"], state["hops"]
        evidence, path, visited = [], [], set(seeds)
        seen_edges, seed_set = set(), set(seeds)
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
                # 정렬 없이 자르면 NetworkX 인접 삽입 순서(≒추출 순서)에 기대게 되어
                # 재빌드마다 잘리는 집합이 달라진다. 차수 낮은(구체적인) 것부터.
                nbrs.sort(key=lambda x: (self.G.degree(x[0]), str(x[0])))
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

        # 수상 연도는 속성이라 BFS 가 닿지 않는다. 연도로 물었을 때만, 그 조회로 나온
        # 사람에게만 연도를 근거로 얹는다 (그래프에 노드를 만들지는 않는다).
        #
        # 모든 시드에 무조건 붙였더니 1홉 문항이 무너졌다 — "이시구로가 1989년
        # 맨부커상을 받은 작품은?" 에서 '이시구로 -WON_IN_YEAR-> 2017' 이 근거
        # 맨 앞에 뜨자, 질문의 1989 와 어긋나 답을 못 하게 됐다.
        for name in state.get("year_seeds") or []:
            y = self.G.nodes.get(name, {}).get("nobel_year")
            if y:
                evidence.insert(0, {
                    "subject": name, "relation": "WON_IN_YEAR", "object": str(y),
                    "depth": 0, "docs": [name],
                    "quote": f"{name} 문서에서 읽은 노벨문학상 수상 연도",
                })

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
        # 연도 근거가 실제로 있을 때만 설명한다. 늘 붙이면 연도와 무관한 질문까지
        # 연도로 끌려간다 — "맨부커상을 받은 다른 수상자는?" 이 "같은 해에 받은
        # 다른 수상자는?" 으로 답해졌다.
        year_line = ("- `WON_IN_YEAR` 는 **그 사람이 노벨문학상을 받은 해**를 뜻한다. "
                     "연도로 물었다면 이 삼중항이 바로 답의 근거다.\n"
                     if any(e["relation"] == "WON_IN_YEAR" for e in ev) else "")
        system = (
            "너는 지식 그래프에서 뽑아 온 삼중항만 보고 질문에 답하는 도구다.\n\n"
            "지켜야 할 것\n"
            "- 아래 삼중항에 있는 것만 쓴다. 상식·추측·바깥 지식을 절대 보태지 않는다.\n"
            "- **여러 삼중항을 이어서 답한다.** 답이 한 삼중항에 통째로 들어 있는 경우는 "
            "드물다. A-관계->B 와 B-관계->C 를 이어 A 에서 C 를 끌어내는 것이 네 일이다.\n"
            "- 삼중항의 표기는 통일돼 있다. 질문의 표기가 달라도 같은 것으로 본다:\n"
            f"{alias_lines}\n"
            f"{year_line}"
            "- 질문에 연도·순서·'데뷔' 같은 부수 조건이 붙어 있고 그것을 삼중항으로 "
            "확인할 수 없더라도, 질문이 묻는 **핵심 관계**가 삼중항에 있으면 "
            "sufficient 를 true 로 두고 답한다.\n"
            "  이때 **답을 먼저 말하고**, 확인하지 못한 부분은 뒤에 한 마디로 덧붙인다. "
            "단서만 쓰고 답을 빼먹으면 안 된다 — '윌리엄 골딩의 데뷔 소설은?' 에 "
            "'어느 것이 데뷔작인지는 근거에 없습니다' 라고만 답한 적이 있다. "
            "'파리대왕과 통과 의례가 있습니다. 다만 어느 것이 먼저인지는 근거에 "
            "없습니다' 처럼 후보를 대고 단서를 붙여라.\n"
            "- **해당하는 것이 여럿이면 모두 나열한다.** 하나만 대고 끝내지 않는다. "
            "삼중항에 그 조건을 만족하는 개체가 셋이면 셋을 다 적어라.\n\n"
            "거절해야 할 때\n"
            "- 질문이 묻는 핵심 관계 자체를 뒷받침하는 삼중항이 없으면 "
            "sufficient 를 false 로 두고 answer 는 비운다.\n"
            "- 두 개체 사이에 경로가 있다는 것만으로 관계가 있다고 하지 않는다. "
            "'A 와 B 가 함께 한 일' 을 물었다면 A 와 B 를 직접 잇는 삼중항이 있어야 한다.\n"
            "- 질문이 어떤 사실을 전제해도, 삼중항에 없으면 전제를 따르지 않는다.\n\n"
            "- **답의 종류를 질문에 맞춰라.** 작품을 물었으면 작품 이름을, 사람을 "
            "물었으면 사람 이름을 답한다. 삼중항의 목적어가 나라·언어·상이면 그것은 "
            "작품이 아니다 (`헤이덴스탐 -NATIONALITY-> 스웨덴` 을 보고 '스웨덴' 을 "
            "작품이라 답한 적이 있다). 질문이 '2024년 수상작' 처럼 작품을 물었는데 "
            "삼중항에 사람만 있으면 사람 이름을 작품인 양 내놓지 않는다.\n"
            "  이 규칙은 **답을 고를 때** 쓰는 것이지 거절 사유가 아니다 — "
            "위의 '부수 조건' 규칙을 뒤집지 않는다.\n"
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
        year = state.get("asked_year")
        if not state["seeds"] and year:
            # 연도는 알아들었다. 그 해 수상자가 코퍼스에 없을 뿐이다.
            # 이 둘을 같은 문장으로 뭉뚱그리면 '연도를 못 읽는다' 로 오해된다.
            msg = (f"{year}년 수상자는 이 지식 그래프에 없습니다. "
                   f"코퍼스는 한국어 위키백과 문서 60건으로 만들어 모든 연도를 "
                   f"담고 있지 않습니다. 없는 사람을 지어내지 않겠습니다.")
        elif not state["seeds"]:
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
            for i in used:
                ev[i - 1]["inferred"] = True   # LLM 이 고른 게 아니라 되채운 것
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
    ap.add_argument("--mermaid", action="store_true",
                    help="컴파일된 LangGraph 를 Mermaid 로 출력한다 (REPORT 구조도용)")
    args = ap.parse_args()

    agent = GraphAgent()
    if args.mermaid:
        # 그림을 손으로 그리면 코드와 어긋난다. 실제 그래프에서 뽑는다.
        print(agent.app.get_graph().draw_mermaid())
        return 0
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
