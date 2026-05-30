"""
analyze_maneuver_behavior.py
============================
對 validation_full.csv 中 maneuver_detected=True 的 LEO 衛星，
重新抓取逐筆 TLE 轉移資料，分析機動行為特性並分類，輸出 Markdown 說明文件。
"""

import io
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ── 設定 ─────────────────────────────────────────────────────────────────────
DB_PATH    = r"C:\STK_Python\CCIT_Orbit_Maneuvers\GCP_Version\space_db.duckdb"
VAL_CSV    = r"output/validation_full.csv"
ANN_CSV    = r"output/annotations_leo_full.csv"
OUT_MD     = r"output/maneuver_behavior_report.md"
OUT_CSV    = r"output/maneuver_behavior_classified.csv"

DATE_START = "2026-05-01"
DATE_END   = "2026-05-30"
OBS_DAYS   = 30.0   # DATE_END - DATE_START 的天數差

THR_DA_SM  = 1.0
THR_DI     = 0.02
THR_DE     = 0.001
THR_DRAAN  = 0.1

J2 = 1.08263e-3
RE = 6378.137
MU = 398600.4418

_STREAK_NORM  = 5
_STREAK_BSTAR = 3
_DROP_NORM    = 5.0
_DROP_BSTAR   = 3.0
_NET_NORM     = -3.0
_NET_BSTAR    = -2.0


def adaptive_thr_da(sma_km: float) -> float:
    """P2：高度自適應 Δa 閾值（< 400 km → 2.0；> 600 km → 0.5；其餘 1.0）"""
    alt = sma_km - RE
    if alt < 400:
        return 2.0
    elif alt > 600:
        return 0.5
    return THR_DA_SM


# ── 輔助函式 ─────────────────────────────────────────────────────────────────

def j2_raan_rate(sma, ecc, inc_deg):
    n = np.sqrt(MU / sma ** 3)
    p = sma * (1 - ecc ** 2)
    return np.degrees(-1.5 * J2 * (RE / p) ** 2 * n * np.cos(np.radians(inc_deg)))


def angle_diff(a, b):
    d = (a - b) % 360.0
    return d - 360.0 if d > 180.0 else d


def detect_transitions(df: pd.DataFrame) -> pd.DataFrame:
    """P1/P2/P3 同步版：adaptive_thr_da + monotone_decay 抑制 + B* 輔助"""
    df = df.sort_values("epoch_dt").reset_index(drop=True)
    rows = []
    for i in range(1, len(df)):
        prev, curr = df.iloc[i - 1], df.iloc[i]
        dt_s = (curr["epoch_dt"] - prev["epoch_dt"]).total_seconds()
        if dt_s <= 0 or dt_s > 86400 * 7:
            continue
        da        = float(curr["sma_km"])          - float(prev["sma_km"])
        di        = float(curr["inclination_deg"]) - float(prev["inclination_deg"])
        de        = float(curr["eccentricity"])    - float(prev["eccentricity"])
        draan_raw = angle_diff(float(curr["raan_deg"]), float(prev["raan_deg"]))
        raan_j2   = j2_raan_rate(float(prev["sma_km"]), float(prev["eccentricity"]),
                                  float(prev["inclination_deg"])) * dt_s
        draan_res = draan_raw - raan_j2
        thr_da    = adaptive_thr_da(float(prev["sma_km"]))  # P2

        flagged = (abs(da) > thr_da or abs(di) > THR_DI or
                   abs(de) > THR_DE or abs(draan_res) > THR_DRAAN)
        rows.append({
            "epoch":     curr["epoch_dt"],
            "dt_h":      round(dt_s / 3600, 2),
            "da_km":     round(da, 3),
            "di_deg":    round(di, 5),
            "de":        round(de, 6),
            "draan_res": round(draan_res, 4),
            "sma_km":    round(float(prev["sma_km"]), 3),
            "thr_da":    round(thr_da, 2),
            "flagged":   flagged,
        })

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows)

    # P1 + P3：單調衰減偵測
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

    bstar_boost = False
    if "bstar" in df.columns and df["bstar"].notna().any():
        bstar_mean  = float(df["bstar"].dropna().mean())
        bstar_boost = (bstar_mean > 0.0005 and float(df["sma_km"].mean()) < RE + 450)

    s_thr = _STREAK_BSTAR if bstar_boost else _STREAK_NORM
    d_thr = _DROP_BSTAR   if bstar_boost else _DROP_NORM
    n_thr = _NET_BSTAR    if bstar_boost else _NET_NORM

    monotone_decay = (neg_streak >= s_thr and total_drop > d_thr and net_da < n_thr)

    if monotone_decay:
        result["flagged"] = (
            (result["di_deg"].abs()   > THR_DI)    |
            (result["de"].abs()       > THR_DE)    |
            (result["draan_res"].abs() > THR_DRAAN)
        )

    result["monotone_suppressed"] = monotone_decay
    return result


