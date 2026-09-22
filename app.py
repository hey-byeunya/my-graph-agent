#!/usr/bin/env python3
"""6단계 — 데모 화면.

  streamlit run app.py

화면에 반드시 드러나야 하는 것
  ① 답변
  ② 실제로 탄 경로
  ③ 근거 삼중항 (원문 인용까지)
  ④ 출처 문서
  ⑤ 근거가 없어 거절한 경우, 그 사실과 어디까지 시도했는지

모양은 '터미널 콘솔 디자인 시스템(범용판)'을 따른다. 색·면·선 토큰은
.streamlit/config.toml 의 테마로, 테마로 못 옮기는 것(섹션 라벨·상태 배지·
액자)은 아래 CSS 로 넣는다.
"""
import html
import json
import os
import re
from pathlib import Path

import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))

st.set_page_config(page_title="노벨문학상 지식 그래프 에이전트", layout="wide")

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

# ── 디자인 토큰 → CSS. 이름은 디자인 시스템의 의미 이름 그대로 쓴다.
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&display=swap');
@import url('https://cdn.jsdelivr.net/npm/pretendard@1.3.9/dist/web/static/pretendard.min.css');

:root {
  --surface-0:#050706; --surface-1:#0a0d0c; --surface-2:#0e1412; --surface-3:#111a17;
  --surface-sel:#1a2621;
  --line:#1d2723; --line-soft:#141c19; --line-control:#2c3a35; --track:#233029;
  --ink-hi:#e8efeb; --ink:#cfd8d3; --ink-dim:#8b9a93; --ink-faint:#3c4a44;
  --accent:#4ee08a; --warn:#e8c04e; --danger:#ff8b74; --danger-line:#e2604b;
  --on-accent:#05100a;
  --mono:'JetBrains Mono','Pretendard',monospace;
}
html, body, [class*="st-"], .stMarkdown, button, input, textarea, select {
  font-family: var(--mono) !important;
}
/* 아이콘은 글리프 폰트라 위 규칙에서 빼야 한다 — 안 빼면 확장 화살표 자리에
   'keyboard_arrow_right' 라는 글자가 그대로 찍힌다 */
[data-testid="stIconMaterial"], .material-icons, .material-symbols-rounded {
  font-family: 'Material Symbols Rounded' !important; }
.block-container { padding-top: 24px; max-width: 1180px; }
header[data-testid="stHeader"] { background: transparent; }

/* 액자 — 화면에 하나. 헤더 바 왼쪽은 무엇의 화면인지 */
.frame-bar { display:flex; align-items:center; gap:10px; padding:9px 14px;
  background:var(--surface-2); border:1px solid var(--line); border-bottom:none;
  font-size:12px; color:var(--ink-dim); }
.frame-bar .dots i { display:inline-block; width:8px; height:8px; border-radius:50%;
  background:var(--line-control); margin-right:5px; }
.frame-bar .dots i:last-child { background:var(--accent); }
.frame-bar b { color:var(--ink-hi); font-weight:500; }
.frame-body { border:1px solid var(--line); background:var(--surface-1);
  padding:18px 16px 16px; box-shadow: inset 0 0 90px rgba(78,224,138,.035);
  margin-bottom:18px; }
.frame-body .cmd { font-size:12.5px; color:var(--ink); margin-bottom:10px; }
.frame-body .cmd span { color:var(--accent); }
.frame-body h1 { font-size:26px; font-weight:700; color:var(--ink-hi);
  margin:0 0 8px; padding:0; letter-spacing:0; }
.frame-body p { font-size:13px; line-height:1.95; color:var(--ink-dim); margin:0; }
.frame-body p b { color:var(--ink); font-weight:500; }

/* 섹션 라벨 — [ X ] 11px · 자간 .14em · 강조색 */
.label { font-size:11px; letter-spacing:.14em; color:var(--accent);
  text-transform:uppercase; margin:18px 0 8px; }
.label.plain { color:var(--ink-dim); }

