#!/usr/bin/env python3
"""전 구간 구동 점검 — 수집부터 답변 생성까지 이어서 돌려 오류 없이 끝나는지 본다.

  python run_e2e.py

각 단계의 종료 코드와 소요 시간을 output/e2e_run.json 에 남긴다.
하나라도 실패하면 종료 코드 1 을 돌려주므로 CI 에 그대로 걸 수 있다.

①만 수 분 걸린다 — 위키백과 API 예절 때문이다(호출 사이 0.6초, 429 면 Retry-After).
이미 받아 둔 문서는 건너뛰므로 두 번째 실행부터는 훨씬 빠르다.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable

STEPS = [
    ("① 코퍼스 수집", [PY, "collect_corpus.py"]),
    ("② 평가셋 자체검사", [PY, "verify_goldenset.py"]),
    ("③ 그래프 구축", [PY, "build_graph.py"]),
    ("③' 색인 점검", [PY, "audit_graph.py"]),
    ("④ 답변 생성", [PY, "agent.py",
                   "파블로 네루다와 같은 나라 출신인 다른 노벨문학상 수상자는?"]),
    ("⑤ 채점 + 대조군", [PY, "evaluate.py", "--repeat", "1"]),
    ("⑥ 데모 적재", [PY, "-c", "import app; print('app.py import OK')"]),
]


def main():
    rows, all_ok = [], True
    for name, cmd in STEPS:
        t0 = time.time()
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
        dt = round(time.time() - t0, 1)
        ok = r.returncode == 0
        all_ok &= ok
        rows.append({"step": name, "cmd": " ".join(cmd[1:]), "exit": r.returncode,
                     "seconds": dt, "ok": ok,
                     "stderr_tail": "" if ok else r.stderr.strip()[-300:]})
        print(f"{'✅' if ok else '❌'} {name:14s} {dt:6.1f}초  exit={r.returncode}")
        if not ok:
            print("   stderr:", r.stderr.strip()[-400:])

    out = {"ran_at": time.strftime("%Y-%m-%d %H:%M:%S"), "all_ok": all_ok,
           "total_seconds": round(sum(x["seconds"] for x in rows), 1), "steps": rows}
    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    json.dump(out, open(os.path.join(HERE, "output", "e2e_run.json"), "w",
                        encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\n{'전 구간 무오류' if all_ok else '실패 있음'} · "
          f"총 {out['total_seconds']}초 → output/e2e_run.json")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
