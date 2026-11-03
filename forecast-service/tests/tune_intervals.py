"""FAIL-01 区间宽度调参实验（离线脚本，非 pytest 用例）。

目标（docs/forecast/acceptance-regression.md）：
1. backtest 实际覆盖率落在 [0.90, 0.95]
2. width/pt = (upper-lower)/point：中期（24 步）< 2.0，远端（48 步）< 3.0
3. lower_bound=0 的点占比明显下降（理想 < 50%）

口径：
- coverage：滚动回测窗口（48 步），区间在折内用训练段的模型样本内残差构建
- 宽度/触零：最终预测（全量拟合 → 48 步），区间用全量模型残差构建
- 逐对象统计，FAIL-01 主对象 std-crm

用法：USE_MOCK=true python tests/tune_intervals.py
"""
from __future__ import annotations

import itertools
import os
import sys
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.forecast import dataset  # noqa: E402
from app.forecast.backtest import rolling_backtest, select_best_model  # noqa: E402
from app.forecast.models import build_model, seasonal_naive_values  # noqa: E402

HORIZON = 48
SEASON = 288
FOLDS = 3
PRIMARY = "std-crm"
OBJECTS = ["std-crm", "core-payment", "std-loan", "batch-settlement", "std-report"]


def intervals_cfg(point: np.ndarray, resid: np.ndarray, *,
                  coverage: float, n_cap: float, grow_scale: float,
                  ratio_cap: float, lower_floor: float,
                  calib: float = 1.0,
                  legacy_widen: bool = False) -> Tuple[np.ndarray, np.ndarray]:
    """候选区间实现。

    - legacy_widen=True 复刻旧口径：sqrt(steps) 无上限
    - 否则：sqrt(min(steps, n_cap)) * calib * grow_scale
      calib 为对象自适应系数（回测多步 MAE / 样本内残差 MAE）
    """
    point = np.asarray(point, dtype=float)
    resid = np.asarray(resid, dtype=float)
    resid = resid[np.isfinite(resid)]
    if len(resid) < 10:
        return point, point
    alpha = (1.0 - coverage) / 2.0
    lo_q = float(np.quantile(resid, alpha))
    hi_q = float(np.quantile(resid, 1.0 - alpha))
    steps = np.arange(1, len(point) + 1)
    if legacy_widen:
        widen = np.sqrt(steps) * grow_scale
    else:
        widen = np.sqrt(np.minimum(steps, n_cap)) * calib * grow_scale
    lower = np.maximum(point + lo_q * widen, 0.0)
    upper = np.maximum(point + hi_q * widen, 0.0)
    if np.isfinite(ratio_cap):
        upper = np.minimum(upper, point * ratio_cap)
    if lower_floor > 0:
        lower = np.maximum(lower, point * lower_floor)
    lower = np.minimum(lower, upper)
    lower = np.maximum(lower, 0.0)
    return lower, upper


