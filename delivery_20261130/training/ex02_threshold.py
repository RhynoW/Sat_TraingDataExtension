"""練習 2：L1 規則之有效門檻（P2 × P5 × P6）與 P1 抑制（離線即可執行）

學習目標
1. 計算不同高度、太陽活動、傾角族群下之半長軸判定門檻。
2. 看懂 P5 倍率上限 1.8 的作用。
3. 以一段人工轉換序列，比較「舊版聯集（等同只看 P2）」與「R7 有效門檻」之差別，
   並觀察 P1 如何抑制大氣阻力造成的單調小步衰減。

執行：python training/ex02_threshold.py
"""
import _common  # noqa: F401
import numpy as np
import pandas as pd

import maneuver_strategies_july as ms

P2, P5, P6 = ms.DEFAULT_P2, ms.DEFAULT_P5, ms.DEFAULT_P6

print("① P2 高度門檻（km）")
for alt in (350, 400, 500, 550, 600, 700, 800):
    print(f"   {alt:4d} km → {float(P2(alt)):.3f} km")

print("\n② P5 太陽活動倍率（拋物線，夾在 1.0–1.8）")
for f in (70, 100, 150, 200, 250, 300):
    raw = float(P5(f))
    print(f"   F10.7 {f:3d} sfu → 拋物線 ×{raw:.2f}，採用 ×{min(max(raw, 1.0), ms.P5_MULT_MAX):.2f}")

print("\n③ P6 傾角族群倍率：", P6)

print("\n④ 有效門檻 = P2(高度) × P5(F10.7) × P6(族群)，單位 m")
fams = ("53deg", "SSO", "mid-inc")
print("   高度  F10.7 " + "".join(f"{f:>9s}" for f in fams))
for alt in (400, 550, 700):
    for f in (70, 150, 200):
        m5 = min(max(float(P5(f)), 1.0), ms.P5_MULT_MAX)
        row = "".join(f"{float(P2(alt)) * m5 * P6[k] * 1000:9.0f}" for k in fams)
        print(f"   {alt:4d}  {f:5d} {row}")

# ⑤ 人工轉換序列：550 km 太陽同步軌道（傾角 97.5°），F10.7=150 sfu
# 前 8 筆為每筆約 −20 m 的阻力衰減，第 9 筆為 +1.0 km 步階，第 10 筆為 +1.5 km 步階
da = [-0.02] * 8 + [1.0, 1.5] + [-0.02] * 6
n = len(da)
tr = pd.DataFrame({
    "da_km": da, "di_deg": 0.0, "de": 0.0, "draan_res_deg": 0.0,
    "alt_km": 550.0, "bstar": 2e-4, "f107": 150.0, "inc_deg": 97.5,
})
res = ms.apply_strategies(tr, "LEO")
ps = res["per_strategy"]
print("\n⑤ 人工序列（550 km、SSO、F10.7=150）：")
print(f"   P2 門檻 {float(P2(550))*1000:.0f} m；R7 有效門檻 {res['thr_da'][0]*1000:.0f} m")
print("   序  Δa(m)   P2標記  有效門檻標記  P1抑制  R7最終")
for i in range(n):
    print(f"   {i:2d} {da[i]*1000:+7.0f}   {str(bool(ps['P2'][i])):6s}  "
          f"{str(bool(abs(da[i]) > res['thr_da'][i])):12s}  {str(bool(ps['P1_suppress'][i])):6s}  {bool(res['combined'][i])}")
print("   說明：+1.0 km 步階超過 P2 門檻但未達有效門檻，舊版（聯集）會標記、R7 不標記；")
print("         +1.5 km 步階超過有效門檻，R7 標記，P4 再把其後 2 筆一併補標，以延長事件邊界。")
