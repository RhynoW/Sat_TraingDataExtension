"""練習 4：輔助通道——NRLMSIS 阻力殘差與 L2 統計變點（需網路與 pymsis）

學習目標
1. 理解阻力殘差：實測 Δa 減去 NRLMSIS 大氣模型預期之阻力 Δa，剩下的才是「阻力解釋不了」的變化。
2. 理解 L2 四種統計方法（CUSUM、BOCPD、SSA、MAD 3σ）各自觸發的時點，以及「≥2 種同時觸發」的意義。
3. 對照練習 3 之候選事件，看輔助通道如何只影響證據等級、不新增事件。

執行：python training/ex04_aux_channels.py
"""
import _common  # noqa: F401
import numpy as np
import pandas as pd

rb = _common.load_builder()
NORAD = 62190  # HAISHAO 1
df = rb.load_tle(NORAD, "2025-03-01", "2025-06-30")
print(f"HAISHAO 1：{len(df)} 筆 TLE（2025-03-01 至 06-30）")

# ① 阻力殘差
dr = rb.compute_drag_series(df)
if dr is None:
    print("① 阻力殘差：無法計算（請確認已安裝 pymsis 且 space_weather_ap.csv 存在）")
else:
    print(f"\n① 阻力殘差：{len(dr)} 個轉換；|殘差| > 0.3 km 者 {int((dr.drag_resid_da.abs() > 0.3).sum())} 個")
    print("   殘差最大之 6 個轉換（實測 Δa、殘差，單位 km）：")
    top = dr.reindex(dr.drag_resid_da.abs().sort_values(ascending=False).index).head(6)
    for _, x in top.sort_values("epoch").iterrows():
        print(f"   {x.epoch:%Y-%m-%d %H:%M}  實測 {x.da_km:+7.3f}  殘差 {x.drag_resid_da:+7.3f}")
    print(f"   全期間實測 Δa 中位 {dr.da_km.median()*1000:+.0f} m，殘差中位 {dr.drag_resid_da.median()*1000:+.0f} m"
          "（模型扣除大部分阻力衰減後，殘差應接近 0）")

# ② L2 統計變點
l2 = rb.compute_l2(df)
ep = df["epoch"].reset_index(drop=True)
print("\n② L2 四種方法之觸發時點（索引對應 TLE 序列）")
hits = {}
for k in ("cusum", "bocpd", "ssa", "mad3sig"):
    evs = np.asarray(l2.get(k, {}).get("events", []))
    if evs.dtype == bool:              # 布林遮罩 → 索引
        evs = np.flatnonzero(evs)
    idx = [int(i) for i in evs if 0 <= int(i) < len(ep)]
    hits[k] = pd.to_datetime(ep.iloc[idx]).tolist() if idx else []
    print(f"   {k:8s} {len(idx):3d} 次：" + "、".join(t.strftime('%m-%d') for t in hits[k][:12]))

# ③ 48 小時內 ≥2 種方法同時觸發之時點
allt = sorted((t, k) for k, ts in hits.items() for t in ts)
multi = []
for t, k in allt:
    near = {k2 for t2, k2 in allt if abs((t2 - t).total_seconds()) <= 48 * 3600}
    if len(near) >= 2 and (not multi or (t - multi[-1][0]).total_seconds() > 48 * 3600):
        multi.append((t, sorted(near)))
print(f"\n③ 48 小時內 ≥2 種方法同時觸發：{len(multi)} 處")
for t, ks in multi:
    print(f"   {t:%Y-%m-%d}  {'＋'.join(ks)}")
print("   對照練習 3：低軌高阻力衛星之 L2 方法觸發頻繁，「≥2 種同時觸發」本身不足以代表機動。"
      "R7 對未落在候選事件前後 24 小時內者，另要求「扣除背景衰減後之淨變化超過 L1 單步門檻與 20σ 下限」，"
      "因此練習 3 只列出 2 項 L2 低置信複核項。")
