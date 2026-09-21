#!/usr/bin/env python3
"""전 구간 구동 점검 — 수집부터 답변 생성까지 이어서 돌려 오류 없이 끝나는지 본다.

  python run_e2e.py

각 단계의 종료 코드와 소요 시간을 output/e2e_run.json 에 남긴다.
하나라도 실패하면 종료 코드 1 을 돌려주므로 CI 에 그대로 걸 수 있다.

무엇을 보고 무엇을 보지 않는가
  - 본다: 각 단계가 오류 없이 끝나는가, 그래프가 기준(eval.json 을 만든 그래프)과
          같은가 — graph.graphml 의 sha256 을 기준 성적표에 적힌 것과 비교한다
  - 보지 않는다: ① 의 '재수집' 경로. 코퍼스가 고정돼 있으면 ① 은 위키백과를 치지
          않고 바로 끝난다. 재수집(--refresh)은 네트워크에 기대고 몇 분 걸리며
          결과가 매번 달라져, 연막 점검에 넣지 않았다. 별도로 확인해야 한다.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, ".venv", "bin", "python")
if not os.path.exists(PY):
    PY = sys.executable

# 단계마다 시한을 둔다. LLM 호출이 매달리면 점검 전체가 매달리기 때문이다.
STEPS = [
    ("① 코퍼스 수집", [PY, "collect_corpus.py"], 900),
    ("② 평가셋 자체검사", [PY, "verify_goldenset.py"], 60),
    ("③ 그래프 구축", [PY, "build_graph.py"], 900),
    ("③' 색인 점검", [PY, "audit_graph.py"], 60),
    ("④ 답변 생성", [PY, "agent.py",
                   "파블로 네루다와 같은 나라 출신인 다른 노벨문학상 수상자는?"], 180),
    # --tag 를 붙여 eval_smoke.json 으로 쓴다. 태그가 없으면 기준 성적표인
    # output/eval.json 을 1회 측정치로 덮어써 버린다 (실제로 그런 적이 있다).
    # 1회 측정은 노이즈가 커서 REPORT 에 인용하지 않는다 — 연막용일 뿐이다.
    ("⑤ 채점 + 대조군", [PY, "evaluate.py", "--repeat", "1", "--tag", "smoke"], 600),
    ("⑥ 데모 적재", [PY, "-c", "import app; print('app.py import OK')"], 60),
]


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if os.path.exists(path) else None


def tail(text, n=400):
    return (text or "").strip()[-n:]


def main():
    rows, all_ok = [], True
    for name, cmd, limit in STEPS:
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=limit)
            code, out, err = r.returncode, r.stdout, r.stderr
        except subprocess.TimeoutExpired as e:
            code = "timeout"
            out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = f"{limit}초 안에 끝나지 않았다"
        dt = round(time.time() - t0, 1)
        ok = code == 0
        all_ok &= ok
        # 이 저장소의 스크립트들은 진단을 print(stdout) 로 낸다.
        # 실패 원인을 추적하려면 stderr 만이 아니라 stdout 꼬리도 남겨야 한다.
        rows.append({"step": name, "cmd": " ".join(cmd[1:]), "exit": code,
                     "seconds": dt, "ok": ok,
                     "stdout_tail": "" if ok else tail(out),
                     "stderr_tail": "" if ok else tail(err)})
        print(f"{'✅' if ok else '❌'} {name:14s} {dt:6.1f}초  exit={code}")
        if not ok:
            print("   stdout:", tail(out, 300))
            print("   stderr:", tail(err, 300))

    # 그래프가 기준 성적표를 만든 그래프와 같은가
    graph_sha = sha256(os.path.join(HERE, "output", "graph.graphml"))
    ref_sha = None
    ref_path = os.path.join(HERE, "output", "eval.json")
    if os.path.exists(ref_path):
        ref_sha = json.loads(Path(ref_path).read_text(encoding="utf-8")).get("graph_sha256")
    same = (graph_sha == ref_sha) if ref_sha else None
    if same is False:
        all_ok = False
        print("❌ graph.graphml 이 기준 성적표(eval.json)를 만든 그래프와 다르다 — "
              "REPORT 의 수치가 지금 그래프의 것이 아니다")
    elif same:
        print("✅ 그래프가 기준 성적표를 만든 그래프와 같다 (sha256 일치)")
    else:
        print("ℹ️  eval.json 에 그래프 해시가 없어 대조하지 못했다")

    out = {"ran_at": time.strftime("%Y-%m-%d %H:%M:%S"), "all_ok": all_ok,
           "total_seconds": round(sum(x["seconds"] for x in rows), 1),
           "graph_sha256": graph_sha, "graph_matches_eval": same,
           "steps": rows}
    os.makedirs(os.path.join(HERE, "output"), exist_ok=True)
    Path(os.path.join(HERE, "output", "e2e_run.json")).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'전 구간 무오류' if all_ok else '실패 있음'} · "
          f"총 {out['total_seconds']}초 → output/e2e_run.json")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
