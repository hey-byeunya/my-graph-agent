# 작업 계획 — 노벨문학상 수상자 GraphRAG

과제 요구(필수 5단계)와 제출 루브릭(3항목)을 단계별 산출물로 옮긴 것.

## 루브릭 ↔ 산출물 대응

| 루브릭 | 어디서 증명되나 |
|---|---|
| 엔드투엔드 구동 · 제출물 완결성 | `collect_corpus.py → build_graph.py → agent.py → evaluate.py → app.py` 가 오류 없이 순서대로 돎 + README 실행법 |
| 스키마 설계 · 멀티홉 타당성 | `config.json` 의 schema/traverse 절 + 경로 기록(`output/runs.jsonl`) + 근거 없을 때 거절 |
| 성능 검증 · 실패 분석 | `output/eval.json` 홉 수별 표 + REPORT 3절 실패 층 분류 |

## 단계

### 1단계 — 코퍼스 수집 (60건 이상)
- `collect_corpus.py`: MediaWiki API(`ko.wikipedia.org/w/api.php`), HTML 파싱 안 함
- 시드 10명(config.json `corpus.seeds`) → 본문 링크(`prop=links`, ns=0) 중 **여러 시드가 함께 가리키는 것**부터
- 그 후보 중 시드와 분류를 하나 이상 공유하는 것만 남김 / 연도·목록·틀·분류 제외
- 본문 800자 미만 토막글 버림 → `data/docs/*.md`, `data/manifest.json`
- **채택·탈락 기준을 manifest 에 숫자로 남긴다** (REPORT 1절 재료)

### 2단계 — 평가셋 10문항 이상 (`data/goldenset.json`)
- 1홉 3문항 · 2홉 5문항 · 3홉 2문항 · **답이 없어야 정답인 거절 문항 2건**
- 문항마다: 기대 정답 · 기대 경로(관계 이름을 순서·방향까지) · 원문 근거 문장
- 근거는 그래프가 아니라 **원문 md 에서 직접 확인** (그래프에서 뽑으면 순환 논리)

### 3단계 — 그래프 구축 (`build_graph.py`)
- 스키마 7관계로 제한해 LLM 추출 → `output/triples_raw.json`
- 정규화: 표기 통일 · 별칭 병합(rapidfuzz ≥90) · 일반명사 노드 제외
- **정규화 전/후 노드·엣지 수를 찍는다** (무엇이 합쳐졌는지가 REPORT 2절 재료)
- → `output/graph.graphml`

### 4단계 — 멀티홉 에이전트 (`agent.py`, LangGraph)
- State: `question · seeds · hops · visited · evidence · path · answer`
- 노드: `find_seed → expand → (부족하면) widen → answer` / 한계까지 가도 없으면 거절
- 허브 통과 금지: `노벨문학상` 고정 + 차수 25 초과 노드 자동 배제
- 실행마다 `output/runs.jsonl` 에 경로·근거 append

### 5단계 — 평가 (`evaluate.py`)
- GraphRAG vs basic RAG(BM25) 같은 문항 같은 채점
- 홉 수별로 갈라 보고 (평균 하나로 뭉치지 않음)
- 경로 재현율 = 기대 경로 관계 중 실제 근거에 들어온 비율
- 실패 층 분류: 색인(삼중항 자체가 없음) / 탐색(그래프엔 있는데 못 탐) / 생성(근거는 맞는데 답이 틀림)
- → `output/eval.json`

### 6단계 — 데모 (`app.py`, streamlit)
- 질문 입력 → 답변 · 탄 경로 · 근거 삼중항 · 출처 문서
- 거절한 경우도 화면에 드러남
- 로컬 실행까지가 필수. 화면 캡처 → `docs/screenshot-*.png`

### 7단계 — REPORT.md 작성 + 저장소 공개
- 6개 절 채우기 (Mermaid 구조도 포함)
- 공개 전 점검: `.env` 미포함, `git log -p` 에 키 문자열 없음

## 결정해 둔 것 (REPORT 에 근거와 함께 쓸 것)

- **연도를 노드로 만들지 않음** — 같은 해 수상자가 전부 묶여 무의미한 허브가 됨. 대가: 연도 질문은 속성 조회로 처리
- **출판사·번역가 관계 제외** — 위키 본문에 일관되게 안 나옴. 대가: 출판 경로 질문 불가
- **`노벨문학상` 노드 통과 금지** — 지나가면 아무 두 수상자나 2홉이 되어 멀티홉이 무의미해짐
- **기본 2홉, 근거 부족 시에만 3홉으로 widen** — 넓힐수록 근거가 희석되므로 조건부

## 상태

- [x] 0. 저장소 골격 · 스키마 확정
- [x] 1. 코퍼스 수집 — 60건 (2홉 후보 610 → 분류 공유 120 → 토막글 3건 탈락)
- [x] 2. 평가셋 — 12문항 (1홉 3 · 2홉 5 · 3홉 2 · 거절 2), 근거 25개 전부 원문 대조 통과
- [x] 3. 그래프 구축 — 노드 401 · 엣지 453, 색인 점검 10/10 통과
- [x] 4. 에이전트 — LangGraph find_seed→expand→answer→widen/refuse, 단일 실행 12/12 (Q3 불안정)
- [x] 5. 평가 — GraphRAG 0.97 vs basic RAG 0.71, 반경 ablation 4종, 실패 층 분류 검증됨
- [ ] 6. 데모
- [ ] 7. REPORT · 공개
