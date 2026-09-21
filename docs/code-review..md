# 코드 리뷰 — 2026-09-21

리뷰 범위: 전체 파이프라인 8개 스크립트 + `config.json` + working tree 변경분(`git status`/`diff` 대조).
방식: 읽기 전용 리뷰. 본 리뷰 자체 외의 코드·문서 수정은 하지 않았음.

## P0 — 지금 상태가 깨져 있습니다 (먼저 보셔야 할 것)

### 1. 코퍼스·그래프·문서가 서로 다른 세계를 말합니다
- `data/docs/`는 **85건**인데 `data/manifest.json`의 `saved`는 **60건**, `REPORT.md`·`README.md`는 "문서 60건 · 노드 401 · 엣지 453"을 주장합니다. 실제 `output/build_report.json`(12:31 실행)은 **85건 · 노드 549 · 엣지 634**입니다.
- 원인 2개가 겹쳐 있습니다:
  - `collect_corpus.py:192-196` — 파일이 있으면 무조건 skip(이어받기). 삭제된 문서는 `data/docs/`에 계속 남습니다.
  - `build_graph.py:320` — `data/docs/*.md`를 전부 읽습니다. manifest의 60건 목록이 아니라 디렉토리 전체를 믿습니다.
- 결과: 새로 수집된 25건(`git status`의 untracked 목록)이 디렉토리에 쌓이고, 재빌드 때 조용히 흡수됐습니다. `manifest`의 멤버십도 통째로 바뀌었습니다(예: 기존 `슈무엘 요세프 아그논·버트런드 러셀·윈스턴 처칠` 탈락 → `카를 슈피텔러·아니 에르노` 등 편입). 위키 라이브 소스 + revision 고정 없음이라 재실행이 비결정적이라는 점도 함께 기록해 둘 만합니다.

### 2. `output/` 내부 시점이 엇갈립니다
- `output/eval.json`은 12:15 실행(旧 60건 그래프 기준, GraphRAG 1.00 vs basic 0.68)인데, `graph.graphml`·`triples.json`·`build_report.json`은 12:31 실행(85건 기준)입니다. 즉 **REPORT의 성적표와 현재 그래프는 다른 그래프에서 나온 숫자**입니다. 이 상태로 커밋하면 재현 주장이 깨집니다.
- `output/index_audit.json`에는 `Q13 MISSING — "노드 없음: 1945"`가 새로 생겼습니다. 아래 3번과 연결됩니다.

### 3. Q13(연도 문항)이 설계와 검사기 사이에서 모순됩니다
- 설계: "연도는 노드가 아니라 `nobel_year` 속성" (`config.json:82`, `build_graph.py:72-75`). `data/goldenset.json` Q13의 기대경로는 `['가브리엘라 미스트랄', 'WON_IN_YEAR', '1945']`입니다.
- 그런데 `audit_graph.py:74-81`과 `evaluate.py:104-109`(`classify_failure`)는 경로의 양 끝을 **무조건 그래프 노드 존재 여부로 검사**합니다. `"1945"`는 노드가 아니므로 Q13은 구조적으로 `MISSING`/실패 시 `색인` 오분류됩니다. `WON_IN_YEAR` 스텝에 대한 면제가 두 곳 모두에 빠져 있습니다. (`step_matched`·`path_recall` 쪽은 relation 문자열 비교라 정상 동작합니다.)

## P1 — 버그 또는 버그에 준하는 것

