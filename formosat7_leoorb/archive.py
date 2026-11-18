"""展開 leoOrb 每日 tar 包並解析成 DataFrame。

每日包內約 274 個 SP3-c 檔，每檔是一個**短弧**（126-129 個 epoch × 60 s，
約 2.1 小時）。同一顆星一天有 42-59 個弧段，相鄰弧段大幅重疊（約 4 重）。
重疊不是雜訊 —— 它正是重疊一致性（0.25 m 3D RMS）的來源，見 merge.py。

解析一律走 repo 根目錄的 sp3_core（單位與時制的坑集中在那裡處理）。
"""

from __future__ import annotations

import logging
import re
import tarfile
from pathlib import Path
from typing import Iterator, Optional, Tuple

import numpy as np
import pandas as pd

from sp3_core import parse_sp3_lines

from .satmap import norad_for_sp3, sp3_for_arc_index

log = logging.getLogger(__name__)

#: 地球重力常數 (km^3/s^2)
MU_EARTH_KM3_S2 = 398600.4418

#: IERS 地球自轉角速度 (rad/s)
OMEGA_EARTH_RAD_S = 7.292115e-5

#: leoOrb_2026.229.001.01_0001.0001_sp3
_ARC_NAME_RE = re.compile(
    r"leoOrb_(?P<year>\d{4})\.(?P<doy>\d{3})\.(?P<sat>\d{3})\.(?P<arc>\d+)"
    r"_(?P<a>\d+)\.(?P<b>\d+)_sp3$"
)


def parse_arc_filename(name: str) -> Optional[dict]:
    """從 SP3 成員檔名取出年/年積日/衛星序號/弧段序號。不符格式回傳 None。"""
    m = _ARC_NAME_RE.search(Path(name).name)
    if not m:
        return None
    d = m.groupdict()
    return {
        "year": int(d["year"]),
        "doy": int(d["doy"]),
        "sat_index": d["sat"],
        "arc_index": d["arc"],
        "arc_id": "%s.%s.%s.%s" % (d["year"], d["doy"], d["sat"], d["arc"]),
    }


def iter_sp3_members(tar_path: Path | str) -> Iterator[Tuple[str, list]]:
    """逐一產出 tar 內的 SP3 成員 (檔名, 文字行 list)。"""
    with tarfile.open(tar_path) as tf:
        for m in tf.getmembers():
            if not m.isfile():
                continue
            fh = tf.extractfile(m)
            if fh is None:
                continue
            text = fh.read().decode("ascii", "replace")
            yield m.name, text.splitlines()


def load_leoorb_tar(tar_path: Path | str,
                    keep_unmapped: bool = True) -> pd.DataFrame:
    """解析單日 tar，回傳所有弧段串成的長表。

    欄位：arc_id, sat_index, sp3_sat, norad_id, epoch(UTC),
          x_km, y_km, z_km, vx_dm_s, vy_dm_s, vz_dm_s, clk_us

    epoch 已由 sp3_core 依 %c 表頭（leoOrb 為 GPS）換算為真 UTC。
    速度**維持 SP3 原始的 dm/s**，換算請用 add_velocity_km_s()。
    """
    frames = []
    n_members = n_skipped = 0
    for name, lines in iter_sp3_members(tar_path):
        n_members += 1
        meta = parse_arc_filename(name)
        if meta is None:
            log.debug("檔名不符 leoOrb 弧段格式，略過：%s", name)
            n_skipped += 1
            continue
        df = parse_sp3_lines(lines)
        if df.empty:
            n_skipped += 1
            continue
        df["arc_id"] = meta["arc_id"]
        df["sat_index"] = meta["sat_index"]
        # sp3_sat 由 SP3 的 P 記錄直接得到；再與檔名序號交叉核對
        expected = sp3_for_arc_index(meta["sat_index"])
        seen = set(df["sp3_sat"].unique())
        if expected is not None and seen != {expected}:
            log.warning("%s：檔名序號 %s 應為 %s，但 P 記錄是 %s",
                        name, meta["sat_index"], expected, sorted(seen))
        df["norad_id"] = df["sp3_sat"].map(norad_for_sp3)
        frames.append(df)

    if not frames:
        raise ValueError("tar 內沒有可解析的 leoOrb 弧段：%s" % tar_path)

    out = pd.concat(frames, ignore_index=True)
    if not keep_unmapped:
        out = out[out["norad_id"].notna()].copy()
    log.info("%s：成員 %d、可用弧段 %d、略過 %d、資料點 %d",
             Path(tar_path).name, n_members, len(frames), n_skipped, len(out))
    cols = ["arc_id", "sat_index", "sp3_sat", "norad_id", "epoch",
            "x_km", "y_km", "z_km", "vx_dm_s", "vy_dm_s", "vz_dm_s", "clk_us"]
    return out[[c for c in cols if c in out.columns]].sort_values(
        ["sp3_sat", "epoch", "arc_id"]).reset_index(drop=True)


