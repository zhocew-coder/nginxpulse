"""滚动回测。

需求 §6.3：
  - 按时间顺序滚动回测，**不得随机打乱时间序列**。
  - 指标：MAE、WAPE、sMAPE、预测区间覆盖率、相对基线模型改善程度。
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from .models import build_model, prediction_intervals, seasonal_naive_values


def _mae(y: np.ndarray, yhat: np.ndarray) -> float:
    return float(np.mean(np.abs(y - yhat)))


def _wape(y: np.ndarray, yhat: np.ndarray) -> float:
    denom = float(np.sum(np.abs(y)))
    if denom == 0:
        return float("nan")
    return float(np.sum(np.abs(y - yhat)) / denom)


def _smape(y: np.ndarray, yhat: np.ndarray) -> float:
    denom = np.abs(y) + np.abs(yhat)
    mask = denom > 0
    if not np.any(mask):
        return 0.0
    return float(np.mean(2.0 * np.abs(y[mask] - yhat[mask]) / denom[mask]))


def _coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    inside = (y >= lo) & (y <= hi)
    return float(np.mean(inside)) if len(y) else float("nan")


def rolling_backtest(y: np.ndarray, ts, season: int = 288,
                     horizon: int = 288, folds: int = 3,
                     strategies: List[str] = None) -> Dict[str, dict]:
    """按时间顺序滚动回测多个模型（两趟计算，与 engine.py 口径一致）。

    每折：用 [0, cut) 训练，预测 [cut, cut+horizon)，与实际比较。

    两趟计算：
      第一趟：逐折拟合/预测，得到各折 MAE、WAPE、sMAPE；
      第二趟：用第一趟的多折平均 MAE 作为 model_mae 校准区间，再算覆盖率。
    这样回测覆盖率与线上预测（engine.run_forecast 传 model_mae）用同一口径，
    避免"回测 calib=1.0、线上 calib=model_mae/残差MAE"的口径分裂。
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    strategies = strategies or ["seasonal_naive", "lightgbm"]

    # 需要至少 (folds+1) * horizon 的数据才能滚动
    min_needed = (folds + 1) * horizon
    if n < min_needed:
        folds = max(1, n // horizon - 1)
    if folds < 1:
        return {}

    results: Dict[str, dict] = {}
    for strat in strategies:
        maes, wapes, smapes = [], [], []
        baseline_maes = []
        # 第一趟产物：各折的测试段/预测值/模型样本内残差/训练段
        fold_data: List[dict] = []
        for f in range(folds):
            cut = n - horizon * (folds - f)
            if cut < season * 2:
                continue
            train_y = y[:cut]
            test_y = y[cut:cut + horizon]
            if len(test_y) < horizon:
                continue
            train_ts = ts[:cut] if ts is not None and len(ts) >= cut else None

            model = build_model(strat).fit(train_y, train_ts, season)
            try:
                pred = model.predict(horizon)
            except Exception:
                pred = seasonal_naive_values(train_y, season, horizon)
            pred = np.nan_to_num(pred, nan=float(np.mean(train_y[-season:])))

            maes.append(_mae(test_y, pred))
            wapes.append(_wape(test_y, pred))
            smapes.append(_smape(test_y, pred))

            # 基线：Seasonal Naive
            base_pred = seasonal_naive_values(train_y, season, horizon)
            baseline_maes.append(_mae(test_y, base_pred))

            fold_data.append({
                "train_y": train_y,
                "test_y": test_y,
                "pred": pred,
                "model_resid": model.in_sample_residuals(),
            })

        if not maes:
            continue

        # 第二趟：用第一趟的多折平均 MAE 校准区间宽度，再算覆盖率
        model_mae = float(np.mean(maes))
        covs = []
        for fd in fold_data:
            lo, hi = prediction_intervals(fd["train_y"], fd["pred"], season,
                                          model_mae=model_mae,
                                          model_resid=fd["model_resid"])
            covs.append(_coverage(fd["test_y"], lo, hi))

        mae = model_mae
        base_mae = float(np.mean(baseline_maes)) if baseline_maes else mae
        improvement = None
        if base_mae > 0:
            improvement = round((base_mae - mae) / base_mae, 4)
        results[strat] = {
            "mae": round(mae, 3),
            "wape": round(float(np.nanmean(wapes)), 4),
            "smape": round(float(np.nanmean(smapes)), 4),
            "interval_coverage": round(float(np.nanmean(covs)), 4),
            "baseline_mae": round(base_mae, 3),
            "improvement_vs_baseline": improvement,
            "folds": len(maes),
            "horizon": horizon,
        }
    return results


def select_best_model(backtest: Dict[str, dict]) -> str:
    """按 MAE 选择最优模型；无结果时回退 seasonal_naive。"""
    if not backtest:
        return "seasonal_naive"
    valid = {k: v for k, v in backtest.items()
             if v.get("mae") is not None and np.isfinite(v["mae"])}
    if not valid:
        return "seasonal_naive"
    return min(valid.items(), key=lambda kv: kv[1]["mae"])[0]
