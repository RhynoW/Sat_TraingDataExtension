"""練習 5：評估指標——每千星日、Poisson 精確信賴區間、隨機命中基準（離線即可執行）

學習目標
1. 以「每千星日」表示誤報率，理解為何不用百分比。
2. 以 Poisson 精確法計算小樣本誤報率之 95% 信賴區間，重現期末報告表 17 之數字。
3. 理解「隨機命中基準」：機動頻繁時，命中率高不代表精確度高。

執行：python training/ex05_eval_stats.py
"""
import _common  # noqa: F401
from scipy.stats import chi2


def poisson_ci(k: int, alpha: float = 0.05) -> tuple[float, float]:
    """Poisson 精確（Garwood）信賴區間，回傳事件數之下、上限。"""
    lo = 0.0 if k == 0 else chi2.ppf(alpha / 2, 2 * k) / 2
    hi = chi2.ppf(1 - alpha / 2, 2 * (k + 1)) / 2
    return lo, hi


print("① 每千星日：誤報數 ÷ 星日數 × 1000（1 顆衛星觀測 1 天＝1 星日）")
QUIET = 47_025  # IDS 15 顆衛星之營運方認證安靜期星日（期末報告表 17）
for name, k in (("阻力殘差項（安靜期內）", 4), ("L2 統計變點項（安靜期內）", 4), ("L1 候選事件（安靜期內）", 40)):
    lo, hi = poisson_ci(k)
    print(f"   {name:14s} {k:3d} 件 → 每千安靜星日 {k/QUIET*1000:.2f}"
          f"（95% 信賴區間 {lo/QUIET*1000:.2f}–{hi/QUIET*1000:.2f}）")
print("   對照表 17：阻力殘差 0.09（0.02–0.22）、L1 0.85（0.61–1.16）")

print("\n② 樣本小時，區間很寬：同樣 0.09 的比率，事件數不同時之區間")
for k, n in ((1, 11_000), (4, 47_025), (40, 470_250)):
    lo, hi = poisson_ci(k)
    print(f"   {k:3d} 件／{n:,} 星日 → {k/n*1000:.2f}（{lo/n*1000:.2f}–{hi/n*1000:.2f}）")

print("\n③ 隨機命中基準：若真值事件很密集，隨便選一個時點也很可能落在某件真值 ±24 小時內")
# 簡化示範：每顆衛星平均每 T 天一次機動，±24 小時窗共涵蓋 2 天
for T in (60, 20, 7, 3):
    cover = min(2.0 / T, 1.0)
    print(f"   平均每 {T:2d} 天一次機動 → 隨機時點命中機率約 {cover:.0%}")
print("   MEME（Starlink）實測：複核項 97.5% 落在真值 ±24h 內，隨機時點為 96.5%，兩者相近，")
print("   因此 Starlink 上複核項之精確度無法評估；誤報率改以 IDS 營運方認證安靜期評估。")