1. **`collect_corpus.py:194` — 캐시된 파일의 `chars`가 바이트 수입니다.** `os.path.getsize()`를 그대로 `chars`에 넣습니다. 한글 UTF-8 기준 약 3배 부풀려지므로, manifest의 `chars`와 REPORT의 "중앙값 1,549자·합계 207,922자" 집계가 섞인 단위로 오염됩니다. 새로 수집된 건은 `len(body)`(문자 수)라 같은 필드 안에서 단위가 다릅니다.
2. **`app.py:139-140` — 출처 문서 보기가 `(작가)` 표기에서 깨집니다.** `s.replace(" ", "_") + ".md"`로 경로를 재구성하는데, 실제 파일은 `한강_(작가).md`입니다. 그래프 노드명(정규형 `"한강"`)으로는 `한강.md`를 찾게 되어 "원문 파일을 찾지 못했습니다"가 뜹니다. manifest의 `file` 매핑을 쓰지 않는 것이 원인입니다.
3. **추출 캐시 키가 내용 해시가 아니라 길이입니다** (`build_graph.py:131`). `title|len(text)`라서, 길이가 같은 위키 개정은 stale 추출을 재사용합니다. 프롬프트 해시는 포함돼 있으나 본문 내용 해시가 없습니다.
4. **국가명이 시드가 됩니다.** `runs.jsonl`의 `"프랑스에서 노벨상 탄 작가 알려줘"`는 `seeds: ["프랑스"]`로 실행됐습니다. `agent.py:97-98`은 `never` 2개 외에는 타입 필터가 없어 Country/Language도 substring 매칭으로 시드가 됩니다. 브릿지에서 출발한 BFS는 `max_neighbors_per_bridge=12`로 차수순 잘리므로(`agent.py:175-177`), 정답이 잘려나갈 수 있는 구조입니다.
5. **연대 표기를 단년으로 오독합니다.** `_year_lookup`(`agent.py:145`)은 `re.search` 첫 매치만 보므로, `"1990년대 노벨상 수상자"`가 `1990년 수상자`로 답됐습니다(`runs.jsonl` 12:27 두 건). decade/범위 입력은 거절 또는 별도 처리가 필요합니다.
6. **질문 유형과 답 유형이 어긋나도 통과합니다.** `"2024년도 수상작은?"`에 `"2024년도 수상작은 한강입니다"`(사람을 답)로 실행됐습니다(`runs.jsonl` 12:25). `WON_IN_YEAR` 근거가 작품 질문에 그대로 쓰였습니다. answer 프롬프트에 답의 타입 기대가 없습니다.
7. **`requirements.txt`의 절반이 데드 의존성입니다.** `pandas·matplotlib·langchain-core·langchain-openai·langchain-text-splitters`를 import하는 코드가 없습니다(8개 스크립트 전수 확인). 특히 `matplotlib`는 "시각화에 필요"처럼 보이지만 실제 사용처가 없습니다.
8. **`output/runs.jsonl`에 놀이성 쿼리가 섞인 채로 diff에 올라와 있습니다.** `"2023년도 수상작은?"`, `"카뮈도 노벨상 탔어?"`, `"카프카도..."` 같은 수동 탐색 로그가 실행 기록(provenance)과 뒤섞여 있습니다. append 전용 로그를 커밋하는 구조라 노이즈가 계속 쌓입니다. `.gitignore` 또는 로그 분리 검토를 권합니다(현재 `.gitignore`에 `output/`·`runs.jsonl` 관련 규정이 없습니다).

## P2 — 중간 수준 / 기술부채

