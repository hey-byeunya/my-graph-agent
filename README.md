# my-graph-agent

주제: **노벨문학상 수상자** — 수상자·작품·언어·국가·상을 잇는 지식 그래프

한국어 위키백과 문서 60건에서 지식 그래프를 만들고, 멀티홉 질문에 **근거로 쓴 삼중항과 실제로 탄 경로를 함께** 답합니다. 근거가 없으면 지어내지 않고 거절합니다.

```
노드 401 · 엣지 453 · 평가셋 12문항
GraphRAG 0.97  vs  basic RAG(BM25) 0.71     ← 2홉 구간은 1.00 vs 0.30
```

## 실행 방법

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # OPENAI_API_KEY 를 채웁니다
```

파이프라인을 처음부터 돌리려면 순서대로:

```bash
python collect_corpus.py     # ① 위키백과에서 문서 60건 수집  → data/docs/
python verify_goldenset.py   # ② 평가셋 근거가 원문과 맞는지 대조
python build_graph.py        # ③ 추출 + 정제            → output/graph.graphml
python audit_graph.py        # ③' 기대 경로가 그래프에 깔렸는지 점검
python evaluate.py           # ⑤ 홉 수별 채점 + basic RAG 대조 → output/eval.json
```

이미 만들어진 `output/` 을 쓴다면 바로:

```bash
python agent.py "파블로 네루다와 같은 나라 출신인 다른 노벨문학상 수상자는?"
streamlit run app.py         # ⑥ 데모 화면 (http://localhost:8501)
```

> `build_graph.py` 는 문서별 추출 결과를 `.cache/` 에 남기므로 재실행이 공짜입니다.
> 전체 추출 비용은 gpt-4o-mini 기준 약 $0.035 입니다.

## 데모 화면

질문 → 답변 · 탄 홉 수 · 근거 삼중항(원문 인용 포함) · 출처 문서

![답변 화면](docs/demo-answer.png)

근거가 없으면 **지어내지 않고 거절합니다.** 어디까지 넓혀 봤는지, 무엇을 훑었는지도 함께 보여 줍니다.

![거절 화면](docs/demo-refusal.png)

## 디렉토리

```
collect_corpus.py    ① 코퍼스 수집 (MediaWiki API)
verify_goldenset.py  ② 평가셋 자체검사 — 근거가 원문에 글자 그대로 있는지 대조
build_graph.py       ③ 스키마 제한 추출 + 정규화(별칭·불용어·병합)
audit_graph.py       ③' 색인 층 점검 — 기대 경로가 그래프에 있는가
agent.py             ④ LangGraph 멀티홉 에이전트
rag_basic.py         ⑤ 대조군 (BM25) — 같은 코퍼스·모델·채점
evaluate.py          ⑤ 홉 수별 채점 · 경로 재현율 · 실패 층 분류
app.py               ⑥ 데모 (streamlit)
make_screenshots.py  문서용 화면 캡처 (playwright, 개발용)

config.json          도메인에 묶인 값 전부 — 시드·스키마·허브 기준·반경
data/                docs/ (원본 60건) · goldenset.json (평가셋) · manifest.json
output/              graph.graphml · triples.json · runs.jsonl · eval.json
PLAN.md              작업 계획과 결정 기록
REPORT.md            제출용 보고서
```

코드에는 도메인 지식을 하드코딩하지 않았습니다 — 주제를 바꾸려면 `config.json` 의 시드와 스키마만 갈아 끼우면 됩니다.

> `.env` 는 커밋하지 않습니다.
