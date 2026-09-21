# my-graph-agent

주제: **노벨문학상 수상자** — 수상자·작품·언어·국가·상을 잇는 지식 그래프

한국어 위키백과 문서 60건에서 지식 그래프를 만들고, 멀티홉 질문에 **근거로 쓴 삼중항과 실제로 탄 경로를 함께** 답합니다. 근거가 없으면 지어내지 않고 거절합니다.

```
노드 416 · 엣지 468 · 평가셋 14문항 (5회 반복)
GraphRAG 0.90  vs  basic RAG(BM25) 0.66     ← 2홉 구간은 1.00 vs 0.30
```

설계 근거·측정 결과·실패 분석은 [REPORT.md](REPORT.md) 에 있습니다.

## 실행 방법

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # OPENAI_API_KEY 를 채웁니다
```

![답변 화면](docs/demo-answer.png)

### 바로 써 보기 — 저장소에 든 그래프로

그래프·평가 결과가 `output/` 에 이미 들어 있으므로 곧바로 질문할 수 있습니다.

```bash
python agent.py "파블로 네루다와 같은 나라 출신인 다른 노벨문학상 수상자는?"
python agent.py                # 대화형
streamlit run app.py           # 데모 화면 (http://localhost:8501)
```

### 전 구간이 도는지 한 번에 확인

```bash
python run_e2e.py              # 수집→검사→구축→점검→답변→채점→데모 적재 → output/e2e_run.json
```

### 단계별로 돌리기

```bash
python collect_corpus.py       # ① 문서 60건 수집 → data/docs/
                               #    이미 모았으면 아무것도 하지 않음 · 일부 빠졌으면 그것만 받음
                               #    --refresh 재수집 · --prune manifest 밖 파일 삭제
python verify_goldenset.py     # ② 평가셋 근거 26개가 원문과 글자 그대로 맞는지 대조
python build_graph.py          # ③ 추출 + 정제 → output/graph.graphml
python audit_graph.py          # ③' 평가셋의 기대 경로가 그래프에 깔렸는지 점검
python evaluate.py             # ⑤ 14문항 × 5회 채점 + basic RAG 대조 → output/eval.json
```

그 밖에:

```bash
python agent.py --mermaid                               # LangGraph 구조도 (REPORT 5절의 원본)
python evaluate.py --max-hops 3 --no-widen --tag hop3   # 반경 실험 → output/eval_hop3.json
python check_prompt_regression.py                        # 답변 프롬프트를 고쳤다면 먼저 — 과거 두 회귀를 값싸게 재확인
```

> **REPORT 의 수치를 그대로 재현하려면 `build_graph.py` 를 다시 돌리지 마세요.**
> 추출은 LLM 이 하므로, 추출 캐시(`.cache/`, 저장소에 없음)가 없는 상태에서 다시 돌리면
> 삼중항이 조금 달라지고 그에 따라 성적도 움직입니다. 저장소에 든 `output/graph.graphml`
> 을 그대로 쓰면 REPORT 와 같은 그래프입니다.
>
> 한 번 추출하고 나면 캐시가 생겨 그다음부터는 같은 그래프가 나옵니다 — 캐시 키가
> 프롬프트·모델·문서 **내용 해시**이기 때문입니다. 전량 추출 비용은 gpt-4o-mini 로 약 $0.04 입니다.
>
> 코퍼스는 한 번 모으면 고정됩니다. `collect_corpus.py` 는 `manifest.json` 이 완성돼 있으면
> 위키백과를 치지 않고, `build_graph.py` 도 디렉토리가 아니라 manifest 목록만 읽습니다.

## 디렉토리

```
collect_corpus.py    ① 코퍼스 수집 (MediaWiki API)
verify_goldenset.py  ② 평가셋 자체검사 — 근거가 원문에 글자 그대로 있는지 대조
build_graph.py       ③ 스키마 제한 추출 + 정규화(별칭·불용어·병합) + 수상 연도 속성
audit_graph.py       ③' 색인 층 점검 — 기대 경로가 그래프에 있는가
agent.py             ④ LangGraph 멀티홉 에이전트
rag_basic.py         ⑤ 대조군 (BM25) — 같은 코퍼스·모델·채점
evaluate.py          ⑤ 홉 수별 채점 · 경로 재현율 · 실패 층 분류
app.py               ⑥ 데모 (streamlit)
run_e2e.py           전 구간 구동 점검
check_prompt_regression.py   답변 프롬프트 회귀 안전망 — 과거 두 사고를 Q3·Q6으로 재확인

config.json          시드 · 스키마 · 별칭 · 병합 금지 쌍 · 허브 · 반경 · 모델
data/                docs/ (원본 60건) · goldenset.json (평가셋) · manifest.json (코퍼스 목록)
output/              graph.graphml · triples.json · eval.json · eval_hop*.json
                     build_report.json · index_audit.json · e2e_run.json
docs/                데모 화면 캡처
REPORT.md            제출용 보고서
```

### 주제를 바꾸려면

도메인에 묶인 **값**(시드 · 스키마 · 별칭 · 병합 금지 쌍 · 통과 금지 허브 · 반경)은 전부 `config.json` 에 있습니다. 다만 아래는 이 주제에 맞춰 코드에 들어가 있어 함께 손봐야 합니다.

- `build_graph.py` 의 수상 연도 추출 — 본문에서 "노벨 문학상" 옆의 연도를 찾는 정규식
- `agent.py` 의 답변 프롬프트 — 실제로 틀렸던 사례(골딩의 데뷔작, '스웨덴'을 작품이라 답한 것)를 예시로 담고 있음
- `app.py` 의 제목과 예시 질문

> `.env` 와 실행 로그(`output/runs.jsonl`)는 커밋하지 않습니다.
