#!/usr/bin/env python3
"""1단계 — 한국어 위키백과에서 노벨문학상 수상자 코퍼스를 모은다.

  python collect_corpus.py              # config.json 의 시드로 수집
  python collect_corpus.py --target 40  # 목표 건수만 바꿔 빠르게 확인

수집 방식
  MediaWiki API 만 쓴다. HTML 크롤링·파싱은 하지 않는다.
  ① 시드 문서의 본문 링크(prop=links, ns=0) 를 모아, 여러 시드가 함께 가리키는 것부터 줄 세운다
  ② 그 후보 중 시드와 분류(category)를 하나 이상 공유하는 것만 남긴다
  ③ 살아남은 것의 본문만 한 건씩 받는다 (extracts 는 한 번에 한 문서)
  ④ 800자 미만 토막글은 버린다

산출물
  data/docs/<제목>.md      # 제목 · 분류 · 본문
  data/manifest.json       # 시드 · 채택/탈락 건수와 사유 · 저장 목록
"""
import argparse
import json
import os
import re
import sys
import time
from collections import Counter

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://ko.wikipedia.org/w/api.php"
# User-Agent 는 아스키로만 쓴다. 한글을 넣으면 인코딩 오류가 난다.
UA = "my-graph-agent/0.1 (modulabs project; contact: byeunya at gmail dot com)"
PAUSE = 0.6          # 0.3 초로는 429(요청 과다)가 났다
MAX_RETRY = 5

SESSION = requests.Session()
SESSION.headers["User-Agent"] = UA


def _get(params):
    """429·5xx 는 기다렸다 다시 친다. Retry-After 를 주면 그 값을 따른다."""
    for attempt in range(MAX_RETRY):
        r = SESSION.get(API, params=params, timeout=30)
        if r.status_code in (429, 502, 503, 504):
            wait = float(r.headers.get("Retry-After", 2 ** attempt))
            print(f"    … {r.status_code} — {wait:.0f}초 쉬고 재시도 "
                  f"({attempt + 1}/{MAX_RETRY})")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    r.raise_for_status()
    return r


def api(**params):
    """continue 가 있으면 이어 받아 하나의 응답으로 합친다."""
    params.update(format="json", formatversion=2)
    merged = {}
    cont = {}
    while True:
        r = _get({**params, **cont})
        data = r.json()
        for page in data.get("query", {}).get("pages", []):
            slot = merged.setdefault(page["title"], {})
            for key, value in page.items():
                if isinstance(value, list):
                    slot.setdefault(key, []).extend(value)
                else:
                    slot[key] = value
        time.sleep(PAUSE)
        if "continue" not in data:
            return merged
        cont = data["continue"]


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def is_excluded(title, patterns):
    """연도 · 목록 · 틀 · 분류 문서는 후보에서 뺀다."""
    return any(re.search(p, title) for p in patterns)


def get_links(titles):
    """시드 문서들의 본문 링크. 제목 -> 그 문서가 가리키는 링크 목록."""
    out = {}
    for batch in chunks(titles, 20):
        pages = api(
            action="query", prop="links", plnamespace=0, pllimit="max",
            titles="|".join(batch),
        )
        for title, page in pages.items():
            out[title] = [l["title"] for l in page.get("links", [])]
    return out


def get_categories(titles):
    """분류는 20건씩 묶어 받을 수 있다 — 본문보다 먼저 받아 후보를 거른다."""
    out = {}
    for batch in chunks(titles, 20):
        pages = api(
            action="query", prop="categories", cllimit="max", clshow="!hidden",
            titles="|".join(batch),
        )
        for title, page in pages.items():
            out[title] = [
                c["title"].removeprefix("분류:") for c in page.get("categories", [])
            ]
    return out


def get_extract(title):
    """본문. extracts 는 한 번에 한 문서만 받을 수 있다."""
    pages = api(
        action="query", prop="extracts", explaintext=1, exlimit=1, titles=title,
    )
    page = pages.get(title, {})
    return page.get("extract", "")


