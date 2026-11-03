"""阶段二接口冒烟测试（真实 HTTP 调用）。

注意：本脚本第 3 步会把 cold-archive 覆盖为 manually_included。
为避免污染后续测试（如 test_forecast_api 的冷系统拒绝用例），
末尾在 try/finally 中还原状态：override 清空 + status 恢复 cold
（override API 无还原为 cold 的入口，故直接改库）。
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8090/api/forecast/v1"


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8"))


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def cleanup_cold_archive():
    """7. 清理：还原 cold-archive 状态，避免污染后续测试。

    手段与此前两次手动还原一致：
    - override_* 字段清空
    - status 恢复为 cold（应用级与 URL 级行）
    override API 只接受 manually_included / manually_excluded，
    无法还原为 cold，故直接改库。
    """
    try:
        import psycopg2
    except Exception as e:  # 无 psycopg2 时跳过（内存模式下进程重启即自然还原）
        print(f"7. 清理跳过（无 psycopg2）: {e}")
        return
    try:
        conn = psycopg2.connect(
            "postgresql://nginxpulse:nginxpulse@127.0.0.1:5432/nginxpulse",
            connect_timeout=5,
        )
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE forecast_eligibility
            SET status='cold',
                override_status=NULL, override_reason=NULL,
                override_by=NULL, override_at=NULL
            WHERE app_name=%s
            """,
            ("cold-archive",),
        )
        conn.commit()
        cur.execute(
            "SELECT app_name, uri_template, status, override_status"
            " FROM forecast_eligibility WHERE app_name=%s",
            ("cold-archive",),
        )
        rows = cur.fetchall()
        conn.close()
        print(f"7. 清理完成：还原 {len(rows)} 行 -> {rows}")
    except Exception as e:
        print(f"7. 清理失败（请手动还原 cold-archive）: {e}")


try:
    # 1. 全量评估
    print("1. 全量评估:", post("/eligibility/evaluate-all", {}))

    # 2. 列表 - 各状态统计
    for status in ["eligible", "cold", "probation", "insufficient_history", "poor_data_quality"]:
        rows = get(f"/eligibility/list?status={status}&limit=100")
        print(f"2. 状态 {status}: {len(rows)} 个")

    # 3. 人工纳入冷系统
    print("3. 人工纳入:", post("/eligibility/override", {
        "level": "app", "app_name": "cold-archive", "uri_template": "",
        "new_status": "manually_included",
        "reason": "重要归档业务双十一需专项预测", "operator": "admin",
    }))

    # 4. 验证纳入后状态
    r = post("/eligibility/evaluate", {"app_name": "cold-archive", "uri_template": ""})
    print(f"4. cold-archive 纳入后状态: {r['status']}, override={r['override_status']}, by={r['override_by']}")

    # 5. 资格历史记录
    hist = get("/eligibility/history?app_name=cold-archive")
    print(f"5. 变化历史: {len(hist)} 条, 最新={hist[0]['new_status'] if hist else 'none'}")

    # 6. 规则查看
    rules = get("/eligibility/rules")
    print(f"6. 规则: lookback={rules['lookback_days']}天, 完整率阈值={rules['min_completeness']}")
finally:
    # 无论测试是否中途失败，都还原状态（避免污染后续测试）
    cleanup_cold_archive()

print("全部接口测试通过 ✓")