def add_velocity_km_s(df: pd.DataFrame) -> pd.DataFrame:
    """加上 vx_km_s/vy_km_s/vz_km_s（**地固**速度）。dm/s -> km/s 除以 10000。"""
    out = df.copy()
    for a in ("x", "y", "z"):
        out["v%s_km_s" % a] = out["v%s_dm_s" % a] / 10000.0
    return out


def add_inertial_velocity(df: pd.DataFrame) -> pd.DataFrame:
    """加上 vx_eci_km_s 等 —— 慣性速度，但仍以 ITRF 軸表示：v_i = v_ecef + ω⊕ × r。

    SP3 的 V 記錄是地固速度。漏掉 ω⊕ × r 的後果：以 vis-viva 反算半長軸會低
    約 736 km（軌道完全錯誤），而程式不會報錯。
    """
    out = df if "vx_km_s" in df.columns else add_velocity_km_s(df)
    out = out.copy()
    r = out[["x_km", "y_km", "z_km"]].to_numpy(float)
    v = out[["vx_km_s", "vy_km_s", "vz_km_s"]].to_numpy(float)
    omega = np.array([0.0, 0.0, OMEGA_EARTH_RAD_S])
    v_eci = v + np.cross(omega, r)
    for i, a in enumerate(("x", "y", "z")):
        out["v%s_eci_km_s" % a] = v_eci[:, i]
    return out


def sanity_check(df: pd.DataFrame) -> pd.DataFrame:
    """來源文件第 3.2 節建議的自我檢核。

    |v_ECI| 應接近 sqrt(mu/|r|)（近圓軌）。若得到約 7.11 而非約 7.57 km/s，
    就是漏了 ω⊕ × r。回傳逐星彙總。
    """
    d = add_inertial_velocity(df)
    r = np.linalg.norm(d[["x_km", "y_km", "z_km"]].to_numpy(float), axis=1)
    v_ecef = np.linalg.norm(d[["vx_km_s", "vy_km_s", "vz_km_s"]].to_numpy(float), axis=1)
    v_eci = np.linalg.norm(d[["vx_eci_km_s", "vy_eci_km_s", "vz_eci_km_s"]].to_numpy(float), axis=1)
    circ = np.sqrt(MU_EARTH_KM3_S2 / r)
    d = d.assign(r_km=r, v_ecef_km_s=v_ecef, v_eci_km_s=v_eci,
                 v_circular_km_s=circ,
                 rel_err_pct=100.0 * (v_eci - circ) / circ)
    return d.groupby("sp3_sat").agg(
        n=("epoch", "size"),
        arcs=("arc_id", "nunique"),
        r_km=("r_km", "mean"),
        v_ecef=("v_ecef_km_s", "mean"),
        v_eci=("v_eci_km_s", "mean"),
        v_circ=("v_circular_km_s", "mean"),
        rel_err_pct=("rel_err_pct", "mean"),
    ).round(4)
