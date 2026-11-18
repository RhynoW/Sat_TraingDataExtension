"""重疊弧段的一致性檢核與合併 —— 把每日 tar 的短弧變成單一真值序列。

leoOrb 每顆星每天有 42-59 個獨立解算的 2.1 小時短弧，相鄰弧段大幅重疊
（約 4 重）。同一 epoch 因此有多個獨立解，兩兩相減即得**內部一致性**。

重疊點的定義（與來源文件第 5.1 節一致，已逐星驗證吻合）::

    重疊點數 = sum over epochs of (k - 1) = 總點數 - 相異 epoch 數

即每個 epoch 取 k-1 個獨立差分（各弧段減去該 epoch 的第一個弧段）。

精度 vs 準度
------------
重疊一致性量的是**精度**（precision），不是**準度**（accuracy）。
系統性誤差（框架實現、力模型共同偏差）在弧段互減時會抵銷，不會出現在這裡，
所以真實誤差 >= 此處算出的值。

另注意：兩個獨立解差分的變異數是單解的 2 倍，所以差分 RMS 約為單解 sigma 的
sqrt(2) 倍。本模組回報**差分 RMS**（與來源文件同口徑，偏保守側）；
要換算單解 sigma 請自行除以 sqrt(2)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .archive import add_inertial_velocity

_POS = ["x_km", "y_km", "z_km"]
_VEL_ECI = ["vx_eci_km_s", "vy_eci_km_s", "vz_eci_km_s"]


def overlap_residuals(df: pd.DataFrame) -> pd.DataFrame:
    """逐星逐 epoch 的弧段間差分，投影到 RIC。

    回傳欄位：sp3_sat, epoch, arc_id, R_m, I_m, C_m, d3_m（單位公尺）。
    每個 epoch 產生 k-1 列（各弧段減去該 epoch 的第一個弧段）。
    """
    d = add_inertial_velocity(df).sort_values(
        ["sp3_sat", "epoch", "arc_id"]).reset_index(drop=True)
    g = d.groupby(["sp3_sat", "epoch"], sort=False)

    P = d[_POS].to_numpy(float)
    V = d[_VEL_ECI].to_numpy(float)
    ref = g[_POS].transform("first").to_numpy(float)
    is_first = g.cumcount().to_numpy() == 0

    D = (P - ref) * 1000.0                       # 公尺
    r_hat = P / np.linalg.norm(P, axis=1, keepdims=True)
    h = np.cross(P, V)
    c_hat = h / np.linalg.norm(h, axis=1, keepdims=True)
    i_hat = np.cross(c_hat, r_hat)

    out = pd.DataFrame({
        "sp3_sat": d["sp3_sat"].to_numpy(),
        "epoch": d["epoch"].to_numpy(),
        "arc_id": d["arc_id"].to_numpy(),
        "R_m": (D * r_hat).sum(1),
        "I_m": (D * i_hat).sum(1),
        "C_m": (D * c_hat).sum(1),
    })
    out["d3_m"] = np.linalg.norm(out[["R_m", "I_m", "C_m"]].to_numpy(), axis=1)
    return out[~is_first].reset_index(drop=True)


def overlap_summary(df: pd.DataFrame) -> pd.DataFrame:
    """逐星彙總重疊一致性 RMS（公尺）。欄位對應來源文件第 5.1 節表格。"""
    res = overlap_residuals(df)
    rms = lambda x: float(np.sqrt(np.mean(np.square(x))))
    rows = []
    for sat, g in res.groupby("sp3_sat"):
        rows.append({
            "sp3_sat": sat,
            "arcs": int(df.loc[df["sp3_sat"] == sat, "arc_id"].nunique()),
            "overlap_pts": len(g),
            "R_rms_m": rms(g["R_m"]),
            "I_rms_m": rms(g["I_m"]),
            "C_rms_m": rms(g["C_m"]),
            "d3_rms_m": rms(g["d3_m"]),
        })
    return pd.DataFrame(rows).set_index("sp3_sat").round(3)


def merge_arcs(df: pd.DataFrame, method: str = "mean") -> pd.DataFrame:
    """把重疊弧段併成每顆星每 epoch 一列的真值序列。

    method : "mean"（預設，對重疊解取平均）或 "median"（對離群較穩健）。

    回傳欄位：sp3_sat, norad_id, epoch, x_km, y_km, z_km,
              vx_km_s, vy_km_s, vz_km_s（**地固**速度）, n_arcs
    """
    if method not in ("mean", "median"):
        raise ValueError("method 只能是 'mean' 或 'median'，收到 %r" % (method,))
    d = df.copy()
    for a in ("x", "y", "z"):
        col = "v%s_km_s" % a
        if col not in d.columns:
            d[col] = d["v%s_dm_s" % a] / 10000.0

    val_cols = _POS + ["vx_km_s", "vy_km_s", "vz_km_s"]
    g = d.groupby(["sp3_sat", "epoch"], sort=True)
    out = getattr(g[val_cols], method)().reset_index()
    out["n_arcs"] = g.size().to_numpy()
    nid = d.groupby("sp3_sat")["norad_id"].first()
    out["norad_id"] = out["sp3_sat"].map(nid)
    return out[["sp3_sat", "norad_id", "epoch"] + val_cols + ["n_arcs"]]


def resample(merged: pd.DataFrame, step_minutes: int = 5) -> pd.DataFrame:
    """把 60 秒節奏的真值序列抽稀到指定間隔（來源文件用 5 分鐘）。

    只做**挑點**不做內插 —— 內插會在真值裡引入模型假設。

    !! epoch 不落在整分上。leoOrb 的 SP3 標記是整分的 GPS 時，換算成 UTC 後
    變成 HH:MM:42（2026 年 GPS-UTC = 18 s）。所以不能直接對 Unix 秒取模，
    要先取出資料自身的秒偏移。
    """
    sec = step_minutes * 60
    ts = pd.to_datetime(merged["epoch"], utc=True).astype("int64") // 10**9
    if len(ts) == 0:
        return merged.reset_index(drop=True)
    offset = int(ts.mod(60).mode().iloc[0])          # 例如 42
    keep = ts.sub(offset).mod(sec) == 0
    return merged[keep.to_numpy()].reset_index(drop=True)
