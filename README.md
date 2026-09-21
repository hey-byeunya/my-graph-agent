# my-graph-agent

문서 더미에서 지식 그래프를 만들고, 멀티홉 질문에 **근거와 탄 경로를 함께** 답하는 GraphRAG 에이전트.

주제: _TBD_

## 실행 방법

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # OPENAI_API_KEY 를 채웁니다
```

```bash
python build_graph.py       # 문서 -> output/graph.graphml
python agent.py "질문"       # 멀티홉 답변 + 경로
python evaluate.py          # 홉 수별 채점 + basic RAG 대조
streamlit run app.py        # 데모 화면
```

## 디렉토리

```
data/       docs/ (원본 문서) · goldenset.json (평가셋)
config.json 도메인에 묶인 값 (노드·관계·반경·상한)
output/     graph.graphml · runs.jsonl · eval.json
REPORT.md   제출용 보고서
```

> `.env` 는 커밋하지 않습니다.
