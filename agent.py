#!/usr/bin/env python3
"""③ 시작 개체 찾기 → ④ n홉 확장 → ⑤ 근거만으로 답변 (LangGraph).

  python agent.py "질문"
  python agent.py            # 대화형

LangGraph State 흐름 (REPORT.md 의 구조도와 같아야 한다)
  find_seed -> expand -> [근거 부족이면 widen 으로 되돌아감] -> answer
  widen 을 max_hops 까지 써도 근거가 없으면 '모른다'고 답한다.

반환/기록
  answer · path(실제로 탄 관계 순서) · evidence(삼중항) · sources(문서명)
  실행마다 output/runs.jsonl 에 한 줄씩 append 한다.
"""
raise SystemExit("아직 구현 전 — 주제 확정 후 작성합니다.")
