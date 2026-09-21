#!/usr/bin/env python3
"""6단계 — 데모 화면.

  streamlit run app.py

화면에 반드시 드러나야 하는 것
  ① 답변
  ② 실제로 탄 경로
  ③ 근거 삼중항 (원문 인용까지)
  ④ 출처 문서
  ⑤ 근거가 없어 거절한 경우, 그 사실과 어디까지 시도했는지
"""
import json
import os
import re
from pathlib import Path

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="노벨문학상 지식 그래프 에이전트",
                   page_icon="📖", layout="wide")

EXAMPLES = [
    ("2홉", "파블로 네루다와 같은 나라 출신인 다른 노벨문학상 수상자는 누구인가?"),
    ("2홉", "가즈오 이시구로가 받은 맨부커상을 받은 다른 노벨문학상 수상자는 누구인가?"),
    ("3홉", "한강이 받은 국제 부커상을 받은 다른 수상자 중 캐나다 국적인 사람은 누구인가?"),
    ("3홉", "하뤼 마르틴손과 같은 나라 출신인 다른 노벨문학상 수상자가 쓴 작품을 하나 들어라."),
    ("1홉", "윌리엄 골딩의 데뷔 소설은 무엇인가?"),
    ("연도", "2024년 노벨문학상 수상자는 누구인가?"),
    ("거절", "1994년 노벨문학상 수상자는 누구인가?"),
    ("거절", "무라카미 하루키는 몇 년에 노벨문학상을 받았는가?"),
    ("거절", "한강과 윌리엄 포크너가 함께 작업한 작품은 무엇인가?"),
]


@st.cache_resource(show_spinner="그래프를 불러오는 중…")
def load_agent():
    from agent import GraphAgent
    return GraphAgent()


@st.cache_data
def doc_files():
    """문서 제목 -> 파일명 매핑. 그래프 노드는 정규형('한강')이고
    파일은 위키 제목('한강_(작가).md')이라 둘 다 키로 넣는다."""
    man = load_json("data/manifest.json") or {}
    out = {}
    for row in man.get("saved", []):
        title, fname = row["title"], row["file"]
        out[title] = fname
        out[re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()] = fname
    return out


