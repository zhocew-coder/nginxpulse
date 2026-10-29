#!/usr/bin/env python3
"""端到端验证 /ai 页面的「智能查询」与「异常流量检测」。

通过 Chrome DevTools Protocol 驱动真实浏览器（headless Chrome 156）。

为什么不直接用 Selenium：Selenium 4.51 在本机会话建立后发送命令时，
chromedriver 156 统一返回 "unhandled request"（/tmp 与 /dev/shm 均只有 10M，
且 Selenium 的 BiDi 探测与 chromedriver 不兼容）。CDP 直连绕开 chromedriver，
依然是在真实 Chrome 中渲染、点击、等待与截图。

前置：先启动带调试端口的 Chrome
    chrome --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage \\
           --remote-debugging-port=9222 --user-data-dir=<大磁盘目录> about:blank
"""
import base64
import json
import sys
import time
import urllib.parse
import urllib.request

import websocket

CDP_HOST = "http://127.0.0.1:9222"
PAGE = "http://127.0.0.1:8088/ai"

BAD_TOKENS = [
    "[object Object]",
    "business_insight",
    "ops_advice",
    "risk_alerts",
    "highlights",
    "risk_analysis",
    "source_ips",
    "request_count",
    "confidence",
    "undefined",
    "NaN",
]

_mid = 0


def new_tab(url):
    req = urllib.request.Request(
        f"{CDP_HOST}/json/new?{urllib.parse.quote(url, safe='')}", method="PUT"
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


class CDP:
    def __init__(self, ws_url):
        self.ws = websocket.create_connection(ws_url, timeout=300)
        self.mid = 0

    def send(self, method, params=None):
        self.mid += 1
        mid = self.mid
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def evaluate(self, expr, await_promise=False):
        r = self.send(
            "Runtime.evaluate",
            {
                "expression": expr,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        return r.get("result", {}).get("value")

    def screenshot(self, path):
        r = self.send("Page.captureScreenshot", {"format": "png"})
        data = base64.b64decode(r["data"])
        with open(path, "wb") as f:
            f.write(data)
        return path

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


# JS: 点击并等待某个选择器出现
JS_CLICK_AND_WAIT = """
(async () => {
  const btnSel = %s, waitSel = %s, timeout = %d;
  const btns = [...document.querySelectorAll(btnSel)];
  const btn = btns.find(b => b.offsetParent !== null);
  if (!btn) return {ok:false, why:'button not found: ' + btnSel};
  btn.click();
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (document.querySelector(waitSel)) return {ok:true, ms: Date.now()-t0};
    await new Promise(r => setTimeout(r, 500));
  }
  return {ok:false, why:'timeout waiting ' + waitSel};
})()
"""

JS_TEXT = """
(() => {
  const el = document.querySelector(%s);
  if (!el) return null;
  return el.innerText;
})()
"""

JS_HAS = """
(() => document.querySelectorAll(%s).length)()
"""


def main():
    tab = new_tab(PAGE)
    print(f"tab: {tab.get('id')}  {tab.get('url')}")
    cdp = CDP(tab["webSocketDebuggerUrl"])
    problems = []
    try:
        cdp.send("Page.enable")
        cdp.send("Runtime.enable")
        time.sleep(4)  # 等首屏 Vue 挂载

        # ---------- 智能查询 ----------
        print("\n=== 智能查询 ===")
        res = cdp.evaluate(
            JS_CLICK_AND_WAIT % (
                repr(".example-button, .query-examples button"),
                repr(".query-result"),
                120000,
            ),
            await_promise=True,
        )
        print("  点击结果:", res)
        if not res or not res.get("ok"):
            problems.append(f"query click failed: {res}")

        time.sleep(2)
        q = cdp.evaluate(JS_TEXT % repr(".query-result")) or ""
        print("  --- 渲染文本（前 1500 字）---")
        print("  " + (q[:1500].replace("\n", "\n  ") or "(空)"))

        for sel, name in [
            (".answer-badge", "AI 标记"),
            (".block-highlight", "关键发现"),
            (".block-business", "业务解读"),
            (".block-ops", "运维建议"),
            (".block-risk", "风险提示"),
        ]:
            n = cdp.evaluate(JS_HAS % repr(sel)) or 0
            print(f"  {name}: {'✅ 存在' if n else '❌ 缺失'}")
            if not n:
                problems.append(f"query block missing: {name}")

        found = [t for t in BAD_TOKENS if t in q]
        print(f"  [智能查询] 残留问题 token: {found if found else '无 ✅'}")
        problems.extend(found)

        # ---------- 异常检测 ----------
        print("\n=== 异常流量检测 ===")
        res = cdp.evaluate(
            """
            (async () => {
              const btns = [...document.querySelectorAll('button')];
              const btn = btns.filter(b => b.textContent.includes('开始检测')).pop();
              if (!btn) return {ok:false, why:'no detect button'};
              btn.click();
              const t0 = Date.now();
              while (Date.now() - t0 < 180000) {
                if (document.querySelector('.anomaly-result, .anomaly-empty')) {
                  return {ok:true, ms: Date.now()-t0};
                }
                await new Promise(r => setTimeout(r, 500));
              }
              return {ok:false, why:'timeout'};
            })()
            """,
            await_promise=True,
        )
        print("  点击结果:", res)
        if not res or not res.get("ok"):
            problems.append(f"anomaly click failed: {res}")

        time.sleep(2)
        has_result = cdp.evaluate(JS_HAS % repr(".anomaly-result")) or 0
        if has_result:
            a = cdp.evaluate(JS_TEXT % repr(".anomaly-result")) or ""
            print("  --- 渲染文本（前 2000 字）---")
            print("  " + (a[:2000].replace("\n", "\n  ") or "(空)"))

            for sel, name in [
                (".anomaly-judgement", "风险研判/影响面"),
                (".anomaly-actions", "处置建议"),
                (".confidence-tag", "置信度"),
                (".anomaly-evidence-toggle", "原始证据"),
            ]:
                n = cdp.evaluate(JS_HAS % repr(sel)) or 0
                print(f"  {name}: {'✅ 存在 ({n})' if n else '❌ 缺失'}")
                if not n:
                    problems.append(f"anomaly block missing: {name}")

            found = [t for t in BAD_TOKENS if t in a]
            print(f"  [异常检测] 残留问题 token: {found if found else '无 ✅'}")
            problems.extend(found)
        else:
            empty = cdp.evaluate(JS_HAS % repr(".anomaly-empty")) or 0
            print(f"  未发现异常，空状态: {'✅' if empty else '❌'}")
            if not empty:
                problems.append("anomaly empty state missing")

        shot = cdp.screenshot("/tmp/np_ai_verify.png")
        print(f"\n  截图: {shot} ({len(open(shot,'rb').read())} bytes)")

    finally:
        cdp.close()

    print("\n" + "=" * 60)
    if problems:
        print("发现问题:", problems)
        sys.exit(1)
    print("全部检查通过 ✅")
    sys.exit(0)


if __name__ == "__main__":
    main()