# ── 行為分類器 ────────────────────────────────────────────────────────────────

def classify_behavior(tr: pd.DataFrame, sat_info: dict) -> dict:
    """
    輸入逐筆轉移 DataFrame，回傳行為分類結果。
    """
    flagged  = tr[tr["flagged"]].copy()
    n_trans  = len(tr)
    n_flag   = len(flagged)
    prop_cls = sat_info.get("propulsion_class", "")

    # ── 觸發維度 ─────────────────────────────────────────────────────────────
    has_da     = (flagged["da_km"].abs() > THR_DA_SM).any()    if not flagged.empty else False
    has_di     = (flagged["di_deg"].abs() > THR_DI).any()       if not flagged.empty else False
    has_de     = (flagged["de"].abs() > THR_DE).any()           if not flagged.empty else False
    has_draan  = (flagged["draan_res"].abs() > THR_DRAAN).any() if not flagged.empty else False

    max_da  = flagged["da_km"].abs().max()   if not flagged.empty else 0.0
    max_di  = flagged["di_deg"].abs().max()  if not flagged.empty else 0.0
    net_da  = float(tr["da_km"].sum())       # 21 天累積 da
    da_vals = tr["da_km"].values

    # ── 單調性分析 ───────────────────────────────────────────────────────────
    neg_streak = 0   # 最長連續下降段
    cur_streak = 0
    for v in da_vals:
        if v < -0.3:
            cur_streak += 1
            neg_streak = max(neg_streak, cur_streak)
        else:
            cur_streak = 0

    total_drop     = -net_da if net_da < 0 else 0.0
    monotone_decay = (neg_streak >= 5 and total_drop > 5.0 and net_da < -3.0)

    # ── 頻率指標 ─────────────────────────────────────────────────────────────
    flag_rate = n_flag / n_trans if n_trans > 0 else 0.0
    burn_freq = n_flag / OBS_DAYS   # burns/day

    # ── 主類別判定 ───────────────────────────────────────────────────────────
    if prop_cls not in ("Electric_EP", "Chemical", "Micro/ColdGas", "Hybrid/Other"):
        # 無推進標註
        if monotone_decay:
            behavior = "DragDecay"
        elif has_draan and not has_da and not has_di:
            behavior = "UnknownRAANAnomaly"
        else:
            behavior = "UnknownFP"
    else:
        # 有推進
        if monotone_decay:
            behavior = "DragMakeup"          # 電推持續補償拖曳
        elif net_da > 5.0 and has_da:
            behavior = "OrbitRaising"
        elif net_da < -5.0 and has_da and not monotone_decay:
            behavior = "OrbitLowering"
        elif has_da and has_di:
            behavior = "ComplexManeuver"
        elif has_di and not has_da:
            behavior = "InclinationChange"
        elif has_draan and not has_da and not has_di:
            behavior = "RAANMaintenance"
        elif flag_rate > 0.25 and has_da:
            behavior = "Stationkeeping"
        elif n_flag <= 3 and max_da > 5.0:
            behavior = "PhasingManeuver"
        elif has_da and flag_rate <= 0.15:
            behavior = "DragMakeup"
        else:
            behavior = "Stationkeeping"

    # ── 行為細分標籤 ─────────────────────────────────────────────────────────
    sub_tags = []
    if has_da:
        sub_tags.append(f"da_max={max_da:.1f}km net={net_da:+.1f}km")
    if has_di:
        sub_tags.append(f"di_max={max_di:.4f}°")
    if has_de:
        sub_tags.append("Δe")
    if has_draan:
        sub_tags.append(f"draan_res")
    if monotone_decay:
        sub_tags.append(f"monotone_drop={total_drop:.1f}km")

    return {
        "behavior":      behavior,
        "net_da_km":     round(net_da, 2),
        "max_da_km":     round(max_da, 3),
        "max_di_deg":    round(max_di, 5),
        "n_flagged":     n_flag,
        "n_transitions": n_trans,
        "flag_rate":     round(flag_rate, 3),
        "burn_freq_per_day": round(burn_freq, 3),
        "monotone_decay": monotone_decay,
        "triggers":      "+".join([x for x in ["da", "di", "de", "draan"]
                                   if [has_da, has_di, has_de, has_draan][
                                       ["da","di","de","draan"].index(x)]]),
        "sub_tags":      "; ".join(sub_tags),
        "mean_sma_km":   round(float(tr["sma_km"].mean()), 1),
    }


