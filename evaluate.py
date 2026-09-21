#!/usr/bin/env python3
"""홉 수별 측정 + basic RAG 대조.

  python evaluate.py           # data/goldenset.json -> output/eval.json

측정
  - 정답 일치      기대 정답 대비 (채점 기준은 REPORT.md 에 사전 정의)
  - 경로 재현율    기대 경로의 관계가 실제 근거에 얼마나 들어왔는가
  - 대조군         BM25 basic RAG 같은 문항 같은 채점
  - 홉 수별로 갈라 보고한다 (평균 하나로 뭉치지 않는다)

실패 분류
  색인(추출 때 삼중항이 없었다) · 탐색(그래프엔 있는데 못 탔다) · 생성(근거는 맞는데 답이 틀렸다)
"""
raise SystemExit("아직 구현 전 — 주제 확정 후 작성합니다.")
