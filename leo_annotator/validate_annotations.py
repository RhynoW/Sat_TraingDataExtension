"""
validate_annotations.py
========================
從 annotations_leo_full.csv 分層隨機取 100 顆衛星，
用 DuckDB TLE 資料（2026-05-01~2026-05-22）偵測軌道機動，
驗證推進系統標註是否與偵測結果一致。
"""

import argparse
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

# ── 設定 ─────────────────────────────────────────────────────────────────────
_HERE       = Path(__file__).parent
DB_PATH     = r"C:\STK_Python\CCIT_Orbit_Maneuvers\GCP_Version\space_db.duckdb"
ANN_PATH    = str(_HERE / "output" / "annotations_leo_full.csv")
OUT_CSV     = str(_HERE / "output" / "validation_full.csv")
OUT_REPORT  = str(_HERE / "output" / "validation_report_full.txt")

DATE_START  = "2026-05-01"
DATE_END    = "2026-05-27"
SEED        = 42

# 機動偵測閾值（與 detect_maneuvers.py 一致）
THR_DA_SM  = 1.0    # km  – 最小有效機動
THR_DI     = 0.02   # deg
THR_DE     = 0.001
THR_DRAAN  = 0.1    # deg – J2 校正後殘差

J2 = 1.08263e-3
RE = 6378.137     # km
MU = 398600.4418  # km³/s²

# P2：neg_streak 連續下降門檻（無 B* 時用 5，高阻力衛星用 3）
_STREAK_NORM  = 5
_STREAK_BSTAR = 3
_DROP_NORM    = 5.0   # km
_DROP_BSTAR   = 3.0   # km
_NET_NORM     = -3.0  # km
_NET_BSTAR    = -2.0  # km


def adaptive_thr_da(sma_km: float) -> float:
    """P2：高度自適應 Δa 閾值（低軌噪聲大 → 2 km；高軌噪聲小 → 0.5 km）"""
    alt_km = sma_km - RE
    if alt_km < 400:
        return 2.0
    elif alt_km > 600:
        return 0.5
    return THR_DA_SM


# ── 輔助函式 ─────────────────────────────────────────────────────────────────

def j2_raan_rate_deg_s(sma_km: float, ecc: float, inc_deg: float) -> float:
    """J2 引起的 RAAN 進動率 (deg/s)"""
    n = np.sqrt(MU / sma_km ** 3)
    p = sma_km * (1 - ecc ** 2)
    return np.degrees(-1.5 * J2 * (RE / p) ** 2 * n * np.cos(np.radians(inc_deg)))


def angle_diff(a: float, b: float) -> float:
    """有號角度差，範圍 (-180, 180]"""
    d = (a - b) % 360.0
    return d - 360.0 if d > 180.0 else d


