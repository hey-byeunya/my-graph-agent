#!/usr/bin/env python3
"""데모 화면 캡처 — README·REPORT 에 넣을 그림을 재현 가능하게 만든다.

먼저 데모를 띄워 두고 (다른 터미널에서):
    streamlit run app.py --server.port 8502

그리고:
    pip install playwright && playwright install chromium   # 이 스크립트에만 필요
    python make_screenshots.py

두 장을 찍는다 — 답한 경우와 거절한 경우. 거절 화면이 있어야
'근거가 없을 때 지어내지 않는다' 를 그림으로 보일 수 있다.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
URL = os.environ.get("DEMO_URL", "http://localhost:8502")

SHOTS = [
    ("demo-answer.png",
     "하뤼 마르틴손과 같은 나라 출신인 다른 노벨문학상 수상자가 쓴 작품을 하나 들어라.",
     "🔗 근거 삼중항"),
    ("demo-refusal.png",
     "한강과 윌리엄 포크너가 함께 작업한 작품은 무엇인가?",
     None),
]


def main():
    from playwright.sync_api import sync_playwright

    os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1150},
                                device_scale_factor=2)
        for name, question, tab in SHOTS:
            page.goto(URL, wait_until="networkidle")
            page.wait_for_selector("input[aria-label='질문']", timeout=30000)
            page.fill("input[aria-label='질문']", question)
            page.get_by_role("button", name="물어보기").click()
            # 거절 문항은 widen 까지 돌아 훨씬 오래 걸린다. 스피너가 사라질 때까지
            # 기다려야 로딩 중 화면을 찍지 않는다.
            spinner = page.get_by_text("그래프를 타는 중")
            try:
                spinner.wait_for(state="visible", timeout=10000)
            except Exception:
                pass
            spinner.wait_for(state="hidden", timeout=120000)
            page.get_by_role("tab", name="탄 경로").wait_for(timeout=30000)
            page.wait_for_timeout(1500)
            if tab:
                page.get_by_role("tab", name=tab).click()
                page.wait_for_timeout(800)
            out = os.path.join(HERE, "docs", name)
            page.screenshot(path=out, full_page=True)
            print(f"  저장 → docs/{name}")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
