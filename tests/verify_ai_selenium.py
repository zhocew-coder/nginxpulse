#!/usr/bin/env python3
"""端到端验证 /ai 页面的「智能查询」与「异常流量检测」两个功能。

检查点：
1. 智能查询返回后，业务解读 / 运维建议 / 风险提示 区块是否渲染出 LLM 内容
2. 异常检测返回后，风险研判 / 影响面 / 处置建议 是否渲染
3. 界面上是否残留 [object Object] 或裸英文 key（上一轮日报的同类问题）
"""
import os
import sys
import tempfile
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

CHROME = "/opt/chrome-linux64/chrome-linux64/chrome"
DRIVER = "/opt/chrome-linux64/chromedriver"
BASE = "http://127.0.0.1:8088/ai"
PROFILE_ROOT = "/home/joyce/workspace/nginxpulse/.chrome-profiles"

BAD_TOKENS = [
    "[object Object]",
    "business_insight",
    "ops_advice",
    "risk_alerts",
    "highlights",
    "risk_analysis",
    "source_ips",
    "request_count",
    "undefined",
    "NaN",
]


def make_driver():
    """Connect to an already-running chromedriver.

    Letting Selenium spawn chromedriver itself fails here with
    "unhandled request": /tmp and /dev/shm are only 10M, too small for
    chromedriver's own scratch files. Start it manually first:

        chromedriver --port=9515 --allowed-ips=127.0.0.1

    The user-data-dir must also live on a real disk for the same reason.
    """
    # A fresh profile per run: reusing one makes Chrome exit immediately.
    os.makedirs(PROFILE_ROOT, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="p", dir=PROFILE_ROOT)

    opts = Options()
    opts.binary_location = CHROME
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1500,2600")
    opts.add_argument(f"--user-data-dir={profile}")
    return webdriver.Remote(
        command_executor="http://127.0.0.1:9515",
        options=opts,
    )


def scan_bad_tokens(text, label):
    found = [t for t in BAD_TOKENS if t in text]
    print(f"  [{label}] 残留问题 token: {found if found else '无 ✅'}")
    return found


def main():
    driver = make_driver()
    problems = []
    try:
        driver.get(BASE)
        time.sleep(3)

        # ---------- 智能查询 ----------
        print("=== 智能查询 ===")
        clicked = False
        for btn in driver.find_elements(By.CSS_SELECTOR, ".example-button, button.p-button"):
            if "URL" in btn.text or "PV" in btn.text:
                print(f"  点击示例问题: {btn.text}")
                btn.click()
                clicked = True
                break
        if not clicked:
            print("  ! 未找到示例问题按钮")
            problems.append("no example button")

        WebDriverWait(driver, 150).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".query-result"))
        )
        time.sleep(2)

        q = driver.find_element(By.CSS_SELECTOR, ".query-result").text
        print("  --- 渲染文本（前 1200 字）---")
        print("  " + q[:1200].replace("\n", "\n  "))

        for sel, name in [
            (".answer-badge", "AI 标记"),
            (".block-highlight", "关键发现"),
            (".block-business", "业务解读"),
            (".block-ops", "运维建议"),
            (".block-risk", "风险提示"),
        ]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            print(f"  {name}: {'✅ 存在' if els else '❌ 缺失'}")
            if not els:
                problems.append(f"query block missing: {name}")

        problems.extend(scan_bad_tokens(q, "智能查询"))
        driver.save_screenshot("/tmp/np_query.png")
        print("  截图: /tmp/np_query.png")

        # ---------- 异常检测 ----------
        print()
        print("=== 异常流量检测 ===")
        btns = driver.find_elements(By.XPATH, "//button[contains(., '开始检测')]")
        if not btns:
            print("  ! 未找到「开始检测」按钮")
            problems.append("no detect button")
        else:
            btns[-1].click()
            try:
                WebDriverWait(driver, 200).until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, ".anomaly-result, .anomaly-empty")
                    )
                )
            except Exception:
                print("  ! 等待检测结果超时")

        time.sleep(2)
        has_result = bool(driver.find_elements(By.CSS_SELECTOR, ".anomaly-result"))
        if has_result:
            a = driver.find_element(By.CSS_SELECTOR, ".anomaly-result").text
            print("  --- 渲染文本（前 1800 字）---")
            print("  " + a[:1800].replace("\n", "\n  "))

            for sel, name in [
                (".anomaly-judgement", "风险研判/影响面"),
                (".anomaly-actions", "处置建议"),
                (".confidence-tag", "置信度"),
                (".anomaly-evidence-toggle", "原始证据"),
            ]:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
                print(f"  {name}: {'✅ 存在' if els else '❌ 缺失'}")
                if not els:
                    problems.append(f"anomaly block missing: {name}")

            problems.extend(scan_bad_tokens(a, "异常检测"))
        else:
            print("  未发现异常（.anomaly-empty）")
            empty = driver.find_elements(By.CSS_SELECTOR, ".anomaly-empty")
            print(f"  空状态提示: {'✅' if empty else '❌ 缺失'}")
            if not empty:
                problems.append("anomaly empty state missing")

        driver.save_screenshot("/tmp/np_anomaly.png")
        print("  截图: /tmp/np_anomaly.png")

    finally:
        driver.quit()

    print()
    print("=" * 60)
    if problems:
        print("发现问题:", problems)
        sys.exit(1)
    print("全部检查通过 ✅")
    sys.exit(0)


if __name__ == "__main__":
    main()