def detect_maneuvers_for_sat(
    df: pd.DataFrame,
    use_p1: bool = True,   # da_monotonic_decay suppression
    use_p2: bool = True,   # adaptive threshold
    use_p3: bool = True,   # B* auxiliary condition
) -> pd.DataFrame:
    """
    輸入：單顆衛星的 TLE DataFrame（須含 epoch_dt, sma_km, eccentricity,
                                       inclination_deg, raan_deg；可選 bstar）
    輸出：每對相鄰 TLE 的轉移指標 DataFrame

    改進：
      P1 — da_monotonic_decay 排除器：連續單調下降視為大氣阻力，抑制 da 旗標
      P2 — adaptive_thr_da()：依軌道高度調整 Δa 閾值
      P3 — B* 輔助條件：高阻力係數衛星放寬 monotone_decay 判定門檻

    參數：
      use_p1 — 啟用 P1 單調衰減抑制（預設 True）
      use_p2 — 啟用 P2 高度自適應閾值（預設 True；False 則用固定 THR_DA_SM）
      use_p3 — 啟用 P3 B* 輔助放寬門檻（預設 True）
    """
    df = df.sort_values("epoch_dt").reset_index(drop=True)
    rows = []
    for i in range(1, len(df)):
        prev, curr = df.iloc[i - 1], df.iloc[i]
        dt_s = (curr["epoch_dt"] - prev["epoch_dt"]).total_seconds()
        if dt_s <= 0 or dt_s > 86400 * 7:
            continue

        da        = float(curr["sma_km"]) - float(prev["sma_km"])
        di        = float(curr["inclination_deg"]) - float(prev["inclination_deg"])
        de        = float(curr["eccentricity"]) - float(prev["eccentricity"])
        draan_raw = angle_diff(float(curr["raan_deg"]), float(prev["raan_deg"]))
        raan_j2   = j2_raan_rate_deg_s(
            float(prev["sma_km"]), float(prev["eccentricity"]), float(prev["inclination_deg"])
        ) * dt_s
        draan_res = draan_raw - raan_j2
        thr_da = adaptive_thr_da(float(prev["sma_km"])) if use_p2 else THR_DA_SM  # P2

        flagged = (
            abs(da)        > thr_da    or
            abs(di)        > THR_DI    or
            abs(de)        > THR_DE    or
            abs(draan_res) > THR_DRAAN
        )
        rows.append({
            "t_from":        prev["epoch_dt"],
            "t_to":          curr["epoch_dt"],
            "dt_h":          round(dt_s / 3600, 2),
            "da_km":         round(da, 3),
            "di_deg":        round(di, 5),
            "de":            round(de, 6),
            "draan_res_deg": round(draan_res, 4),
            "thr_da":        round(thr_da, 2),
            "flagged":       flagged,
        })

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)

    # ── P1 + P3：單調衰減偵測 ─────────────────────────────────────────────────
    da_vals    = result["da_km"].values
    net_da     = float(da_vals.sum())
    total_drop = -net_da if net_da < 0 else 0.0

    neg_streak = cur = 0
    for v in da_vals:
        if v < -0.3:
            cur += 1
            neg_streak = max(neg_streak, cur)
        else:
            cur = 0

    # P3：高 B* + 低軌 → 放寬 neg_streak / drop / net 門檻
    bstar_boost = False
    if use_p3 and "bstar" in df.columns and df["bstar"].notna().any():
        bstar_mean  = float(df["bstar"].dropna().mean())
        bstar_boost = (bstar_mean > 0.0005 and float(df["sma_km"].mean()) < RE + 450)

    s_thr = _STREAK_BSTAR if bstar_boost else _STREAK_NORM
    d_thr = _DROP_BSTAR   if bstar_boost else _DROP_NORM
    n_thr = _NET_BSTAR    if bstar_boost else _NET_NORM

    # P1 判斷「是否為單調衰減」（無論 use_p1 如何都先計算，後面需要 monotone_with_spike 判斷）
    monotone_decay = (neg_streak >= s_thr and total_drop > d_thr and net_da < n_thr)

    # monotone_with_spike：P1 本來要抑制，但同時有 ≥2 次正向 da 跳動
    # 代表「主動降軌 + 偶發軌道維持」，不應被 P1 抑制
    thr_da_mean = adaptive_thr_da(float(df["sma_km"].mean())) if use_p2 else THR_DA_SM
    pos_da_spikes = int((result["da_km"] > thr_da_mean).sum())
    monotone_with_spike = monotone_decay and (pos_da_spikes >= 2)

    if use_p1 and monotone_decay and not monotone_with_spike:
        # P1：抑制 da 觸發的旗標；保留 di / de / draan 旗標
        result["flagged"] = (
            (result["di_deg"].abs()        > THR_DI)    |
            (result["de"].abs()            > THR_DE)    |
            (result["draan_res_deg"].abs() > THR_DRAAN)
        )

    result["monotone_suppressed"]  = monotone_decay and not monotone_with_spike
    result["monotone_with_spike"]  = monotone_with_spike
    return result


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main() -> None:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="LEO 標註驗證 (P1–P4 可控)")
    parser.add_argument("--disable-p2", action="store_true", help="停用 P2 自適應閾值（固定用 THR_DA_SM）")
    parser.add_argument("--disable-p3", action="store_true", help="停用 P3 B* 輔助條件")
    parser.add_argument("--out-suffix", default="", metavar="STR",
                        help="輸出檔名後綴，例如 _p1only → validation_full_p1only.csv")
    args = parser.parse_args()

    use_p2 = not args.disable_p2
    use_p3 = not args.disable_p3

    out_csv    = OUT_CSV.replace(".csv", f"{args.out_suffix}.csv")       if args.out_suffix else OUT_CSV
    out_report = OUT_REPORT.replace(".txt", f"{args.out_suffix}.txt")    if args.out_suffix else OUT_REPORT

    cfg_label = (
        f"P1=ON  P2={'ON' if use_p2 else 'OFF'}  P3={'ON' if use_p3 else 'OFF'}"
    )
    print(f"[設定] {cfg_label}  out_suffix='{args.out_suffix}'")

    # ── 1. 載入標註 ───────────────────────────────────────────────────────────
    ann = pd.read_csv(ANN_PATH, dtype=str, encoding="utf-8-sig")
    ann["norad_id"] = ann["norad_id"].str.strip()
    print(f"標註總數: {len(ann)} 筆")
    print(f"推進分布:\n{ann['propulsion_class'].value_counts().to_string()}\n")

    # ── 2. 全量（不取樣）────────────────────────────────────────────────────────
    sampled_norads = ann["norad_id"].tolist()
    sample_ann     = ann.set_index("norad_id")
    print(f"全量處理 {len(sampled_norads)} 顆")

    # ── 3. 查詢 DuckDB TLE ────────────────────────────────────────────────────
    # norad_id 在 DuckDB 可能是 INTEGER 或 VARCHAR，統一轉成整數列表
    try:
        norad_ints = [int(n) for n in sampled_norads]
    except ValueError:
        norad_ints = sampled_norads

    norad_sql = ", ".join(str(n) for n in norad_ints)

    print(f"連線 DuckDB: {DB_PATH}")
    con = duckdb.connect(DB_PATH, read_only=True)

    # 先嘗試 tle_table，再嘗試 raw_tle_archive；P3：嘗試取 bstar 欄位
    tle_df = None
    for tbl, time_col in [("tle_table", "date_tag"), ("raw_tle_archive", "epoch_utc")]:
        try:
            # 判斷 bstar 是否存在於該表
            try:
                tbl_cols  = con.execute(f"DESCRIBE {tbl}").df()["column_name"].str.lower().tolist()
                bstar_sel = ", bstar" if "bstar" in tbl_cols else ", NULL::DOUBLE AS bstar"
            except Exception:
                bstar_sel = ", NULL::DOUBLE AS bstar"

            tle_df = con.execute(f"""
                SELECT CAST(norad_id AS VARCHAR) AS norad_id,
                       {time_col}               AS epoch_dt,
                       sma_km,
                       eccentricity,
                       inclination_deg,
                       raan_deg
                       {bstar_sel}
                FROM {tbl}
                WHERE norad_id IN ({norad_sql})
                  AND {time_col} BETWEEN TIMESTAMP '{DATE_START}'
                                     AND TIMESTAMP '{DATE_END} 23:59:59'
                ORDER BY norad_id, {time_col}
            """).df()
            bstar_note = "有 bstar" if bstar_sel.startswith(", bstar") else "無 bstar"
            print(f"[{tbl}] 查到 {len(tle_df)} 筆 TLE 記錄（"
                  f"{tle_df['norad_id'].nunique()} 顆衛星有資料，{bstar_note}）")
            break
        except Exception as e:
            print(f"[{tbl}] 查詢失敗: {e}")

    con.close()

    if tle_df is None or tle_df.empty:
        sys.exit("[ERROR] 無法取得 TLE 資料，請確認 DuckDB 路徑與表格名稱。")

    tle_df["epoch_dt"] = pd.to_datetime(tle_df["epoch_dt"], utc=True, errors="coerce")
    tle_df["epoch_dt"] = tle_df["epoch_dt"].dt.tz_localize(None)  # 去掉 tz 便於比較

    # ── 4. 逐顆偵測機動 ───────────────────────────────────────────────────────
    records = []
    for norad in sampled_norads:
        sat_tle  = tle_df[tle_df.norad_id == str(norad)]
        ann_row  = sample_ann.loc[norad] if norad in sample_ann.index else {}

        rec = {
            "norad_id":               norad,
            "sat_name":               ann_row.get("sat_name",         "") if hasattr(ann_row, "get") else "",
            "propulsion_class":       ann_row.get("propulsion_class", "") if hasattr(ann_row, "get") else "",
            "mass_kg":                ann_row.get("mass_kg",          "") if hasattr(ann_row, "get") else "",
            "n_tle":                  len(sat_tle),
            "maneuver_detected":      False,
            "multi_window_detected":  False,   # P4
            "monotone_suppressed":    False,   # P1
            "monotone_with_spike":    False,   # P1 rescue
            "n_flagged":              0,
            "max_da_km":              None,
            "max_di_deg":             None,
            "flag_reasons":           "",
            "tle_status":             "no_data",
        }

        if len(sat_tle) < 3:
            rec["tle_status"] = f"only_{len(sat_tle)}_tle"
            records.append(rec)
            continue

        trans = detect_maneuvers_for_sat(sat_tle, use_p2=use_p2, use_p3=use_p3)

        if trans.empty:
            rec["tle_status"] = "ok_no_transitions"
            records.append(rec)
            continue

        flagged = trans[trans["flagged"]]
        rec["n_flagged"]            = int(len(flagged))
        rec["maneuver_detected"]    = bool(len(flagged) > 0)
        rec["monotone_suppressed"]  = bool(trans["monotone_suppressed"].any())   # P1
        rec["monotone_with_spike"]  = bool(trans["monotone_with_spike"].any())   # P1 rescue
        rec["max_da_km"]            = round(float(trans["da_km"].abs().max()), 3)
        rec["max_di_deg"]           = round(float(trans["di_deg"].abs().max()), 5)
        rec["tle_status"]           = "ok"

        if not flagged.empty:
            reasons = []
            # P2：用各轉移自己的 thr_da 比較（而非全域固定值）
            if (flagged["da_km"].abs() > flagged["thr_da"]).any():
                reasons.append(f"da={flagged['da_km'].abs().max():.2f}km")
            if (flagged["di_deg"].abs() > THR_DI).any():
                reasons.append(f"di={flagged['di_deg'].abs().max():.4f}°")
            if (flagged["de"].abs() > THR_DE).any():
                reasons.append(f"de={flagged['de'].abs().max():.5f}")
            if (flagged["draan_res_deg"].abs() > THR_DRAAN).any():
                reasons.append(f"draan_res={flagged['draan_res_deg'].abs().max():.3f}°")
            if rec["monotone_suppressed"]:
                reasons.append("mono_suppressed")
            rec["flag_reasons"] = "; ".join(reasons)

        # P4：多窗口滾動分析（4 × 7 天）——僅對主偵測未發現機動的衛星補查
        if not rec["maneuver_detected"]:
            mw_origin = sat_tle["epoch_dt"].min()
            for w in range(4):
                w0     = mw_origin + pd.Timedelta(days=w * 7)
                w1     = w0 + pd.Timedelta(days=7)
                w_data = sat_tle[(sat_tle["epoch_dt"] >= w0) & (sat_tle["epoch_dt"] < w1)]
                if len(w_data) >= 3:
                    w_tr = detect_maneuvers_for_sat(w_data, use_p2=use_p2, use_p3=use_p3)
                    if not w_tr.empty and w_tr["flagged"].any():
                        rec["multi_window_detected"] = True
                        break
        else:
            rec["multi_window_detected"] = True

        records.append(rec)

    # ── 5. 輸出 CSV ───────────────────────────────────────────────────────────
    res_df = pd.DataFrame(records)
    res_df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # ── 6. 驗證報告 ───────────────────────────────────────────────────────────
    ok   = res_df[res_df.tle_status == "ok"]
    skip = res_df[res_df.tle_status != "ok"]

    lines = []
    lines.append("=" * 65)
    lines.append(f"LEO 標註驗證報告  （{DATE_START} ~ {DATE_END}，P1–P4 改進版）")
    lines.append("=" * 65)
    lines.append(f"\n取樣總數 : {len(res_df)} 顆")
    lines.append(f"有效分析 : {len(ok)} 顆（TLE >= 3 筆且有轉移記錄）")
    lines.append(f"資料不足 : {len(skip)} 顆（{skip['tle_status'].value_counts().to_dict()}）")

    # P1 單調衰減抑制統計
    if "monotone_suppressed" in ok.columns:
        n_supp  = int(ok["monotone_suppressed"].sum())
        n_spike = int(ok["monotone_with_spike"].sum()) if "monotone_with_spike" in ok.columns else 0
        lines.append(f"P1 抑制大氣衰減 : {n_supp} 顆（da 旗標被 monotone_decay 覆蓋）")
        lines.append(f"P1 rescue spike : {n_spike} 顆（monotone+spike 保留偵測）")

    lines.append("\n" + "─" * 65)
    lines.append("推進類別 vs TLE 機動偵測率")
    lines.append("─" * 65)
    header = f"{'propulsion_class':<20} {'樣本':>5} {'有TLE':>6} {'偵到機動':>9} {'偵測率':>7}"
    lines.append(header)
    lines.append("─" * 65)

    cls_order = ["Electric_EP", "Chemical", "Micro/ColdGas", "Hybrid/Other", "None"]
    for cls in cls_order:
        sub    = res_df[res_df.propulsion_class == cls]
        sub_ok = ok[ok.propulsion_class == cls]
        det    = sub_ok["maneuver_detected"].sum()
        rate   = f"{det/len(sub_ok)*100:.0f}%" if len(sub_ok) > 0 else "N/A"
        lines.append(f"{cls:<20} {len(sub):>5} {len(sub_ok):>6} {det:>9} {rate:>7}")

    # 混淆矩陣
    has_prop = ok["propulsion_class"].isin(
        ["Electric_EP", "Chemical", "Micro/ColdGas", "Hybrid/Other"]) & \
        ok["propulsion_class"].notna()
    tp = int(ok[has_prop  & ok["maneuver_detected"]].shape[0])
    fn = int(ok[has_prop  & ~ok["maneuver_detected"]].shape[0])
    fp = int(ok[~has_prop & ok["maneuver_detected"]].shape[0])
    tn = int(ok[~has_prop & ~ok["maneuver_detected"]].shape[0])

    lines.append("\n" + "─" * 65)
    lines.append("混淆矩陣（有推進標註 vs TLE 偵測到機動）")
    lines.append("─" * 65)
    lines.append(f"  TP 有推進 + 偵到機動 : {tp:>4}")
    lines.append(f"  FN 有推進 + 未偵到   : {fn:>4}")
    lines.append(f"  FP 無推進 + 偵到機動 : {fp:>4}")
    lines.append(f"  TN 無推進 + 未偵到   : {tn:>4}")

    if tp + fp > 0 and tp + fn > 0:
        precision = tp / (tp + fp)
        recall    = tp / (tp + fn)
        f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        lines.append(f"\n  Precision : {precision:.1%}")
        lines.append(f"  Recall    : {recall:.1%}")
        lines.append(f"  F1-score  : {f1:.1%}")

    # P4 多窗口補偵混淆矩陣
    if "multi_window_detected" in ok.columns:
        any_det = ok["maneuver_detected"] | ok["multi_window_detected"]
        mw_new  = int((~ok["maneuver_detected"] & ok["multi_window_detected"]).sum())
        tp2 = int(ok[ has_prop &  any_det].shape[0])
        fn2 = int(ok[ has_prop & ~any_det].shape[0])
        fp2 = int(ok[~has_prop &  any_det].shape[0])
        tn2 = int(ok[~has_prop & ~any_det].shape[0])
        lines.append("\n" + "─" * 65)
        lines.append("P4 多窗口補偵後混淆矩陣（主偵測 OR 任意 7 天窗口偵到）")
        lines.append("─" * 65)
        lines.append(f"  多窗口新增偵測 : {mw_new:>4} 顆（原未偵到，7 天窗口補到）")
        lines.append(f"  TP : {tp2:>4}   FN : {fn2:>4}   FP : {fp2:>4}   TN : {tn2:>4}")
        if tp2 + fp2 > 0 and tp2 + fn2 > 0:
            p2 = tp2 / (tp2 + fp2)
            r2 = tp2 / (tp2 + fn2)
            f2 = 2 * p2 * r2 / (p2 + r2) if (p2 + r2) > 0 else 0
            lines.append(f"  Precision : {p2:.1%}   Recall : {r2:.1%}   F1 : {f2:.1%}")

    # monotone_with_spike 補救後混淆矩陣（P1 rescue）
    if "monotone_with_spike" in ok.columns:
        spike_rescue = ok["monotone_with_spike"].fillna(False).astype(bool)
        any_det3 = ok["maneuver_detected"] | ok["multi_window_detected"].fillna(False) | spike_rescue
        spike_new = int((~ok["maneuver_detected"] & ~ok["multi_window_detected"].fillna(False) & spike_rescue).sum())
        tp3 = int(ok[ has_prop &  any_det3].shape[0])
        fn3 = int(ok[ has_prop & ~any_det3].shape[0])
        fp3 = int(ok[~has_prop &  any_det3].shape[0])
        tn3 = int(ok[~has_prop & ~any_det3].shape[0])
        lines.append("\n" + "─" * 65)
        lines.append("monotone_with_spike 補救後混淆矩陣（P1 rescue + P4）")
        lines.append("─" * 65)
        lines.append(f"  spike rescue 新增 : {spike_new:>4} 顆")
        lines.append(f"  TP : {tp3:>4}   FN : {fn3:>4}   FP : {fp3:>4}   TN : {tn3:>4}")
        if tp3 + fp3 > 0 and tp3 + fn3 > 0:
            p3 = tp3 / (tp3 + fp3)
            r3 = tp3 / (tp3 + fn3)
            f3 = 2 * p3 * r3 / (p3 + r3) if (p3 + r3) > 0 else 0
            lines.append(f"  Precision : {p3:.1%}   Recall : {r3:.1%}   F1 : {f3:.1%}")
            lines.append(f"\n[最終指標] Precision={p3:.1%}  Recall={r3:.1%}  F1={f3:.1%}")

    lines.append("\n" + "─" * 65)
    lines.append("機動偵測衛星（前 30）")
    lines.append("─" * 65)
    top = ok[ok.maneuver_detected].sort_values("max_da_km", ascending=False).head(80)
    for _, r in top.iterrows():
        lines.append(
            f"  NORAD {r['norad_id']:>7}  {r['sat_name'][:22]:<22}"
            f"  {r['propulsion_class']:<15}"
            f"  da_max={r['max_da_km']:>7.3f} km"
            f"  flags={r['n_flagged']:>3}"
        )

    report = "\n".join(lines)
    print("\n" + report)
    Path(out_report).write_text(report, encoding="utf-8")
    print(f"\n[DONE] {out_csv}")
    print(f"[DONE] {out_report}")


if __name__ == "__main__":
    main()