# ── Markdown 報告產生器 ───────────────────────────────────────────────────────

BEHAVIOR_DESC = {
    "OrbitRaising":       ("軌道抬升", "衛星執行主動升軌機動，半長軸淨增 >5 km。常見於新星座部署、任務相位調整或規避目標後返回工作軌道。"),
    "OrbitLowering":      ("軌道降低 / 離軌", "衛星執行主動降軌或離軌機動，半長軸淨減 >5 km。可能為任務結束降軌、再入燃燒或碰撞規避後的軌道修正。"),
    "Stationkeeping":     ("站位保持", "衛星在觀測窗口內頻繁執行小幅機動（旗標率 >25%），維持精確工作軌道高度或相位。典型於 EO/SAR 星座的重訪週期維持。"),
    "DragMakeup":         ("大氣阻力補償", "電推或小推力系統持續補償大氣阻力造成的軌道衰減，da 呈現週期性小幅正向修正，累積 da 接近零或微正。"),
    "PhasingManeuver":    ("相位調整", "少量旗標（≤3 次）但 da 幅度大，表示衛星在短時間內執行一次或數次明顯的軌道相位調整，後續軌道趨於穩定。"),
    "ComplexManeuver":    ("複合機動", "同時觸發 da 與 di 旗標，衛星在觀測期間執行了包含軌道面變換在內的複合機動。"),
    "InclinationChange":  ("傾角調整", "僅 di 旗標觸發，衛星執行軌道傾角變更，典型於任務轉換或初始部署後的面調整。"),
    "RAANMaintenance":    ("RAAN 維持", "RAAN 殘差（去除 J2 進動後）超過閾值，衛星可能正在維持太陽同步或特定地面軌跡的升交點赤經。"),
    "DragDecay":          ("大氣阻力衰減（無推進）", "無推進衛星在低軌道因大氣阻力導致半長軸持續單調下降，非主動機動，為 FP 誤判目標。"),
    "UnknownRAANAnomaly": ("RAAN 異常（身份待查）", "觸發 RAAN 殘差但無 da/di，物體身份或推進系統不確定，需進一步研究。"),
    "UnknownFP":          ("未知 FP", "無推進標註但觸發機動旗標，可能為資料噪聲、TLE 品質問題或推進系統標註遺漏。"),
}


def df_to_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    header = "| " + " | ".join(str(c) for c in cols) + " |"
    sep    = "|" + "---|" * len(cols)
    rows   = []
    for _, r in df.iterrows():
        rows.append("| " + " | ".join(str(v) for v in r.values) + " |")
    return "\n".join([header, sep] + rows)


