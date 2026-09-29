#!/usr/bin/env python3
"""s5_drag_residual_test.py — 把修正後密度代回本專案 drag_residual 公式，在本專案 TLE 上檢驗
2024-05 Gannon 磁暴期的誤報（|drag_resid_da| > 0.3 km 物理閘門）與注入式召回。

資料：主資料庫 raw_tle_archive（duckdb read_only）。期間 2024-04-01 ~ 2024-06-30（B_eff 以此期間
中位數校準，與專案「逐衛星自我校準」同法）。
  磁暴窗 STORM：轉換終點落在 [2024-05-08, 2024-05-16)
  平靜窗 QUIET：[2024-04-01, 2024-04-15) ∪ [2024-05-20, 2024-06-03)（週均 Ap < 10）
負樣本（無機動、或真機動遠小於 0.3 km，閘門旗標 = 誤報）：
  RB   火箭殘骸 R/B（sat_n2yo_metadata 名稱含 R/B；近地點 < 750 km、e < 0.02、TLE ≥ 100 筆）
  FS3  FORMOSAT-3 A–F（29047–29052，退役不推進）
  FS7  FORMOSAT-7 1–6（2024-05 精密軌道 SP3 驗證事件皆 < 50 m，fs7_events_2024.csv）
  IDS  IDS/ILRS operator 認證安靜區間內之轉換（ids_quiet.csv）
  GFO  GRACE-FO 1/2（另以 STORM-AI 實測密度做 oracle 上限）
密度變體（s_i = ρ·√(μa)·dt·geom，B_eff = median(−Δa/s)，resid = Δa + B_eff·s）：
  V0   專案原版：單點、日均 Ap、lat=lon=0（AD.drag_residual，不給 line1/2、關 3h ap）
  V1   專案現行：AD.drag_residual 原樣（3h ap + 星下點）
  V1s  V1 但 pymsis 開關 9=−1（修正「3h ap 未生效」的 bug，無 ML）
  V1M  V1 × exp(M1)            （drop-in：只乘比值修正）
  V2   軌道平均 MSIS（開關 9=−1）逐時積分 ∫ρ̄dt（物理改良，無 ML）
  V2M  V2 × exp(M2) 逐時積分    （物理改良 + 比值修正）
  VT   GRACE-FO1 only：STORM-AI 實測軌道平均密度逐時積分（oracle）
召回：對負樣本每一個轉換注入 Δa = ±0.4/±0.5/±1.0 km 的永久階躍（resid_i + m；B_eff 用中位數，
  單點注入不影響），計 |resid+m| > 0.3 的比例（STORM 與 QUIET 分開）。
輸出：out/drag_transitions.parquet、out/drag_fp_summary.csv、out/drag_injection_recall.csv、
      out/drag_model2_fp.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import lightgbm as lgb
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sa_common import DB, MU, OUT, PROJ, RE, sw_features, use_swall  # noqa: E402
sys.path.insert(0, str(PROJ))
import s2_msis_compare as S2  # noqa: E402
from s4_ratio_model import build_X  # noqa: E402

T0, T1 = pd.Timestamp("2024-04-01"), pd.Timestamp("2024-07-01")
STORM = [(pd.Timestamp("2024-05-08"), pd.Timestamp("2024-05-16"))]
QUIET = [(pd.Timestamp("2024-04-01"), pd.Timestamp("2024-04-15")),
         (pd.Timestamp("2024-05-20"), pd.Timestamp("2024-06-03"))]
GATE = 0.3
H_SCALE = 50.0


def in_windows(t, wins):
    t = pd.DatetimeIndex(t)
    m = np.zeros(len(t), bool)
    for a, b in wins:
        m |= (t >= a) & (t < b)
    return m


def pick_sats(con) -> pd.DataFrame:
    df = con.execute("""
        SELECT r.norad_id, count(*) n, median(r.sma_km) a, median(r.eccentricity) e,
               any_value(m.name_en) nm
        FROM raw_tle_archive r LEFT JOIN sat_n2yo_metadata m USING (norad_id)
        WHERE epoch_utc >= ? AND epoch_utc < ? AND r.sma_km IS NOT NULL GROUP BY 1""",
                     [T0, T1]).fetchdf()
    df["hp"] = df["a"] * (1 - df["e"]) - RE
    rb = df[df["nm"].fillna("").str.contains("R/B") & (df["hp"] < 750) & (df["e"] < 0.02) & (df["n"] >= 100)]
    sets = [rb.assign(group="RB")]
    for grp, ids in [("FS3", [29047, 29048, 29049, 29050, 29051, 29052]),
                     ("FS7", [44343, 44349, 44350, 44351, 44353, 44358]),
                     ("GFO", [43476, 43477]),
                     ("IDS", [41240, 46984, 36508, 41335, 43437, 39086, 54754, 46469, 48621])]:
        sets.append(df[df["norad_id"].isin(ids)].assign(group=grp))
    return pd.concat(sets, ignore_index=True)


def load_tle(con, nid) -> pd.DataFrame:
    d = con.execute("SELECT epoch_utc AS epoch, sma_km, eccentricity, inclination_deg, raan_deg, "
                    "line1, line2 FROM raw_tle_archive WHERE norad_id=? AND sma_km IS NOT NULL "
                    "AND epoch_utc >= ? AND epoch_utc < ? ORDER BY epoch_utc", [int(nid), T0, T1]).fetchdf()
    d["epoch"] = pd.to_datetime(d["epoch"], utc=True)
    return d.drop_duplicates("epoch").reset_index(drop=True)


def resid_from_s(da, s):
    ok = np.isfinite(s) & (s > 0) & np.isfinite(da)
    ratios = -da[ok] / s[ok]
    B = float(np.median(ratios[ratios > 0])) if np.any(ratios > 0) else 0.0
    return da + B * s, B


def geom_factor(a0, e0):
    from scipy.special import ive
    z = np.clip(a0 * e0 / H_SCALE, 0.0, 1e6)
    return ive(0, z) + 2.0 * e0 * ive(1, z)


def main():
    AD, sw = use_swall()
    con = duckdb.connect(DB, read_only=True)
    sats = pick_sats(con)
    import os
    if os.environ.get("MAXS"):
        sats = sats.groupby("group").head(int(os.environ["MAXS"])).reset_index(drop=True)
    print("衛星組：", sats.groupby("group").size().to_dict())
    m1 = lgb.Booster(model_file=str(OUT / "model_M1.txt"))
    m2 = lgb.Booster(model_file=str(OUT / "model_M2.txt"))
    q = pd.read_csv(PROJ / "ids_truth_set" / "ids_quiet.csv")
    q.columns = [c.lstrip("﻿") for c in q.columns]
    q["t0"] = pd.to_datetime(q["quiet_start_tai"]) - pd.Timedelta(seconds=37)
    q["t1"] = pd.to_datetime(q["quiet_end_tai"]) - pd.Timedelta(seconds=37)
    truth = pd.read_parquet(HERE / "data" / "density_all.parquet")
    truth = truth[truth["sat"] == "GRACE-FO1"].set_index("t")["rho_true"].sort_index()

    rows = []
    for k, r in sats.iterrows():
        nid, grp = int(r["norad_id"]), r["group"]
        d = load_tle(con, nid)
        if len(d) < 20:
            continue
        # ── V1（專案現行，原樣）與 V0（原版）
        AD._ap3h_cache = None; AD._ap3h_series(str(HERE / "data" / "SW-All.csv"))
        v1 = AD.drag_residual(d, sw)
        AD._ap3h_cache = pd.Series(dtype=float)
        v0 = AD.drag_residual(d[["epoch", "sma_km", "eccentricity"]], sw)
        AD._ap3h_cache = None; AD._ap3h_series(str(HERE / "data" / "SW-All.csv"))
        if v1.empty:
            continue
        a = d["sma_km"].to_numpy(float); e = d["eccentricity"].to_numpy(float)
        t = pd.DatetimeIndex(d["epoch"]).tz_convert(None).as_unit("ns")  # duckdb 回傳 us：asi8/1e9 會差 1000 倍
        dt_s = np.diff(t.asi8) / 1e9
        da = np.diff(a)
        a0, e0 = a[:-1], e[:-1]
        gf = geom_factor(a0, e0)
        shape = np.sqrt(MU * a0) * dt_s * gf          # s_i = ρ · shape
        # ── V1M：P1 單點 × exp(M1)
        Gi = S2.geom_tle(str(nid), nid, t[:-1])       # 以 TLE_i 於 t_i 之幾何（ring + 星下點）
        Gi = S2.add_geom_features(Gi)
        Gi = Gi.set_index("t").reindex(t[:-1].to_numpy()).reset_index().rename(columns={"index": "t"})
        okg = Gi["alt_proj"].notna().to_numpy()
        Gi["rho_P1"] = v1["rho"].to_numpy()
        X1 = build_X(Gi.fillna({"lst0": 0, "ltan": 0, "asc0": False, "lat0": 0}), "P1")
        c1 = np.exp(m1.predict(X1, num_iteration=m1.best_iteration))
        c1[~okg] = 1.0
        s_v1m = v1["rho"].to_numpy() * c1 * shape
        # ── V1s：只修 pymsis 開關 9=−1（讓 3h ap(7) 真正生效），單點、無 ML
        rho_p1s = S2._worker(("P1s", pd.DatetimeIndex(t[:-1]).tz_localize("UTC"),
                              a0 * (1 - e0) - RE, Gi["lat0"].fillna(0).to_numpy(),
                              Gi["lon0"].fillna(0).to_numpy()))
        s_v1s = rho_p1s * shape
        # ── V2 / V2M：逐時軌道平均 MSIS 積分
        hrs = pd.date_range(t[0].floor("h"), t[-1].ceil("h"), freq="h")
        Gh = S2.geom_tle(str(nid), nid, hrs)
        Gh = S2.add_geom_features(Gh)
        tr_ = np.repeat(Gh["t"].to_numpy(), S2.NRING)
        la = np.concatenate(Gh["ring_lat"].to_numpy()); lo = np.concatenate(Gh["ring_lon"].to_numpy())
        al = np.concatenate(Gh["ring_alt"].to_numpy())
        rho2 = S2.run_parallel("P2", pd.DatetimeIndex(tr_), al, la, lo, nproc=24, chunk=4000)
        Gh["rho_P2"] = rho2.reshape(-1, S2.NRING).mean(axis=1)
        X2 = build_X(Gh.drop(columns=["ring_lat", "ring_lon", "ring_alt"]).fillna({"ltan": 0}), "P2")
        Gh["rho_P2M"] = Gh["rho_P2"] * np.exp(m2.predict(X2, num_iteration=m2.best_iteration))
        th = pd.DatetimeIndex(Gh["t"]).as_unit("ns").asi8 / 1e9

        def integ(rho_h):
            """∫_{t_i}^{t_{i+1}} ρ(t) dt（逐時線性內插、1 分鐘步）→ 平均 ρ × dt。"""
            out = np.full(len(dt_s), np.nan)
            ts = t.asi8 / 1e9
            for i in range(len(dt_s)):
                g = np.arange(ts[i], ts[i + 1], 600.0)
                if len(g) == 0:
                    continue
                out[i] = np.interp(g, th, rho_h).mean() * dt_s[i]
            return out
        s_v2 = integ(Gh["rho_P2"].to_numpy()) * np.sqrt(MU * a0) * gf
        s_v2m = integ(Gh["rho_P2M"].to_numpy()) * np.sqrt(MU * a0) * gf
        res = {"V0": v0["drag_resid_da"].to_numpy(), "V1": v1["drag_resid_da"].to_numpy()}
        res["V1s"], _ = resid_from_s(da, s_v1s)
        res["V1M"], _ = resid_from_s(da, s_v1m)
        res["V2"], _ = resid_from_s(da, s_v2)
        res["V2M"], _ = resid_from_s(da, s_v2m)
        if nid == 43476:
            tt = truth[(truth.index >= t[0] - pd.Timedelta(hours=2)) & (truth.index <= t[-1] + pd.Timedelta(hours=2))]
            if len(tt) > 100:
                rt = np.interp(th, tt.index.as_unit("ns").asi8 / 1e9, tt.to_numpy())
                s_vt = integ(rt) * np.sqrt(MU * a0) * gf
                res["VT"], _ = resid_from_s(da, s_vt)
        # ── 驗證：自寫 resid 與 AD.drag_residual 一致（V1）
        chk, _ = resid_from_s(da, v1["rho"].to_numpy() * shape)
        assert np.nanmax(np.abs(chk - res["V1"])) < 1e-6, "重算與專案 drag_residual 不一致"
        # Model 2 其他物理通道（與 ml_model2_anomaly.physical_residuals 同式）
        from ml_model2_anomaly import _ang, _j2_raan, _FLOOR
        inc = d["inclination_deg"].to_numpy(float); raan = d["raan_deg"].to_numpy(float)
        z_di = np.diff(inc) / _FLOOR["z_di"]
        z_de = np.diff(e) / _FLOOR["z_de"]
        z_draan = (_ang(raan[:-1], raan[1:]) - _j2_raan(a0, e0, inc[:-1], dt_s)) / _FLOOR["z_draan"]
        tend = t[1:]
        D = pd.DataFrame({"norad_id": nid, "name": r["nm"], "group": grp, "t_from": t[:-1], "t_to": tend,
                          "dt_h": dt_s / 3600, "da_km": da, "alt_p": a0 * (1 - e0) - RE,
                          "z_di": z_di, "z_de": z_de, "z_draan": z_draan,
                          **{f"resid_{k_}": v for k_, v in res.items()}})
        D["storm"] = in_windows(tend, STORM)
        D["quiet"] = in_windows(tend, QUIET)
        if grp == "IDS":
            qq = q[q["norad"] == nid]
            inq = np.zeros(len(D), bool)
            for _, w in qq.iterrows():
                inq |= (D["t_from"] >= w["t0"]) & (D["t_to"] <= w["t1"])
            D["in_ids_quiet"] = inq
        rows.append(D)
        if (k + 1) % 10 == 0:
            print(f"  ...{k+1}/{len(sats)}", flush=True)
    con.close()
    T = pd.concat(rows, ignore_index=True)
    if "in_ids_quiet" in T:
        T = T[(T["group"] != "IDS") | (T["in_ids_quiet"] == True)]  # noqa: E712
    T.to_parquet(OUT / "drag_transitions.parquet", index=False)
    summarize(T)


def summarize(T: pd.DataFrame):
    V = [c.replace("resid_", "") for c in T.columns if c.startswith("resid_")]
    rows = []
    for grp in ["RB", "FS3", "FS7", "IDS", "GFO", "ALL_neg"]:
        g = T if grp == "ALL_neg" else T[T["group"] == grp]
        if grp == "ALL_neg":
            g = g[g["group"].isin(["RB", "FS3", "FS7", "IDS"])]
        for win in ["storm", "quiet"]:
            w = g[g[win]]
            r = {"group": grp, "window": win, "n_sats": w["norad_id"].nunique(), "n_trans": len(w)}
            for v in V:
                x = w[f"resid_{v}"].to_numpy()
                ok = np.isfinite(x)
                r[f"FP_{v}"] = int((np.abs(x[ok]) > GATE).sum())
                r[f"FP0.2_{v}"] = int((np.abs(x[ok]) > 0.2).sum())
                r[f"FP0.1_{v}"] = int((np.abs(x[ok]) > 0.1).sum())
                r[f"FPsat_{v}"] = int(w.loc[np.abs(w[f"resid_{v}"]) > GATE, "norad_id"].nunique())
                r[f"p95abs_{v}"] = float(np.nanpercentile(np.abs(x), 95)) if ok.any() else np.nan
                r[f"medresid_{v}"] = float(np.nanmedian(x)) if ok.any() else np.nan
            rows.append(r)
    S = pd.DataFrame(rows)
    S.to_csv(OUT / "drag_fp_summary.csv", index=False, encoding="utf-8-sig")
    pd.set_option("display.width", 250)
    print("\n=== |drag_resid_da| > 0.3 km 誤報數（轉換數）===")
    print(S[["group", "window", "n_sats", "n_trans"] + [f"FP_{v}" for v in V]].to_string(index=False))
    print("（敏感度：門檻 0.2 km）"); print(S[["group", "window"] + [f"FP0.2_{v}" for v in V]].to_string(index=False))
    print("（敏感度：門檻 0.1 km）"); print(S[["group", "window"] + [f"FP0.1_{v}" for v in V]].to_string(index=False))
    print(S[["group", "window"] + [f"p95abs_{v}" for v in V]].round(3).to_string(index=False))
    print(S[["group", "window"] + [f"medresid_{v}" for v in V]].round(3).to_string(index=False))
    # 注入召回
    rows = []
    neg = T[T["group"].isin(["RB", "FS3", "FS7", "IDS"])]
    for win in ["storm", "quiet"]:
        w = neg[neg[win]]
        for m in [-1.0, -0.5, -0.4, 0.4, 0.5, 1.0]:
            r = {"window": win, "inject_km": m, "n": len(w)}
            for v in [x for x in V if x != "VT"]:
                x = w[f"resid_{v}"].to_numpy() + m
                r[f"recall_{v}"] = float(np.mean(np.abs(x[np.isfinite(x)]) > GATE))
            rows.append(r)
    R = pd.DataFrame(rows)
    R.to_csv(OUT / "drag_injection_recall.csv", index=False, encoding="utf-8-sig")
    # Model 2（部署中之 IsolationForest）在各密度變體下之誤報
    import joblib
    m2 = joblib.load(PROJ / "Orbital_Maneuver_V2" / "models_meme_anomaly" / "model2.pkl")
    iso = m2["model"]
    rows = []
    for grp in ["RB", "FS3", "FS7", "IDS", "GFO"]:
        for win in ["storm", "quiet"]:
            w = T[(T["group"] == grp) & T[win]]
            if not len(w):
                continue
            r = {"group": grp, "window": win, "n_trans": len(w)}
            for v in V:
                X = np.column_stack([w[f"resid_{v}"].to_numpy() / 0.10, w["z_di"], w["z_de"], w["z_draan"]])
                okx = np.isfinite(X[:, 0])
                X = np.clip(np.nan_to_num(X[okx]), -200, 200)
                r[f"M2flag_{v}"] = int((iso.predict(X) == -1).sum()) if len(X) else 0
            rows.append(r)
    M2 = pd.DataFrame(rows)
    M2.to_csv(OUT / "drag_model2_fp.csv", index=False, encoding="utf-8-sig")
    print("\n=== Model 2（IsolationForest）旗標數 ===")
    print(M2.to_string(index=False))
    print("\n=== 注入 Δa 階躍召回（負樣本每轉換各注入一次）===")
    print(R.round(3).to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--summary":
        summarize(pd.read_parquet(OUT / "drag_transitions.parquet"))
    else:
        main()
