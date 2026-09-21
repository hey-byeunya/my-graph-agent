#!/usr/bin/env python3
"""프롬프트 회귀 안전망 — answer() 시스템 프롬프트를 고치기 **전에** 돈다.

  python check_prompt_regression.py

REPORT.md 7절 "④ 프롬프트 규칙은 서로 간섭한다"에 적힌 두 사고를 정확히
겨냥한다. `evaluate.py` 의 채점(score_item)은 **정답 문자열이 들어 있는가**만
보므로, 정답은 그대로 맞히면서 엉뚱한 근거로 답의 틀이 새는 것까지는 못
잡는다 — 이 스크립트는 그 틈을 메운다. 전체 평가셋(`evaluate.py --repeat 1`)
을 대신하지 않는다 — 이 두 건 외의 회귀는 여전히 못 잡으므로, 규칙을 새로
추가했다면 전체 평가셋도 함께 돌려야 한다.

사고 ① — WON_IN_YEAR 설명을 항상 넣었더니 연도와 무관한 질문이
        "같은 해에 받은 다른 수상자" 로 답했다 → Q6 으로 감지
사고 ②③ — "질문 종류에 맞는 답을 하라" 가 기존 규칙과 싸워 Q3(데뷔 소설)이
         거절되거나, 단서만 말하고 답을 빼먹었다 → Q3 으로 감지
"""
import os
import sys
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CASES = [
    {
        # 주의: 이 질문은 "찍어도 맞았던" 시절 이후 그래프가 다시 추출되며
        # 골딩의 작품이 파리대왕·통과 의례 둘로 늘어, 어느 쪽이 데뷔작인지는
        # 스키마에 없어 원래 답할 수 없는 질문이 됐다(REPORT.md ③). 그래서
        # 골든셋 채점(파리대왕 고정)은 지금도 0점이 정상이고, 여기서는 그
        # 점수를 다시 묻지 않는다 — 후보를 대고 거절하지 않는지만 본다.
        "id": "Q3 데뷔 소설 — 거절/누락 회귀",
        "question": "윌리엄 골딩의 데뷔 소설은 무엇인가?",
        "must_not_refuse": True,
        "must_contain_any": ["파리대왕", "통과 의례"],
        "guards": "REPORT.md ②③ — '질문 종류에 맞는 답을 하라' 규칙이 "
                  "'핵심 관계만 있으면 답하라' 와 싸워 5/5 거절되거나, "
                  "단서만 말하고 정답 후보를 빼먹은 사고",
    },
    {
        "id": "Q6 부커상 — 연도로 새는 회귀",
        "question": "가즈오 이시구로가 받은 맨부커상을 받은 다른 노벨문학상 수상자는 누구인가?",
        "must_not_refuse": True,
        "must_not_contain": ["같은 해"],
        "guards": "REPORT.md ① — WON_IN_YEAR 설명을 무조건 붙였더니 "
                  "연도와 무관한 이 질문이 '같은 해에 받은 다른 수상자' 로 답한 사고",
    },
]


def run_case(agent, case):
    r = agent.ask(case["question"], log=False)
    answer, refused = r["answer"], r["refused"]
    fails = []

    if case.get("must_not_refuse") and refused:
        fails.append("거절됐다 (must_not_refuse)")
    if "must_contain_any" in case:
        if not any(s in answer for s in case["must_contain_any"]):
            fails.append(f"{case['must_contain_any']} 중 아무것도 답변에 없다")
    if "must_not_contain" in case:
        hit = [s for s in case["must_not_contain"] if s in answer]
        if hit:
            fails.append(f"있으면 안 되는 문구가 있다: {hit}")

    return fails, answer


def main():
    from agent import GraphAgent
    agent = GraphAgent()

    print(f"프롬프트 회귀 케이스 {len(CASES)}건\n")
    all_ok = True
    for case in CASES:
        fails, answer = run_case(agent, case)
        ok = not fails
        all_ok &= ok
        mark = "✅" if ok else "❌"
        print(f"{mark} {case['id']}")
        print(f"   지킴: {case['guards']}")
        print(f"   답변: {answer[:150]}")
        if fails:
            print(f"   실패: {'; '.join(fails)}")
        print()

    if all_ok:
        print("전부 통과 — 이 두 사고는 재발하지 않았다.")
    else:
        print("회귀 발생 — 위 실패 항목을 보고 프롬프트를 다시 확인할 것.")
        print("(주의: 이 스크립트가 못 잡는 다른 회귀도 있을 수 있다 — "
              "규칙을 새로 추가했다면 evaluate.py --repeat 1 --tag <이름> 도 함께 돌릴 것)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