/* 상태 배지 — 서버 상태값 그대로, 대문자 스네이크, 사각 점 6px */
.badge { display:inline-flex; align-items:center; gap:7px; padding:3px 9px;
  font-size:11.5px; letter-spacing:.04em; border:1px solid; }
.badge::before { content:""; width:6px; height:6px; background:currentColor; }
.badge.ok { color:var(--accent); border-color:var(--accent); }
.badge.warn { color:var(--warn); border-color:var(--warn); }
.badge.danger { color:var(--danger); border-color:var(--danger-line); }
.badge-row { display:flex; justify-content:space-between; align-items:center;
  margin:4px 0 8px; font-size:11.5px; color:var(--ink-faint); }

/* 답변 패널 — 답했으면 accent, 거절이면 warn 테두리 */
.st-key-answer_ok, .st-key-answer_refused { padding:14px 16px;
  background:var(--surface-1); border:1px solid var(--accent); }
.st-key-answer_refused { border-color:var(--warn); }
.st-key-answer_ok p, .st-key-answer_ok li,
.st-key-answer_refused p, .st-key-answer_refused li {
  font-size:14px; line-height:1.9; color:var(--ink-hi); }

/* 계기 — 수치 17/700 ink-hi, 라벨 ink-dim */
[data-testid="stMetric"] { background:var(--surface-1); border:1px solid var(--line);
  padding:10px 14px; }
[data-testid="stMetricLabel"] p { font-size:11.5px; color:var(--ink-dim); }
[data-testid="stMetricValue"] { font-size:17px; font-weight:700; color:var(--ink-hi); }

/* 탭 — 테두리 없이 면을 반전 */
.stTabs [data-baseweb="tab-list"] { gap:0; border-bottom:1px solid var(--line); }
.stTabs [data-baseweb="tab"] { padding:6px 14px; font-size:12px; color:var(--ink-dim); }
.stTabs [aria-selected="true"] { background:var(--surface-sel); color:var(--ink-hi); }
.stTabs [data-baseweb="tab-highlight"] { background:var(--accent); }

/* 근거 삼중항 · 로그 한 줄 */
.triple { padding:9px 0; border-bottom:1px solid var(--line-soft); font-size:12.5px; }
.triple .rel { color:var(--accent); }
.triple .ent { color:var(--ink-hi); }
.triple .quote { color:var(--ink-dim); font-size:11.5px; line-height:1.85; margin-top:3px; }
.triple .src { color:var(--ink-faint); font-size:11px; }
.log { background:var(--surface-0); border:1px solid var(--line); padding:10px 12px;
  font-size:11.5px; line-height:1.85; }
.log div { color:var(--ink); }
.log .g { display:inline-block; width:1.4em; }
.log .g.ok { color:var(--accent); } .log .g.warn { color:var(--warn); }
.log .g.faint { color:var(--ink-faint); }
.path { font-size:12px; line-height:1.85; color:var(--ink); }
.path .arrow { color:var(--ink-faint); }

/* 알림 — 제목 한 줄 + 본문 한 문장 */
.notice { border:1px solid var(--warn); padding:10px 14px; font-size:12px;
  color:var(--ink); line-height:1.85; }
.notice b { color:var(--warn); font-weight:500; }
.empty { border:1px dashed var(--line-control); padding:16px; text-align:center;
  font-size:12px; color:var(--ink-dim); }

/* 버튼 — 채운 강조 버튼은 화면당 하나 */
.stFormSubmitButton button[kind="primaryFormSubmit"],
.stButton button[kind="primary"] { background:var(--accent); color:var(--on-accent);
  border:1px solid var(--accent); font-weight:700; }
/* 입력 칸 — 안쪽은 페이지보다 어두운 surface-0, 테두리는 '누를 수 있는 것' 색.
   질문 칸은 이 화면에서 사람이 손대야 하는 자리라 한 단계 더 밝게 두고,
   커서가 들어오면 강조색으로 바뀐다 */
.stTextInput input, .stSelectbox [data-baseweb="select"] > div {
  background:var(--surface-0) !important; }