def generate_report(classified: pd.DataFrame) -> str:
    lines = []
    lines.append("# LEO 衛星機動行為分析報告")
    lines.append("")
    lines.append(f"**資料期間：** {DATE_START} ～ {DATE_END}（{OBS_DAYS:.0f} 天，P1–P3 改進版）")
    lines.append(f"**分析樣本：** {len(classified)} 顆（maneuver_detected=True）")
    lines.append(f"**機動偵測閾值：** Δa > {THR_DA_SM} km | Δi > {THR_DI}° | Δe > {THR_DE} | RAAN_res > {THR_DRAAN}°")
    lines.append("")

    # 行為分類統計
    lines.append("## 1. 行為類別總覽")
    lines.append("")
    cnt = classified["behavior"].value_counts()
    lines.append("| 類別代號 | 中文名稱 | 顆數 | 佔比 |")
    lines.append("|---------|---------|------|------|")
    for beh, n in cnt.items():
        zh, _ = BEHAVIOR_DESC.get(beh, (beh, ""))
        lines.append(f"| {beh} | {zh} | {n} | {n/len(classified)*100:.1f}% |")
    lines.append("")

    # 推進類別 × 行為分佈
    lines.append("## 2. 推進類別 × 行為分佈")
    lines.append("")
    ct = pd.crosstab(classified["propulsion_class"].fillna("未標註"),
                     classified["behavior"])
    behs = list(cnt.index)
    props = list(ct.index)
    lines.append("| 推進類別 | " + " | ".join(behs) + " |")
    lines.append("|" + "---|" * (len(behs) + 1))
    for p in props:
        row_vals = [str(int(ct.loc[p, b])) if b in ct.columns else "0" for b in behs]
        lines.append(f"| {p} | " + " | ".join(row_vals) + " |")
    lines.append("")

    # 各行為類別詳細說明 + 代表衛星
    lines.append("## 3. 各行為類別詳細說明與代表案例")
    lines.append("")
    for beh, n in cnt.items():
        zh, desc = BEHAVIOR_DESC.get(beh, (beh, ""))
        sub = classified[classified["behavior"] == beh].sort_values("max_da_km", ascending=False)
        lines.append(f"### 3.{list(cnt.index).index(beh)+1} {beh}（{zh}）— {n} 顆")
        lines.append("")
        lines.append(f"**說明：** {desc}")
        lines.append("")
        # 統計摘要
        lines.append(f"- 平均 |Δa| 最大值：{sub['max_da_km'].mean():.2f} km")
        lines.append(f"- 平均淨 Δa（26 天）：{sub['net_da_km'].mean():+.2f} km")
        lines.append(f"- 平均旗標次數：{sub['n_flagged'].mean():.1f} 次")
        lines.append(f"- 平均旗標率（flags/transitions）：{sub['flag_rate'].mean()*100:.1f}%")
        lines.append(f"- 平均軌道高度（SMA）：{sub['mean_sma_km'].mean()-6378.137:.0f} km")
        lines.append("")
        # 代表衛星（最多 15 顆）
        lines.append("**代表衛星：**")
        lines.append("")
        lines.append("| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |")
        lines.append("|-------|---------|---------|-----------|----------|--------|---------|")
        for _, r in sub.head(15).iterrows():
            pc = r["propulsion_class"] if pd.notna(r["propulsion_class"]) else "—"
            lines.append(
                f"| {r['norad_id']} | {str(r['sat_name'])[:22]} | {pc} "
                f"| {r['net_da_km']:+.1f} | {r['max_da_km']:.2f} "
                f"| {int(r['n_flagged'])} | {r['triggers']} |"
            )
        if len(sub) > 15:
            lines.append(f"| … | （另 {len(sub)-15} 顆） | | | | | |")
        lines.append("")

    # 特殊案例
    lines.append("## 4. 特殊案例分析")
    lines.append("")

    # 最大 da
    top_da = classified.nlargest(5, "max_da_km")[
        ["norad_id","sat_name","propulsion_class","behavior","max_da_km","net_da_km","n_flagged"]]
    lines.append("### 4.1 半長軸最大變化量（前 5 顆）")
    lines.append("")
    lines.append(df_to_md(top_da.reset_index(drop=True)))
    lines.append("")

    # 最多旗標
    top_flag = classified.nlargest(5, "n_flagged")[
        ["norad_id","sat_name","propulsion_class","behavior","n_flagged","flag_rate","max_da_km"]]
    lines.append("### 4.2 旗標次數最多（前 5 顆）")
    lines.append("")
    lines.append(df_to_md(top_flag.reset_index(drop=True)))
    lines.append("")

    # 高頻燃燒
    hf = classified[classified["burn_freq_per_day"] > 1.0].sort_values(
        "burn_freq_per_day", ascending=False).head(10)[
        ["norad_id","sat_name","propulsion_class","behavior","burn_freq_per_day","n_flagged"]]
    if not hf.empty:
        lines.append("### 4.3 高頻機動衛星（>1 次/天，前 10 顆）")
        lines.append("")
        lines.append(df_to_md(hf.reset_index(drop=True)))
        lines.append("")

    # FP 殘餘分析
    fp = classified[classified["behavior"].isin(["DragDecay","UnknownFP","UnknownRAANAnomaly"])]
    lines.append("## 5. 殘餘 FP 分析（無推進標註但觸發機動旗標）")
    lines.append("")
    lines.append(f"共 {len(fp)} 顆殘餘 FP，細分如下：")
    lines.append("")
    fp_cnt = fp["behavior"].value_counts()
    lines.append("| 子類別 | 顆數 | 主要特徵 |")
    lines.append("|-------|------|---------|")
    for b, n in fp_cnt.items():
        zh, desc = BEHAVIOR_DESC.get(b, (b, ""))
        lines.append(f"| {zh} | {n} | {desc[:60]}… |")
    lines.append("")
    lines.append("**殘餘 FP 完整列表：**")
    lines.append("")
    lines.append("| NORAD | 衛星名稱 | 行為 | |Δa|max (km) | 旗標數 | 觸發 |")
    lines.append("|-------|---------|------|----------|--------|------|")
    for _, r in fp.sort_values("max_da_km", ascending=False).iterrows():
        lines.append(
            f"| {r['norad_id']} | {str(r['sat_name'])[:25]} | "
            f"{BEHAVIOR_DESC.get(r['behavior'],('',''))[0]} | "
            f"{r['max_da_km']:.2f} | {int(r['n_flagged'])} | {r['triggers']} |"
        )
    lines.append("")

    # 訓練資料建議
    lines.append("## 6. 訓練資料建議")
    lines.append("")
    lines.append("### 6.1 高品質正例（TP）建議使用策略")
    lines.append("")
    lines.append("| 行為類別 | 推薦使用 | 建議標籤 |")
    lines.append("|---------|---------|---------|")
    tp_recs = [
        ("OrbitRaising",    "✅ 高信心",  "maneuver=True, type=raising"),
        ("OrbitLowering",   "✅ 高信心",  "maneuver=True, type=lowering"),
        ("PhasingManeuver", "✅ 高信心",  "maneuver=True, type=phasing"),
        ("ComplexManeuver", "✅ 中信心",  "maneuver=True, type=complex"),
        ("Stationkeeping",  "✅ 中信心",  "maneuver=True, type=stationkeeping"),
        ("DragMakeup",      "⚠️ 低信心",  "maneuver=True, type=drag_makeup (區分困難)"),
        ("DragDecay",       "❌ 排除",    "非機動，建議從 TP 集移除"),
        ("UnknownFP",       "❌ 排除或查明", "身份未確認，不納入訓練"),
    ]
    for beh, rec, lbl in tp_recs:
        lines.append(f"| {beh} | {rec} | `{lbl}` |")
    lines.append("")
    lines.append("### 6.2 Recall 偏低原因分析")
    lines.append("")
    lines.append("本次驗證 Recall ≈ 12.4%，主要原因：")
    lines.append("")
    lines.append("1. **觀測窗口（26 天）**：電推衛星每次燃燒僅 1–3 km，26 天內不一定執行機動。")
    lines.append("2. **閾值偏高**：THR_DA_SM=1.0 km 過濾掉微小機動；低軌 Starlink 電推量約 0.1–0.5 km/burn。")
    lines.append("3. **TLE 更新頻率不足**：機動發生於兩個 TLE epoch 之間無法偵測。")
    lines.append("4. **多機動抵消**：升軌後降軌的累積 da 趨近零，被視為無機動。")
    lines.append("")

    lines.append("---")
    lines.append(f"*Generated by analyze_maneuver_behavior.py — 分析日期：{DATE_START}～{DATE_END}*")
    return "\n".join(lines)


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    # 1. 載入 validation CSV 篩選有機動衛星
    val = pd.read_csv(VAL_CSV, dtype=str, encoding="utf-8-sig")
    val["maneuver_detected"] = val["maneuver_detected"].map({"True": True, "False": False})
    val["max_da_km"]  = pd.to_numeric(val["max_da_km"],  errors="coerce")
    val["n_flagged"]  = pd.to_numeric(val["n_flagged"],  errors="coerce")
    val["max_di_deg"] = pd.to_numeric(val["max_di_deg"], errors="coerce")

    maneuvering = val[val["maneuver_detected"] == True].copy()
    print(f"機動衛星數：{len(maneuvering)} 顆")

    # 2. 載入標註（取 propulsion_class）
    ann = pd.read_csv(ANN_CSV, dtype=str, encoding="utf-8-sig")
    ann["norad_id"] = ann["norad_id"].astype(str).str.strip()
    ann_idx = ann.set_index("norad_id")

    # 3. 查詢 DuckDB 逐筆 TLE
    norads = maneuvering["norad_id"].astype(str).str.strip().tolist()
    norad_ints = ", ".join(str(int(n)) for n in norads)

    print(f"連線 DuckDB: {DB_PATH}")
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        tbl_cols  = con.execute("DESCRIBE tle_table").df()["column_name"].str.lower().tolist()
        bstar_sel = ", bstar" if "bstar" in tbl_cols else ", NULL::DOUBLE AS bstar"
    except Exception:
        bstar_sel = ", NULL::DOUBLE AS bstar"
    tle_df = con.execute(f"""
        SELECT CAST(norad_id AS VARCHAR) AS norad_id,
               date_tag AS epoch_dt,
               sma_km, eccentricity, inclination_deg, raan_deg
               {bstar_sel}
        FROM tle_table
        WHERE norad_id IN ({norad_ints})
          AND date_tag BETWEEN TIMESTAMP '{DATE_START}'
                           AND TIMESTAMP '{DATE_END} 23:59:59'
        ORDER BY norad_id, date_tag
    """).df()
    con.close()
    tle_df["epoch_dt"] = pd.to_datetime(tle_df["epoch_dt"], utc=True, errors="coerce")
    tle_df["epoch_dt"] = tle_df["epoch_dt"].dt.tz_localize(None)
    print(f"TLE 筆數：{len(tle_df)}")

    # 4. 逐顆行為分類
    records = []
    for norad in norads:
        sat_tle = tle_df[tle_df["norad_id"] == norad]
        if len(sat_tle) < 3:
            continue
        tr = detect_transitions(sat_tle)
        if tr.empty:
            continue
        flagged = tr[tr["flagged"]]
        if flagged.empty:
            continue

        ann_row = ann_idx.loc[norad] if norad in ann_idx.index else {}
        prop_cls = ann_row.get("propulsion_class", "") if hasattr(ann_row, "get") else ""
        sat_name = ann_row.get("sat_name", "")         if hasattr(ann_row, "get") else ""

        beh = classify_behavior(tr, {"propulsion_class": prop_cls})
        beh.update({
            "norad_id":         norad,
            "sat_name":         sat_name,
            "propulsion_class": prop_cls if (prop_cls and prop_cls == prop_cls) else None,
        })
        records.append(beh)

    classified = pd.DataFrame(records)
    print(f"分類完成：{len(classified)} 顆")
    print(classified["behavior"].value_counts().to_string())

    # 5. 輸出 CSV
    col_order = ["norad_id", "sat_name", "propulsion_class", "behavior",
                 "net_da_km", "max_da_km", "max_di_deg", "n_flagged",
                 "n_transitions", "flag_rate", "burn_freq_per_day",
                 "monotone_decay", "triggers", "mean_sma_km", "sub_tags"]
    classified[col_order].to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n[DONE] {OUT_CSV}")

    # 6. 輸出 Markdown
    report = generate_report(classified)
    Path(OUT_MD).write_text(report, encoding="utf-8")
    print(f"[DONE] {OUT_MD}")


if __name__ == "__main__":
    main()
