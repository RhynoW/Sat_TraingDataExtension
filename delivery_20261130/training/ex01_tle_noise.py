"""練習 1：TLE 時間序列、平均高度與 TLE 雜訊（需網路，讀 HF 公開資料集）

學習目標
1. 由 TLE 半長軸換算平均高度，看懂一顆衛星的高度歷程。
2. 認識發射初期 TLE 的不穩定（SJ-26 最初數筆在兩個高度之間交替）。
3. 以相鄰 TLE 半長軸差（Δa）之穩健標準差估計 TLE 雜訊，理解「偵測下限」的來源。

執行：python training/ex01_tle_noise.py
"""
import _common  # noqa: F401
import numpy as np

rb = _common.load_builder()
R_E = 6378.137
NORAD = 64199  # SJ-26，2025-05-29 04:12 UTC 發射

df = rb.load_tle(NORAD)
df["alt_km"] = df["sma_km"] - R_E
print(f"SJ-26（NORAD {NORAD}）共 {len(df)} 筆 TLE，{df.epoch.min():%Y-%m-%d} 至 {df.epoch.max():%Y-%m-%d}\n")

print("① 最初 8 筆 TLE 之平均高度（半長軸 − 地球赤道半徑）")
for _, r in df.head(8).iterrows():
    print(f"   {r.epoch:%Y-%m-%d %H:%M}  {r.alt_km:7.1f} km")

# 入軌穩定後之 Δa 雜訊：取 2025-07 起，排除 |Δa| > 1 km 之大步階（可能為機動）
st = df[df.epoch >= "2025-07-01"].copy()
da = np.diff(st["sma_km"].to_numpy())
small = da[np.abs(da) < 1.0]
mad = np.median(np.abs(small - np.median(small)))
sigma = 1.4826 * mad
print(f"\n② 2025-07 以後：相鄰 TLE 轉換 {len(da)} 個，|Δa|<1 km 者 {len(small)} 個")
print(f"   Δa 中位數 {np.median(small)*1000:+.1f} m（負值＝大氣阻力造成之平均衰減）")
print(f"   穩健標準差 σ = 1.4826 × MAD = {sigma*1000:.1f} m")
print(f"   5σ ≈ {5*sigma*1000:.0f} m、20σ ≈ {20*sigma*1000:.0f} m")
print("   （R7 報表之偵測下限以「未標記轉換、逐月穩健標準差之中位數」計算，數值會略有不同，見練習 3）")