def wpt_stats(pt: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> Dict[str, float]:
    with np.errstate(divide="ignore", invalid="ignore"):
        wpt = (hi - lo) / np.maximum(pt, 1e-9)
    mask = pt > 1e-9
    return {
        "wpt24": float(np.mean(wpt[:24][mask[:24]])) if mask[:24].any() else 0.0,
        "wpt48": float(np.mean(wpt[-1:][mask[-1:]])) if mask[-1:].any() else 0.0,
        "wpt_all": float(np.mean(wpt[mask])) if mask.any() else 0.0,
        "over2": float(np.mean(wpt[mask] > 2.0)) if mask.any() else 0.0,
        "zero": float(np.mean(lo <= 0)),
    }


def prepare() -> List[dict]:
    packs = []
    for app_name in OBJECTS:
        series = dataset.load_series(app_name, "", "5m")
        if series.empty or len(series) < SEASON * 4:
            print(f"  [skip] {app_name}")
            continue
        y = series["value"].to_numpy(dtype=float)
        ts = series["timestamp"]
        bt = rolling_backtest(y, ts, season=SEASON,
                              horizon=min(HORIZON, SEASON), folds=FOLDS,
                              strategies=["seasonal_naive", "lightgbm"])
        chosen = select_best_model(bt)

        folds = []
        n = len(y)
        for f in range(FOLDS):
            cut = n - HORIZON * (FOLDS - f)
            if cut < SEASON * 2:
                continue
            train_y, test_y = y[:cut], y[cut:cut + HORIZON]
            if len(test_y) < HORIZON:
                continue
            m = build_model(chosen).fit(train_y, ts[:cut], SEASON)
            pred = np.asarray(m.predict(HORIZON), dtype=float)
            pred = np.nan_to_num(pred, nan=float(np.mean(train_y[-SEASON:])))
            pred = np.maximum(pred, 0.0)
            folds.append({
                "test_y": test_y, "pred": pred,
                "resid_model": m.in_sample_residuals(),
                "resid_naive": train_y - seasonal_naive_values(train_y, SEASON, len(train_y)),
            })

        m = build_model(chosen).fit(y, ts, SEASON)
        point = np.asarray(m.predict(HORIZON), dtype=float)
        point = np.nan_to_num(point, nan=float(np.mean(y[-SEASON:])))
        point = np.maximum(point, 0.0)
        resid_model = m.in_sample_residuals()
        # 对象自适应校准：回测多步 MAE / 模型样本内残差 MAE（engine 已有 model_mae）
        bt_mae = (bt.get(chosen) or {}).get("mae") or 0.0
        insample_mae = float(np.mean(np.abs(resid_model))) or 1.0
        calib_obj = max(bt_mae / insample_mae, 0.3) if bt_mae else 1.0
        packs.append({
            "app": app_name, "y": y, "point": point, "folds": folds,
            "resid_model": resid_model,
            "resid_naive": y - seasonal_naive_values(y, SEASON, len(y)),
            "model": chosen, "calib": calib_obj, "ts": ts,
        })
        rm, rn = packs[-1]["resid_model"], packs[-1]["resid_naive"]
        print(f"  [ok] {app_name}: 模型={chosen} "
              f"模型残差std={rm.std():.1f} 朴素残差std={rn.std():.1f} "
              f"点预测均值={point.mean():.1f} 自适应calib={calib_obj:.2f}")
    return packs


def eval_cfg(cfg: dict, pack: dict, source: str) -> Dict[str, float]:
    """source: model（自适应 calib）| model_nocalib | naive"""
    calib = pack["calib"] if source == "model" else 1.0
    covs = []
    for fd in pack["folds"]:
        resid = fd["resid_model"] if source.startswith("model") else fd["resid_naive"]
        lo, hi = intervals_cfg(fd["pred"], resid, calib=calib, **cfg)
        covs.append(float(np.mean((fd["test_y"] >= lo) & (fd["test_y"] <= hi))))
    resid = pack["resid_model"] if source.startswith("model") else pack["resid_naive"]
    lo, hi = intervals_cfg(pack["point"], resid, calib=calib, **cfg)
    st = wpt_stats(pack["point"], lo, hi)
    st["coverage"] = float(np.mean(covs)) if covs else float("nan")
    return st


def main() -> None:
    print("=" * 92)
    print("FAIL-01 区间调参实验（模型残差 vs 朴素残差 × 增长/帽参数）")
    print("=" * 92)
    packs = prepare()
    if not packs:
        return

    def show(cfg, source, tag):
        print(f"\n-- {tag} (source={source}) --")
        for p in packs:
            st = eval_cfg(cfg, p, source)
            print(f"   {p['app']:>18}: cov={st['coverage']:.4f} "
                  f"wpt@24={st['wpt24']:.2f} wpt@48={st['wpt48']:.2f} "
                  f">2倍={st['over2']:.1%} zero={st['zero']:.1%}")

    # 基线：当前生产口径（朴素残差 + sqrt 无上限）
    show(dict(coverage=0.95, n_cap=1e9, grow_scale=1.0, ratio_cap=np.inf,
              lower_floor=0.0), "naive", "基线A：朴素残差+sqrt无上限(=任务前口径)")
    # 基线：并发改动口径（朴素残差 + log 增长，用 grow_scale=1、n_cap 模拟）
    print("\n-- 基线B：朴素残差 + log增长(1+0.15*ln h)（当前文件里的并发改动）--")
    for p in packs:
        covs, w_mid, w_far, zeros = [], [], [], []
        for fd in p["folds"]:
            pt, res = fd["pred"], fd["resid_naive"]
            lo_q, hi_q = np.quantile(res, [0.025, 0.975])
            w = 1 + 0.15 * np.log(np.arange(1, len(pt) + 1))
            lo, hi = np.maximum(pt + lo_q * w, 0), np.maximum(pt + hi_q * w, 0)
            covs.append(float(np.mean((fd["test_y"] >= lo) & (fd["test_y"] <= hi))))
        pt, res = p["point"], p["resid_naive"]
        lo_q, hi_q = np.quantile(res, [0.025, 0.975])
        w = 1 + 0.15 * np.log(np.arange(1, len(pt) + 1))
        lo, hi = np.maximum(pt + lo_q * w, 0), np.maximum(pt + hi_q * w, 0)
        st = wpt_stats(pt, lo, hi)
        print(f"   {p['app']:>18}: cov={np.mean(covs):.4f} "
              f"wpt@24={st['wpt24']:.2f} wpt@48={st['wpt48']:.2f} "
              f">2倍={st['over2']:.1%} zero={st['zero']:.1%}")

    # 网格：模型残差 × 覆盖标称 × 增长 × 帽
    print("\n3. 网格搜索（模型残差；判定 std-crm cov∈[0.90,0.95] & w@24<2.0 & w@48<3.0 & zero<50%）")
    coverages = [0.88, 0.90, 0.925, 0.95]
    grow_scales = [0.2, 0.3, 0.4, 0.5, 0.6, 0.8]
    n_caps = [8, 12, 16, 24]
    ratio_caps = [2.5, 3.0, np.inf]
    floors = [0.0, 0.1]

    good, near = [], []
    for cov, gs, ncap, rcap, fl in itertools.product(
            coverages, grow_scales, n_caps, ratio_caps, floors):
        cfg = dict(coverage=cov, n_cap=ncap, grow_scale=gs,
                   ratio_cap=rcap, lower_floor=fl)
        stats = {p["app"]: eval_cfg(cfg, p, "model") for p in packs}
        prim = stats[PRIMARY]
        others_ok = all(s["coverage"] >= 0.85 for a, s in stats.items() if a != PRIMARY)
        ok = (0.90 <= prim["coverage"] <= 0.95 and prim["wpt24"] < 2.0
              and prim["wpt48"] < 3.0 and prim["zero"] < 0.5 and others_ok)
        row = (cfg, prim, stats)
        good.append(row) if ok else near.append(row)

    print(f"   全达标组合数：{len(good)}")

    def key(row):
        _, prim, stats = row
        others_cov = np.mean([s["coverage"] for a, s in stats.items() if a != PRIMARY])
        return (abs(prim["coverage"] - 0.925), abs(others_cov - 0.925),
                prim["wpt24"] + prim["wpt48"], prim["zero"])

    rows = sorted(good, key=key) if good else sorted(
        [r for r in near if 0.88 <= r[1]["coverage"] <= 0.97], key=key)
    print(f"\n4. {'达标 Top 12' if good else '候选 Top 12'}：")
    print(f"   {'cov标':>5} {'grow':>5} {'ncap':>5} {'R':>5} {'floor':>5} | "
          f"{'cov':>6} {'w@24':>6} {'w@48':>6} {'>2倍':>6} {'zero':>6} | 其余cov均值")
    for cfg, prim, stats in rows[:12]:
        others = np.mean([s["coverage"] for a, s in stats.items() if a != PRIMARY])
        print(f"   {cfg['coverage']:>5} {cfg['grow_scale']:>5} {cfg['n_cap']:>5} "
              f"{str(cfg['ratio_cap']):>5} {cfg['lower_floor']:>5} | "
              f"{prim['coverage']:>6.4f} {prim['wpt24']:>6.2f} {prim['wpt48']:>6.2f} "
              f"{prim['over2']:>6.1%} {prim['zero']:>6.1%} | {others:.4f}")

    if rows:
        cfg = rows[0][0]
        print(f"\n5. 建议定稿：coverage={cfg['coverage']} grow_scale={cfg['grow_scale']} "
              f"n_cap={cfg['n_cap']} ratio_cap={cfg['ratio_cap']} "
              f"lower_floor={cfg['lower_floor']}")
        show(cfg, "model", "逐对象明细")

    # 6. 候选默认参数对比 + 24h（288 步）远端覆盖率复核
    print("\n6. 候选默认参数对比（含 24h/288 步覆盖率复核）：")
    candidates = [
        ("A cov0.925/g0.3/N16", dict(coverage=0.925, grow_scale=0.3, n_cap=16,
                                     ratio_cap=2.5, lower_floor=0.0)),
        ("B cov0.95/g0.3/N16", dict(coverage=0.95, grow_scale=0.3, n_cap=16,
                                    ratio_cap=2.5, lower_floor=0.0)),
        ("C cov0.95/g0.4/N12", dict(coverage=0.95, grow_scale=0.4, n_cap=12,
                                    ratio_cap=2.5, lower_floor=0.0)),
        ("D cov0.95/g0.35/N16", dict(coverage=0.95, grow_scale=0.35, n_cap=16,
                                     ratio_cap=2.5, lower_floor=0.0)),
    ]
    for tag, cfg in candidates:
        print(f"   [{tag}]")
        covs48, covs288 = [], []
        for p in packs:
            st = eval_cfg(cfg, p, "model")
            # 24h 远端：整段 288 步误差是否落在区间内（用末 288 步历史做对照折）
            h288_cov = []
            n = len(p["y"])
            for f in range(2):
                cut = n - 288 * (2 - f)
                if cut < SEASON * 2:
                    continue
                tr, te = p["y"][:cut], p["y"][cut:cut + 288]
                m = build_model(p["model"]).fit(tr, p["ts"][:cut], SEASON)
                pred = np.maximum(np.nan_to_num(
                    m.predict(288), nan=float(tr[-SEASON:].mean())), 0)
                lo, hi = intervals_cfg(pred, m.in_sample_residuals(),
                                       calib=p["calib"], **cfg)
                h288_cov.append(float(np.mean((te >= lo) & (te <= hi))))
            cov288 = float(np.mean(h288_cov)) if h288_cov else float("nan")
            covs48.append(st["coverage"])
            covs288.append(cov288)
            print(f"      {p['app']:>18}: cov48={st['coverage']:.4f} "
                  f"cov288={cov288:.4f} w@24={st['wpt24']:.2f} "
                  f"w@48={st['wpt48']:.2f} zero={st['zero']:.1%}")
        print(f"      汇总: cov48均值={np.mean(covs48):.4f} "
              f"cov288均值={np.nanmean(covs288):.4f}")


if __name__ == "__main__":
    main()