/* 테두리는 input 이 아니라 그것을 감싼 div(react-aria 래퍼) 에 붙어 있다 */
.stTextInput .react-aria-TextField > div,
.stSelectbox .react-aria-ComboBox > div {
  border-color:var(--line-control) !important; }
.st-key-q .react-aria-TextField > div { border-color:var(--ink-dim) !important; }
.stTextInput .react-aria-TextField > div:focus-within,
.stSelectbox .react-aria-ComboBox > div:focus-within {
  border-color:var(--accent) !important; }
.st-key-q label p { color:var(--ink) !important; }
label p { font-size:11.5px !important; color:var(--ink-dim) !important; }

/* 사이드바 */
section[data-testid="stSidebar"] { border-right:1px solid var(--line); }
section[data-testid="stSidebar"] .label:first-child { margin-top:4px; }
.kv { font-size:11.5px; line-height:1.85; color:var(--ink-dim); }
.kv b { color:var(--ink-hi); font-weight:700; }
.unknown { color:var(--warn); }
</style>
"""


def label(text, plain=False):
    st.markdown(f'<div class="label{" plain" if plain else ""}">[ {text} ]</div>',
                unsafe_allow_html=True)


def esc(s):
    return html.escape(str(s))


@st.cache_resource(show_spinner="그래프를 불러온다…")
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
    with st.sidebar:
        label("GRAPH")
        G = agent.G
        c1, c2 = st.columns(2)
        c1.metric("노드", f"{G.number_of_nodes():,}")
        c2.metric("엣지", f"{G.number_of_edges():,}")

        man = load_json("data/manifest.json")
        if man:
            st.markdown(
                f'<div class="kv">코퍼스 <b>{man["counts"]["saved"]}</b>건 · 한국어 위키백과<br>'
                f'시드 {man["counts"]["seeds"]}명 → 2홉 후보 '
                f'{man["counts"]["two_hop_candidates"]}건에서 추렸다</div>',
                unsafe_allow_html=True)
        else:
            st.markdown('<div class="kv">코퍼스 <span class="unknown">확인 못 함</span>'
                        ' — manifest.json 이 없다</div>', unsafe_allow_html=True)

        label("TRAVERSE")
        # 캐시된 agent 의 dict 를 직접 고치면 설정이 질문 사이로 새고 원래 값으로
        # 못 돌아온다. config 원본을 복사해 쓰고, 이번 질문에만 적용한다.
        tv = dict(agent.cfg["traverse"])
        agent.tv = tv
        tv["max_hops"] = st.slider(
            "--max-hops", 1, 3, tv["max_hops"],
            help="여기까지 펼쳐 근거를 모은다.")
        tv["widen_to_hops"] = st.slider(
            "--widen-to-hops", tv["max_hops"], 4,
            max(tv["widen_to_hops"], tv["max_hops"]),
            help="근거가 모자라면 여기까지 넓힌다. 그래도 없으면 지어내지 않고 거절한다.")
        st.markdown(
            f'<div class="kv">통과 금지 노드 <b>{esc(", ".join(tv["never_traverse"]))}</b><br>'
            f'수상자 대부분을 잇는 허브라 지나가면 아무 두 사람이나 2홉으로 이어진다. '
            f'"이 사람이 수상자다"라는 사실은 근거로 보여 준다.</div>',
            unsafe_allow_html=True)

        label("EVAL")
        ev = load_json("output/eval.json")
        if ev:
            # 화면에는 사람 재채점을 반영한 성적을 쓴다 — REPORT 4절과 같은 숫자여야
            # 한다. 채점기 원점수는 아래 한 줄로 함께 밝힌다.
            board = ev.get("regraded") or ev
            rows = [{"홉": k, "graph": v["graph"], "basic": v["basic"]}
                    for k, v in board["by_hops"].items()]
            st.dataframe(rows, hide_index=True, width="stretch")
            st.markdown(
                f'<div class="kv">전체 <b>{board["overall"]["graph"]:.2f}</b> '
                f'vs basic RAG {board["overall"]["basic"]:.2f} · '
                f'{ev["repeat"]}회 반복 평균 · 대조군은 같은 코퍼스의 BM25</div>',
                unsafe_allow_html=True)
            if ev.get("regraded"):
                ids = ", ".join(f"Q{i}" for i in ev["regraded"]["applied"])
                st.markdown(
                    f'<div class="kv">{ids} 은 사람이 다시 채점한 값이다 — 채점기 '
                    f'원점수는 {ev["overall"]["graph"]:.2f} 다 (REPORT 4절)</div>',
                    unsafe_allow_html=True)
        else:
            st.markdown('<div class="kv">성적 <span class="unknown">확인 못 함</span>'
                        ' — output/eval.json 이 없다</div>', unsafe_allow_html=True)


def render(r):
    # 상태 배지는 화면에 하나. 거절은 warn — 실패가 아니라 '사람 판단이 필요한 정지'다
    if r["refused"]:
        badge = '<span class="badge warn">REFUSED</span>'
    else:
        badge = '<span class="badge ok">ANSWERED</span>'
    st.markdown(f'<div class="badge-row">{badge}<span>{r["elapsed"]}s</span></div>',
                unsafe_allow_html=True)

    # ① 답변 — 거절이면 강조색으로 칠하지 않는다
    with st.container(key="answer_refused" if r["refused"] else "answer_ok"):
        st.markdown(r["answer"])
    if r["refused"]:
        st.markdown(
            f'<div class="kv" style="margin-top:8px">시작 개체 '
            f'<b>{esc(r["seeds"] or "없음")}</b> · {r["hops_used"]}홉까지 확장 '
            f'(넓힌 횟수 {r["widened"]}) · 훑어본 삼중항 {r["evidence_pool"]}개</div>',
            unsafe_allow_html=True)
    else:
        # 4열은 좁은 화면에서 한 줄씩 쌓여 세로로 길어진다. 2×2 로 나눈다
        c1, c2 = st.columns(2)
        c1.metric("탄 홉 수", f"{r['hops_used']}홉")
        c2.metric("넓힌 횟수", r["widened"])
        c3, c4 = st.columns(2)
        c3.metric("쓴 근거", f"{len(r['evidence'])}개")
        c4.metric("출처 문서", f"{len(r['sources'])}건")

    st.write("")
    t1, t2, t3, t4 = st.tabs(["경로", "근거 삼중항", "출처 문서", "진행 기록"])

    with t1:
        if r["path"]:
            st.markdown(
                '<div class="kv">' + (
                    "답하지 못했지만 여기까지 훑었다. 이 중 어느 것도 질문이 묻는 관계를 "
                    "뒷받침하지 못했다." if r["refused"] else
                    "답에 실제로 쓰인 근거의 경로다.") + "</div>",
                unsafe_allow_html=True)
            st.markdown('<div class="path">' + "".join(
                f"<div>{esc(p).replace('-&gt;', '<span class=arrow>-&gt;</span>')}</div>"
                for p in r["path"]) + "</div>", unsafe_allow_html=True)
            extra = [p for p in r.get("path_all", []) if p not in r["path"]]
            if extra:
                with st.expander(f"답에 쓰이지 않은 탐색 경로 {len(extra)}개"):
                    st.markdown('<div class="path">' + "".join(
                        f"<div>{esc(p)}</div>" for p in extra[:60]) + "</div>",
                        unsafe_allow_html=True)
        else:
            st.markdown('<div class="empty">탄 경로가 없다 — 시작 개체를 찾지 못했다</div>',
                        unsafe_allow_html=True)

    with t2:
        if r["evidence"]:
            rows = []
            for e in r["evidence"]:
                quote = (f'<div class="quote">“{esc(e["quote"])}”</div>'
                         if e.get("quote") else "")
                rows.append(
                    f'<div class="triple"><span class="ent">{esc(e["subject"])}</span> '
                    f'<span class="rel">-{esc(e["relation"])}-&gt;</span> '
                    f'<span class="ent">{esc(e["object"])}</span>{quote}'
                    f'<div class="src">출처 {esc(", ".join(e["docs"]) or "—")}</div></div>')
            st.markdown("".join(rows), unsafe_allow_html=True)
        else:
            st.markdown('<div class="empty">근거로 쓴 삼중항이 없다</div>',
                        unsafe_allow_html=True)

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
                        st.markdown(f'<div class="kv"><span class="unknown">확인 못 함</span>'
                                    f' — 원문 파일이 없다 ({esc(name)})</div>',
                                    unsafe_allow_html=True)
        else:
            st.markdown('<div class="empty">출처 문서가 없다</div>', unsafe_allow_html=True)

    with t4:
        # 로그 한 줄은 글리프 · 내용. 마지막 줄만 결과 글리프를 단다
        lines = [f'<div><span class="g faint">·</span>{esc(n)}</div>' for n in r["notes"]]
        end = ('<span class="g warn">■</span>거절 — 근거가 없어 멈췄다' if r["refused"]
               else '<span class="g ok">✓</span>답변 완료')
        lines.append(f"<div>{end} · {r['elapsed']}s</div>")
        st.markdown('<div class="log">' + "".join(lines) + "</div>",
                    unsafe_allow_html=True)


def main():
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="frame-bar"><span class="dots"><i></i><i></i><i></i></span>'
        'my-graph-agent — <b>nobel-literature</b> · graph-rag</div>'
        '<div class="frame-body">'
        '<div class="cmd"><span>➜</span> python agent.py --ask</div>'
        '<h1>노벨문학상 지식 그래프 에이전트</h1>'
        '<p>한국어 위키백과 문서 60건에서 뽑은 지식 그래프를 여러 홉 타고 답한다. '
        '<b>근거로 쓴 삼중항과 실제로 탄 경로를 함께 보여 주고, '
        '근거가 없으면 지어내지 않고 거절한다.</b></p></div>',
        unsafe_allow_html=True)

    agent = load_agent()
    sidebar(agent)

    label("ASK")
    # 예시는 한 줄짜리 목록으로 접어 둔다 — 화면의 주인공은 답변과 근거다
    DIRECT = "선택"
    labels = [DIRECT] + [f"[{tag}] {ex}" for tag, ex in EXAMPLES]

    def _pick():
        chosen = st.session_state.get("ex", DIRECT)
        if chosen != DIRECT:
            st.session_state["q"] = chosen.split("] ", 1)[1]
            st.session_state["run"] = True

    st.selectbox("--example", labels, key="ex", on_change=_pick,
                 help="고르면 바로 묻는다. 직접 물으려면 아래 --question 칸에 쓴다.")

    # st.form 으로 감싸야 텍스트 칸에서 Enter 를 눌러도 "물어보기" 를 누른 것과
    # 같이 제출된다 (폼 밖 text_input 은 Enter 를 눌러도 값만 반영될 뿐, 버튼을
    # 따로 눌러야 실행됐다).
    with st.form("ask_form", border=False):
        q = st.text_input("--question", key="q",
                          placeholder="예: 조수에 카르두치와 같은 나라 출신인 다른 노벨문학상 수상자는?")
        submitted = st.form_submit_button("물어보기 ↵", type="primary")
    if submitted:
        st.session_state["run"] = True

    # 탭을 누르거나 슬라이더를 만지면 Streamlit 이 스크립트를 다시 돌린다.
    # 그때마다 LLM 을 다시 부르지 않도록 결과를 세션에 담아 둔다.
    if st.session_state.pop("run", False) and q.strip():
        with st.spinner("그래프를 탐색한다…"):
            st.session_state["result"] = agent.ask(q.strip())

    if st.session_state.get("result"):
        label("RESULT")
        render(st.session_state["result"])
    else:
        st.markdown('<div class="empty" style="margin-top:18px">아직 질문이 없다 — '
                    '예시를 고르거나 질문을 쓰고 Enter</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    main()