- `agent.py:179` — 브릿지가 아닌 홉의 `nbrs[:max_nodes_per_hop]`는 정렬 없이 잘라 NetworkX 인접 삽입 순서(≒ 추출 순서)에 의존합니다. 재빌드마다 잘리는 집합이 달라질 수 있습니다.
- `agent.py:364-372` — `used` 되채움 휴리스틱(답변 문장에 등장한 개체 포함 삼중항)은 우연한 언급을 근거로 둔갑시킬 수 있습니다. 폴백임을 `notes`에 남기는 것은 잘돼 있으나, `evidence` 자체에 편입되므로 하류에서 구분이 안 됩니다.
- `app.py:66-73` — 슬라이더가 캐시된 agent의 `tv` dict를 직접 mutate합니다. 질문 간 설정이 누출되고, 원래 config 값으로 복귀가 안 됩니다. 복사본을 쓰는 쪽이 안전합니다. 같은 파일, LLM 키 부재·호출 실패 시 앱 전체가 크래시합니다(에러 핸들링 없음).
- `rag_basic.py:42-53` — 900자 비오버랩 청킹은 문장 절단으로 basic 회수율을 깎아 GraphRAG에 유리한 비대칭을 만듭니다. REPORT 3절의 "회수율이 승패를 가른다"는 결론과 얽혀 있어, 청킹 조건도 함께 명시하는 편이 정직합니다.
- `evaluate.py:29,46-48` — 거절 판정이 거절 문구 부분문자열 매칭이라 프롬프트 문구 변경에 취약합니다. `refused` 플래그를 직접 쓰는 쪽이 낫습니다(현재 basic/agent 모두 `refused`를 반환하므로 가능).
- `build_graph.py:230,253` — `title_pulls`가 `step3` dict를 in-place로 고치고, fuzzy 병합은 O(N²) 전수 비교입니다. 현 규모(수백 노드)는 괜찮지만 타입·초성 블로킹 없이 키우면 위험합니다. `to_graph`(`294-309`)는 같은 이름이 다른 타입으로 등장하면 첫 타입이 이기고 경고가 없습니다.
- `build_graph.py:355`, `verify_goldenset.py:65`, `audit_graph.py:120` 등 — `open()`을 `with` 없이 쓰는 패턴이 전역에 반복됩니다. 예외 시 핸들 누수 + `triples.json` 쓰기 도중 실패 시 파일 잘림 가능.
- `INFLUENCED_BY`는 스키마·프롬프트에는 있으나 추출 0건(`build_report.json`의 `by_relation`에 키 자체가 없음)으로 사실상 데드 관계입니다. 남겨둘 이유(REPORT 2절에 서술됨)는 있으나, config에 "0건" 상태 표기가 없습니다.
- 문서 내부 수치 불일치: REPORT 회고는 "문항 수도 12개""거절 2문항"(§6-④·①)이라 쓰지만 실제 평가셋은 **14문항·거절 3문항**입니다. PLAN.md의 상태 수치("노드 401…GraphRAG 0.97 vs 0.71")도 REPORT(1.00 vs 0.68)와 어긋나 있습니다. P0-2와 같은 뿌리(재실행 후 문서 미갱신)입니다.

## 잘돼 있는 점 (유지 권장)

- 스키마 7종을 프롬프트에 박아 넣고 `never_merge`(부커상/국제 부커상) 근거를 ratio 실측표로 남긴 것. 문자열 거리 함정을 수치로 증명한 대목은 설득력이 있습니다.
- `verify_goldenset.py`의 원문 대조 + `audit_graph.py`의 색인 점검을 파이프라인에 내장한 것. 실패 층 분류(색인/탐색/생성)와 결합돼 디버깅 동선이 명확합니다.
- "좋은 숫자를 먼저 의심"한 기록(경로재현율 한쪽 끝 버그, 띄어쓰기 채점 버그)과 이를 수정한 경위 서술. 평가 코드의 자기유리 바이어스를 공개적으로 다룬 것은 신뢰도를 올립니다.
- `--mermaid`를 컴파일된 그래프에서 직접 뽑아 REPORT 구조도와 코드의 어긋남을 방지한 것. LLM 호출을 `answer` 노드 하나로 격리한 설계도 실패 층 분류의 전제가 됩니다.
- `.cache/extract`로 추출-정제 실험 비용을 0으로 만든 것, 429 대응 백오프와 중단-재개 지원.

## 권장되는 다음 순서

1. 코퍼스 고정: `data/docs/` 85건 중 25건 untracked의去就 결정 → `collect` 재실행 또는 디렉토리 정리 → manifest·`build_report`·그래프·`eval.json`·`index_audit`를 동일 시점에서 재생성 → REPORT·README·PLAN 수치 갱신(Q13 면제 포함).
2. P1 수정: `getsize`→문자 수, 출처 경로 manifest 매핑, 캐시 키 내용 해시, 시드 타입 제한, decade 처리, 수상작/수상자 타입 검증, dead deps 정리, `runs.jsonl` gitignore/분리.
3. P2 정리: BFS 잘림 정렬, `used` 폴백 표식, 슬라이더 복사본, 청킹 조건 명시, 거절 플래그 채점, `WON_IN_YEAR` 면제 2곳.
