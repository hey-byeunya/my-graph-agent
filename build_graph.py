#!/usr/bin/env python3
"""① 추출 + ② 정제·병합 — 문서 더미에서 지식 그래프를 만든다.

  python build_graph.py            # data/docs/*.md -> output/graph.graphml
  python build_graph.py --limit 5  # 적은 문서로 빠르게 확인

단계
  1. 로드      data/docs/*.md 를 읽는다
  2. 추출      config.json 의 스키마(노드 타입·관계)로 제한해 LLM 이 삼중항을 뽑는다
  3. 정규화    표기 통일 · 별칭 병합(rapidfuzz) · 일반명사 노드 제외
  4. 저장      output/graph.graphml + output/triples.json
               (정규화 전후 건수를 찍어 병합이 뭘 지웠는지 남긴다)
"""
raise SystemExit("아직 구현 전 — 주제 확정 후 작성합니다.")