@st.cache_data
def load_json(name):
    path = os.path.join(HERE, name)
    if os.path.exists(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return None


def sidebar(agent):
    st.sidebar.header("지식 그래프")
    G = agent.G
    c1, c2 = st.sidebar.columns(2)
    c1.metric("노드", f"{G.number_of_nodes():,}")
    c2.metric("엣지", f"{G.number_of_edges():,}")

    man = load_json("data/manifest.json")
    if man:
        st.sidebar.caption(
            f"코퍼스 {man['counts']['saved']}건 · 한국어 위키백과 "
            f"(시드 {man['counts']['seeds']}명 → 2홉 후보 "
            f"{man['counts']['two_hop_candidates']}건에서 추림)")

    st.sidebar.divider()
    st.sidebar.subheader("탐색 설정")
    # 캐시된 agent 의 dict 를 직접 고치면 설정이 질문 사이로 새고 원래 값으로
    # 못 돌아온다. config 원본을 복사해 쓰고, 이번 질문에만 적용한다.
    tv = dict(agent.cfg["traverse"])
    agent.tv = tv
    tv["max_hops"] = st.sidebar.slider(
        "기본 반경 (홉)", 1, 3, tv["max_hops"],
        help="여기까지 펼쳐 근거를 모읍니다.")
    tv["widen_to_hops"] = st.sidebar.slider(
        "근거가 부족하면 넓힐 한계", tv["max_hops"], 4,
        max(tv["widen_to_hops"], tv["max_hops"]),
        help="여기까지 넓혀도 근거가 없으면 지어내지 않고 거절합니다.")
    st.sidebar.caption(
        f"통과 금지 노드: {', '.join(tv['never_traverse'])}  \n"
        f"— 수상자 대부분을 잇는 허브라, 지나가면 아무 두 사람이나 "
        f"2홉으로 이어져 버립니다. 다만 '이 사람이 수상자다' 라는 사실 자체는 "
        f"근거로 보여 줍니다.")

    ev = load_json("output/eval.json")
    if ev:
        st.sidebar.divider()
        st.sidebar.subheader("평가셋 성적")
        rows = [{"홉": k, "GraphRAG": v["graph"], "basic RAG": v["basic"]}
                for k, v in ev["by_hops"].items()]
        st.sidebar.dataframe(rows, hide_index=True, use_container_width=True)
        st.sidebar.caption(f"{ev['repeat']}회 반복 평균 · 대조군은 같은 코퍼스의 BM25")


def render(r):
    # ① 답변 — 거절이면 초록 박스로 칠하지 않는다
    if r["refused"]:
        st.warning(f"**{r['answer']}**", icon="🚫")
        st.caption(
            f"시작 개체 {r['seeds'] or '없음'} · {r['hops_used']}홉까지 확장 "
            f"(넓힌 횟수 {r['widened']}) · 훑어본 삼중항 {r['evidence_pool']}개")
    else:
        st.success(r["answer"], icon="💡")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("탄 홉 수", f"{r['hops_used']}홉")
        c2.metric("넓힌 횟수", r["widened"])
        c3.metric("쓴 근거", f"{len(r['evidence'])}개")
        c4.metric("출처 문서", f"{len(r['sources'])}건")

    t1, t2, t3, t4 = st.tabs(
        ["🧭 탄 경로", "🔗 근거 삼중항", "📄 출처 문서", "🪵 진행 기록"])

    with t1:
        if r["path"]:
            st.caption(
                "답하지는 못했지만 여기까지 훑어봤습니다 — 이 중 어느 것도 "
                "질문이 묻는 관계를 뒷받침하지 못했습니다."
                if r["refused"] else "답에 실제로 쓰인 근거의 경로입니다.")
            for p in r["path"]:
                st.markdown(f"- `{p}`")
            extra = [p for p in r.get("path_all", []) if p not in r["path"]]
            if extra:
                with st.expander(f"답에 쓰이지 않은 탐색 경로 {len(extra)}개"):
                    for p in extra[:60]:
                        st.markdown(f"- `{p}`")
        else:
            st.info("탄 경로가 없습니다 — 시작 개체를 찾지 못했습니다.")

    with t2:
        if r["evidence"]:
            for e in r["evidence"]:
                st.markdown(
                    f"**{e['subject']}** → `{e['relation']}` → **{e['object']}**")
                if e.get("quote"):
                    st.caption(f"원문: “{e['quote']}”")
                st.caption(f"출처: {', '.join(e['docs']) or '—'}")
                st.divider()
        else:
            st.info("근거로 쓴 삼중항이 없습니다.")

    with t3:
        if r["sources"]:
            docmap = doc_files()
            for s in r["sources"]:
                # 제목의 공백을 _ 로 바꾸는 것만으로는 '한강 (작가)' 같은 동음이의
                # 주석이 붙은 파일을 못 찾는다. manifest 의 title->file 매핑을 먼저 본다.
                name = docmap.get(s) or (s.replace(" ", "_") + ".md")
                path = os.path.join(HERE, "data", "docs", name)
                with st.expander(s):
                    if os.path.exists(path):
                        st.text(Path(path).read_text(encoding="utf-8")[:2500])
                    else:
                        st.caption(f"원문 파일을 찾지 못했습니다 ({name}).")
        else:
            st.info("출처 문서가 없습니다.")

    with t4:
        for n in r["notes"]:
            st.markdown(f"- {n}")
        st.caption(f"소요 {r['elapsed']}초")


def main():
    st.title("📖 노벨문학상 지식 그래프 에이전트")
    st.caption(
        "한국어 위키백과 문서 60건에서 뽑은 지식 그래프를 여러 홉 타고 답합니다. "
        "**근거로 쓴 삼중항과 실제로 탄 경로를 함께 보여 주고, "
        "근거가 없으면 지어내지 않고 거절합니다.**")

    agent = load_agent()
    sidebar(agent)

    # 예시는 한 줄짜리 목록으로 접어 둔다 — 화면의 주인공은 답변과 근거다
    DIRECT = "선택"
    labels = [DIRECT] + [f"[{tag}] {ex}" for tag, ex in EXAMPLES]

    def _pick():
        chosen = st.session_state.get("ex", DIRECT)
        if chosen != DIRECT:
            st.session_state["q"] = chosen.split("] ", 1)[1]
            st.session_state["run"] = True

    st.selectbox("예시 질문", labels, key="ex", on_change=_pick,
                 help="고르면 바로 물어봅니다. 직접 물어보려면 아래 질문 칸에 쓰세요.")

    q = st.text_input("질문", key="q",
                      placeholder="예: 조수에 카르두치와 같은 나라 출신인 다른 노벨문학상 수상자는?")
    if st.button("물어보기", type="primary"):
        st.session_state["run"] = True

    # 탭을 누르거나 슬라이더를 만지면 Streamlit 이 스크립트를 다시 돌린다.
    # 그때마다 LLM 을 다시 부르지 않도록 결과를 세션에 담아 둔다.
    if st.session_state.pop("run", False) and q.strip():
        with st.spinner("그래프를 타는 중…"):
            st.session_state["result"] = agent.ask(q.strip())

    if st.session_state.get("result"):
        render(st.session_state["result"])


if __name__ == "__main__":
    main()