def save(title, categories, body):
    name = title.replace(" ", "_").replace("/", "_") + ".md"
    path = os.path.join(HERE, "data", "docs", name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n분류: {', '.join(categories)}\n\n{body.strip()}\n")
    return name


def main():
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))["corpus"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=cfg["target_docs"])
    args = ap.parse_args()

    seeds = cfg["seeds"]
    min_chars = cfg["min_chars"]
    excludes = cfg["exclude_patterns"]
    os.makedirs(os.path.join(HERE, "data", "docs"), exist_ok=True)

    print(f"시드 {len(seeds)}건: {', '.join(seeds)}\n")

    # ── ① 시드가 가리키는 2홉 후보. 여러 시드가 함께 가리킨 것부터.
    links = get_links(seeds)
    missing = [s for s in seeds if s not in links or not links[s]]
    if missing:
        print(f"⚠️  링크를 못 받은 시드: {missing}  (제목 표기를 확인하세요)")

    pointed = Counter()
    for targets in links.values():
        for t in set(targets):
            if t not in seeds and not is_excluded(t, excludes):
                pointed[t] += 1

    candidates = [t for t, _ in pointed.most_common()]
    print(f"2홉 후보 {len(candidates)}건 "
          f"(2개 이상 시드가 가리킨 것 {sum(1 for c in pointed.values() if c >= 2)}건)")

    # ── ② 시드와 분류를 하나 이상 공유하는 것만. 본문보다 분류를 먼저 받아 호출 수를 줄인다.
    seed_cats = get_categories(seeds)
    seed_cat_set = {c for cats in seed_cats.values() for c in cats}
    print(f"시드 분류 {len(seed_cat_set)}종")

    # 후보 전부의 분류를 받으면 낭비다. 많이 가리켜진 순서로 필요한 만큼만 훑는다.
    shared, checked, rejected_nocat = [], 0, 0
    scan_limit = max(args.target * 6, 200)
    for batch in chunks(candidates[:scan_limit], 20):
        cats = get_categories(batch)
        for title in batch:
            checked += 1
            if seed_cat_set & set(cats.get(title, [])):
                shared.append(title)
            else:
                rejected_nocat += 1
        if len(shared) >= args.target * 2:
            break
    print(f"분류를 공유한 후보 {len(shared)}건 / 검사 {checked}건 "
          f"(분류 불일치로 탈락 {rejected_nocat}건)\n")

    # ── ③④ 시드 + 살아남은 후보의 본문을 한 건씩. 토막글은 버린다.
    targets = seeds + shared
    all_cats = {**seed_cats}
    saved, stubs, failed = [], [], []

    for title in targets:
        if len(saved) >= args.target and title not in seeds:
            break
        # 중간에 끊겨도 이어 받을 수 있게 이미 저장한 문서는 건너뛴다
        name = title.replace(" ", "_").replace("/", "_") + ".md"
        path = os.path.join(HERE, "data", "docs", name)
        if os.path.exists(path):
            saved.append({"title": title, "file": name,
                          "chars": os.path.getsize(path), "cached": True})
            print(f"  ↺ [{len(saved):2d}] {title} (이미 있음)")
            continue
        try:
            body = get_extract(title)
        except Exception as e:
            failed.append({"title": title, "reason": f"{type(e).__name__}: {e}"})
            print(f"  ✗ {title} — 요청 실패")
            continue
        if len(body) < min_chars:
            stubs.append({"title": title, "chars": len(body)})
            print(f"  · {title} — 토막글 {len(body)}자, 버림")
            continue
        if title not in all_cats:
            all_cats.update(get_categories([title]))
        name = save(title, all_cats.get(title, []), body)
        saved.append({"title": title, "file": name, "chars": len(body)})
        print(f"  ✓ [{len(saved):2d}] {title} ({len(body):,}자)")

    manifest = {
        "source": "한국어 위키백과 (MediaWiki API)",
        "collected_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seeds": seeds,
        "criteria": {
            "채택": "시드가 본문에서 가리키고(2홉), 시드와 분류를 하나 이상 공유하며, 본문 800자 이상",
            "탈락": "연도·목록·틀·분류 문서 / 시드와 분류를 공유하지 않음 / 본문 800자 미만 토막글",
        },
        "counts": {
            "seeds": len(seeds),
            "two_hop_candidates": len(candidates),
            "shared_category": len(shared),
            "rejected_no_shared_category": rejected_nocat,
            "rejected_stub": len(stubs),
            "failed": len(failed),
            "saved": len(saved),
        },
        "rejected_stub": stubs,
        "failed": failed,
        "saved": saved,
    }
    with open(os.path.join(HERE, "data", "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\n저장 {len(saved)}건 → data/docs/  ·  기록 → data/manifest.json")
    if len(saved) < 50:
        print("⚠️  50건 미만입니다. 시드를 늘리거나 --target 을 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
