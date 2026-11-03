"""预测模型封装。

实现需求 §6.1 的算法组合：
  - Seasonal Naive：基线对比模型
  - ETS / Holt-Winters：稳定时间序列及周期性
  - SARIMA / SARIMAX：周期性及外生变量
  - LightGBM：多特征（时间特征 + 滞后特征）与活动影响

所有模型统一接口：fit(y, timestamps) -> predict(horizon) -> (point, lower, upper)
失败时回退到 Seasonal Naive，保证服务可用。
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd

# ---- 区间定稿参数（tests/tune_intervals.py 网格搜索结果）----
# 随步长放宽系数：widen = sqrt(min(steps, WIDEN_N_CAP)) * calib * WIDEN_GROW
WIDEN_N_CAP = 16          # 步长增长封顶：16 步后不再放宽（均值回归序列不确定性增长慢）
WIDEN_GROW = 0.28         # 单步放宽幅度
UPPER_RATIO_CAP = 2.5     # 上界硬帽：不超过点预测的 2.5 倍
LOWER_FLOOR = 0.0         # 下界防触零比例（>0 时 lower 不低于 point*LOWER_FLOOR）
CALIB_CLIP = (0.3, 3.0)   # 校准系数裁剪范围


class BaseModel:
    name = "base"

    def fit(self, y: np.ndarray, ts: Optional[pd.Series] = None,
            season: int = 288) -> "BaseModel":
        self.y = np.asarray(y, dtype=float)
        self.ts = ts
        self.season = season
        return self

    def predict(self, horizon: int) -> np.ndarray:
        raise NotImplementedError

    def residuals(self) -> np.ndarray:
        """一步向前预测的残差（用于构建预测区间）。"""
        y = getattr(self, "y", np.array([]))
        if len(y) < 2:
            return np.array([0.0])
        naive = seasonal_naive_values(y, self.season, len(y))
        return y - naive

    def in_sample_residuals(self) -> np.ndarray:
        """模型自身的样本内一步残差（预测区间的基数）。

        优先用模型自身拟合值与实际值之差（需求 §6.2：区间来自模型残差）；
        模型未成功拟合时回退到季节朴素残差。
        """
        return self.residuals()


class SeasonalNaiveModel(BaseModel):
    """Seasonal Naive：用上一周期同刻的值作为预测。"""
    name = "seasonal_naive"

    def predict(self, horizon: int) -> np.ndarray:
        return seasonal_naive_values(self.y, self.season, horizon)


def seasonal_naive_values(y: np.ndarray, season: int, horizon: int) -> np.ndarray:
    """取最后 season 个值循环填充到 horizon 长度。"""
    y = np.asarray(y, dtype=float)
    if len(y) == 0:
        return np.zeros(horizon)
    if season <= 0 or len(y) < season:
        return np.full(horizon, float(np.nanmean(y)) if len(y) else 0.0)
    base = y[-season:]
    reps = int(np.ceil(horizon / season))
    return np.tile(base, reps)[:horizon]


class ETSModel(BaseModel):
    """Holt-Winters 指数平滑（statsmodels ExponentialSmoothing）。"""
    name = "ets"

    def fit(self, y, ts=None, season=288) -> "ETSModel":
        super().fit(y, ts, season)
        self.model = None
        self.fitted = None
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing
            # 季节性周期过大时收敛慢，仅使用最近若干个周期
            max_points = season * 6
            yv = self.y[-max_points:] if len(self.y) > max_points else self.y
            if len(yv) < season * 2:
                # 数据不足以支撑季节模型，退化为无季节
                self.model = ExponentialSmoothing(
                    yv, trend="add", seasonal=None, initialization_method="estimated"
                ).fit(optimized=True)
            else:
                self.model = ExponentialSmoothing(
                    yv, trend="add", seasonal="add", seasonal_periods=season,
                    initialization_method="estimated",
                ).fit(optimized=True)
            self.fitted = self.model
        except Exception:
            self.model = None
            self.fitted = None
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if self.model is None:
            return seasonal_naive_values(self.y, self.season, horizon)
        try:
            return np.asarray(self.model.forecast(horizon), dtype=float)
        except Exception:
            return seasonal_naive_values(self.y, self.season, horizon)

    def in_sample_residuals(self) -> np.ndarray:
        if self.model is None:
            return self.residuals()
        try:
            fitted = np.asarray(self.model.fittedvalues, dtype=float)
            yv = self.y[-len(fitted):] if len(fitted) < len(self.y) else self.y
            return yv - fitted
        except Exception:
            return self.residuals()


class SARIMAModel(BaseModel):
    """SARIMA（statsmodels SARIMAX）。

    5min 粒度下季节周期为 288，完整季节性 SARIMA 极慢，
    因此此处使用低阶 + 显式季节周期，并对大数据量做截断与异常回退。
    活动中带外生变量时可用 SARIMAX（阶段四扩展）。
    """
    name = "sarima"

    def fit(self, y, ts=None, season=288) -> "SARIMAModel":
        super().fit(y, ts, season)
        self.model = None
        try:
            from statsmodels.tsa.statespace.sarimax import SARIMAX
            max_points = season * 4
            yv = self.y[-max_points:] if len(self.y) > max_points else self.y
            if len(yv) < max(season + 2, 10):
                # 数据不足，退化为非季节 ARIMA
                m = SARIMAX(yv, order=(1, 1, 1),
                            enforce_stationarity=False,
                            enforce_invertibility=False)
            else:
                m = SARIMAX(yv, order=(1, 1, 1),
                            seasonal_order=(1, 0, 0, season),
                            enforce_stationarity=False,
                            enforce_invertibility=False)
            self.model = m.fit(disp=False, maxiter=50)
        except Exception:
            self.model = None
        return self

    def predict(self, horizon: int) -> np.ndarray:
        if self.model is None:
            return seasonal_naive_values(self.y, self.season, horizon)
        try:
            return np.asarray(self.model.forecast(horizon), dtype=float)
        except Exception:
            return seasonal_naive_values(self.y, self.season, horizon)

    def in_sample_residuals(self) -> np.ndarray:
        if self.model is None:
            return self.residuals()
        try:
            fitted = np.asarray(self.model.fittedvalues, dtype=float)
            yv = self.y[-len(fitted):] if len(fitted) < len(self.y) else self.y
            return yv - fitted
        except Exception:
            return self.residuals()


class LightGBMModel(BaseModel):
    """LightGBM：时间特征 + 滞后特征（日周期/周周期）。

    对高频（5min）序列比季节统计模型更高效，且天然支持外生特征
    （阶段四的活动特征可直接并入）。
    """
    name = "lightgbm"

    def fit(self, y, ts=None, season=288) -> "LightGBMModel":
        super().fit(y, ts, season)
        self.model = None
        self.last_row = None
        try:
            import lightgbm as lgb
            df = self._build_features(self.y, self.ts, self.season)
            df = df.dropna()
            if len(df) < 50:
                return self
            feature_cols = [c for c in df.columns if c not in ("y",)]
            X = df[feature_cols].values
            yv = df["y"].values
            self.feature_cols = feature_cols
            self.model = lgb.LGBMRegressor(
                n_estimators=200, learning_rate=0.05, num_leaves=31,
                min_child_samples=20, subsample=0.9, colsample_bytree=0.9,
                random_state=42, verbosity=-1, n_jobs=2,
            )
            self.model.fit(X, yv)
            self.last_row = df[feature_cols].iloc[-1].values
        except Exception:
            self.model = None
        return self

    def _build_features(self, y, ts, season):
        n = len(y)
        df = pd.DataFrame({"y": y})
        if ts is None:
            ts = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=n,
                               freq="5min")
        ts = pd.to_datetime(pd.Series(ts)).reset_index(drop=True)
        df["hour"] = ts.dt.hour + ts.dt.minute / 60.0
        df["dow"] = ts.dt.dayofweek
        df["is_weekend"] = (ts.dt.dayofweek >= 5).astype(int)
        # 滞后特征：短期、日周期、周周期
        for lag in (1, 2, 3, season, season * 2, season * 7):
            if n > lag:
                df[f"lag_{lag}"] = pd.Series(y).shift(lag)
        # 滚动统计
        for w in (season, season * 7):
            if n > w:
                df[f"rmean_{w}"] = pd.Series(y).shift(1).rolling(w).mean()
                df[f"rstd_{w}"] = pd.Series(y).shift(1).rolling(w).std()
        return df

    def predict(self, horizon: int) -> np.ndarray:
        if self.model is None or self.last_row is None:
            return seasonal_naive_values(self.y, self.season, horizon)
        try:
            # 递归预测：用预测值滚动填充滞后特征
            preds = []
            buf = list(self.y)
            for step in range(horizon):
                row = self._row_for_step(buf, step)
                pred = float(self.model.predict(row.reshape(1, -1))[0])
                pred = max(pred, 0.0)
                preds.append(pred)
                buf.append(pred)
            return np.asarray(preds)
        except Exception:
            return seasonal_naive_values(self.y, self.season, horizon)

    def in_sample_residuals(self) -> np.ndarray:
        """LightGBM 样本内一步残差（用训练特征的行级预测，非递归多步）。"""
        if self.model is None:
            return self.residuals()
        try:
            df = self._build_features(self.y, self.ts, self.season).dropna()
            if df.empty or "y" not in df.columns:
                return self.residuals()
            X = df[self.feature_cols].values
            fitted = np.asarray(self.model.predict(X), dtype=float)
            return df["y"].values - fitted
        except Exception:
            return self.residuals()

    def _row_for_step(self, buf, step):
        """为第 step 步构造特征行（与 _build_features 列顺序一致）。"""
        season = self.season
        n = len(buf)
        # 时间戳：延续原序列频率推断（用最后一个已知时间 + step）
        if self.ts is not None and len(self.ts) > 0:
            last_ts = pd.to_datetime(pd.Series(self.ts).iloc[-1])
            freq = pd.Timedelta(minutes=5)
            cur = last_ts + freq * (step + 1)
        else:
            cur = pd.Timestamp.now(tz="UTC")
        hour = cur.hour + cur.minute / 60.0
        dow = cur.dayofweek
        is_weekend = int(dow >= 5)
        vals = [hour, dow, is_weekend]
        for lag in (1, 2, 3, season, season * 2, season * 7):
            idx = n - lag
            vals.append(buf[idx] if idx >= 0 else np.nan)
        for w in (season, season * 7):
            if n >= w:
                win = buf[-w:]
                vals.append(float(np.mean(win)))
                vals.append(float(np.std(win)))
        return np.asarray(vals, dtype=float)


def build_model(strategy: str) -> BaseModel:
    return {
        "seasonal_naive": SeasonalNaiveModel,
        "ets": ETSModel,
        "sarima": SARIMAModel,
        "lightgbm": LightGBMModel,
    }.get(strategy, SeasonalNaiveModel)()


def prediction_intervals(y: np.ndarray, point: np.ndarray,
                         season: int = 288,
                         coverage: float = 0.95,
                         model_mae: Optional[float] = None,
                         model_resid: Optional[np.ndarray] = None) -> Tuple[np.ndarray, np.ndarray]:
    """基于一步向前残差的经验分位数构建预测区间。

    注意：区间来自模型残差，不是 LLM 生成（需求 §一 核心设计原则）。

    参数:
        coverage: 标称覆盖率，默认 0.95。
        model_mae: 实际模型的多步 MAE（来自回测），用于校准区间宽度。
        model_resid: 模型自身的样本内残差（优先使用）。
                     若提供则直接用其分位数构建区间，
                     否则回退到季节朴素残差。
    """
    y = np.asarray(y, dtype=float)
    if len(y) < 2:
        return point, point

    # 优先使用模型自身残差，回退到季节朴素残差
    if model_resid is not None and len(model_resid) >= 10:
        resid = np.asarray(model_resid, dtype=float)
        resid = resid[np.isfinite(resid)]
    else:
        naive = seasonal_naive_values(y, season, len(y))
        resid = y - naive
        resid = resid[np.isfinite(resid)]

    if len(resid) < 10:
        scale = float(np.nanstd(np.diff(y))) if len(y) > 1 else 0.0
        return point - scale, point + scale
    alpha = (1.0 - coverage) / 2.0
    lo_q = float(np.quantile(resid, alpha))
    hi_q = float(np.quantile(resid, 1.0 - alpha))

    # 校准系数：模型多步 MAE / 模型残差均值绝对值，裁剪到 [0.3, 3.0]
    # （多步误差通常大于样本内一步残差，用比值把区间宽度校到实测水平）
    resid_mae = float(np.mean(np.abs(resid)))
    calib = 1.0
    if model_mae is not None and resid_mae > 0:
        calib = float(np.clip(model_mae / resid_mae, *CALIB_CLIP))

    # 随预测步长放宽：sqrt(min(steps, 16)) * calib * 0.28
    # 季节性流量序列具有均值回归特征，不确定性增长远慢于随机游走，
    # 16 步后不再继续放宽，避免远端区间过度膨胀。
    steps = np.arange(1, len(point) + 1)
    widen = np.sqrt(np.minimum(steps, WIDEN_N_CAP)) * calib * WIDEN_GROW
    lower = np.maximum(point + lo_q * widen, 0.0)
    upper = np.maximum(point + hi_q * widen, 0.0)
    # 上界硬帽：不超过点预测的 2.5 倍
    upper = np.minimum(upper, point * UPPER_RATIO_CAP)
    # 下界防触零：不低于点预测的 LOWER_FLOOR 倍（实验版机制保留，0 表示不启用）
    if LOWER_FLOOR > 0:
        lower = np.maximum(lower, point * LOWER_FLOOR)
    # lower 不得超过 upper，且保持非负
    lower = np.minimum(lower, upper)
    lower = np.maximum(lower, 0.0)
    return lower, upper
