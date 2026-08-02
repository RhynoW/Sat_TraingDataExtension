#!/usr/bin/env python3
"""分析 compare_1000sat_results.csv：一致性/交叉表/軌域分層/分歧案例。"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
df = pd.read_csv("docs/compare_1000sat_results.csv")
N = len(df)
print(f"總樣本 {N} 顆；有 error 的 {df['error'].notna().sum() if 'error' in df else 0} 顆\n")

# 完整三方法皆有旗標的子集
m = df.dropna(subset=["stat_flag", "m1_flag", "m2_flag"]).copy()
for c in ["stat_flag", "m1_flag", "m2_flag", "m2_reentry"]:
    m[c] = m[c].astype(int)
print(f"三方法皆可評估 {len(m)} 顆\n")

# ── 1. 各方法彙總 ──────────────────────────────────────────────
print("=== 1. 各方法旗標彙總 ===")
for c, lab in [("stat_flag", "統計層(named)"), ("m1_flag", "Model1 LGBM"), ("m2_flag", "Model2+NRLMSIS")]:
    print(f"  {lab:16} 旗標 {m[c].sum():4d}/{len(m)}  ({100*m[c].mean():5.1f}%)")
print(f"  統計層平均事件數/顆：cusum {m['stat_cusum_n'].mean():.2f} bocpd {m['stat_bocpd_n'].mean():.2f} "
      f"ssa {m['stat_ssa_n'].mean():.2f} mad {m['stat_mad_n'].mean():.2f}")
print(f"  Model1 p 中位 {m['m1_p'].median():.3f}；Model2 |resid|max 中位 {m['m2_resid_max'].median():.3f} km；"
      f"再入守門觸發 {m['m2_reentry'].sum()} 顆")

# ── 2. 兩兩一致性（Jaccard + Cohen's kappa）────────────────────
def jaccard(a, b):
    inter = int(((a == 1) & (b == 1)).sum()); uni = int(((a == 1) | (b == 1)).sum())
    return inter / uni if uni else float("nan")

def kappa(a, b):
    n = len(a); po = (a == b).mean()
    pa1, pb1 = a.mean(), b.mean()
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    return (po - pe) / (1 - pe) if (1 - pe) else float("nan")

print("\n=== 2. 兩兩一致性 ===")
pairs = [("stat_flag", "m1_flag", "統計層 vs Model1"),
         ("stat_flag", "m2_flag", "統計層 vs Model2"),
         ("m1_flag", "m2_flag", "Model1 vs Model2")]
for a, b, lab in pairs:
    ct = pd.crosstab(m[a], m[b])
    print(f"  {lab}: Jaccard={jaccard(m[a],m[b]):.3f}  kappa={kappa(m[a],m[b]):.3f}  一致率={100*(m[a]==m[b]).mean():.1f}%")
    print(f"     交叉表(列={a},欄={b}):\n{ct.to_string().replace(chr(10),chr(10)+'     ')}")

# 三方法一致（都判有 / 都判無）
allpos = int(((m['stat_flag']==1)&(m['m1_flag']==1)&(m['m2_flag']==1)).sum())
allneg = int(((m['stat_flag']==0)&(m['m1_flag']==0)&(m['m2_flag']==0)).sum())
print(f"\n  三方法皆判有機動：{allpos} 顆；皆判無：{allneg} 顆；至少一致(三同)={allpos+allneg} ({100*(allpos+allneg)/len(m):.1f}%)")

# 各組合計數
combo = m.groupby(["stat_flag","m1_flag","m2_flag"]).size().reset_index(name="n")
print("\n  三方法旗標組合分布：")
print(combo.to_string(index=False).replace(chr(10),chr(10)+"  "))

# ── 3. 軌域分層 ────────────────────────────────────────────────
print("\n=== 3. 軌域分層旗標率 ===")
reg = m.groupby("regime").agg(n=("norad_id","size"),
      stat=("stat_flag","mean"), m1=("m1_flag","mean"), m2=("m2_flag","mean")).reset_index()
reg[["stat","m1","m2"]] = (reg[["stat","m1","m2"]]*100).round(1)
print(reg.to_string(index=False))

# ── 4. 分歧案例 ────────────────────────────────────────────────
print("\n=== 4. 代表性分歧案例 ===")
def show(sub, title, cols):
    print(f"\n  [{title}] n={len(sub)}")
    if len(sub):
        print(sub[cols].head(5).to_string(index=False).replace(chr(10),chr(10)+"  "))

base = ["norad_id","object_name","regime","alt_km","stat_named_n","m1_p","m2_resid_max","m2_n"]
# 只有 Model2 報（阻力異常），統計層/Model1 皆無或弱
only_m2 = m[(m['m2_flag']==1)&(m['m1_flag']==0)].sort_values("m2_resid_max",ascending=False)
show(only_m2, "Model2 報 & Model1 未報（阻力殘差異常，域外 LGBM 未捕捉）", base)
# 只有 Model1 報（監督式高分），Model2 未報
only_m1 = m[(m['m1_flag']==1)&(m['m2_flag']==0)].sort_values("m1_p",ascending=False)
show(only_m1, "Model1 報 & Model2 未報（LGBM 高分但無阻力殘差訊號）", base)
# 三方法皆報（高置信機動）
allp = m[(m['stat_flag']==1)&(m['m1_flag']==1)&(m['m2_flag']==1)].sort_values("m1_p",ascending=False)
show(allp, "三方法皆報（高置信機動）", base)
# 統計層報但另兩者皆無（統計層抓小步/雜訊）
only_stat = m[(m['stat_flag']==1)&(m['m1_flag']==0)&(m['m2_flag']==0)]
show(only_stat.sort_values("stat_named_n",ascending=False), "僅統計層報（小步/雜訊敏感）", base)

# 存分歧案例 CSV
Path("docs").mkdir(exist_ok=True)
div = pd.concat([only_m2.head(20).assign(case="only_M2"),
                 only_m1.head(20).assign(case="only_M1"),
                 allp.head(20).assign(case="all_three")], ignore_index=True)
div.to_csv("docs/compare_1000sat_divergence.csv", index=False, encoding="utf-8-sig")
print("\n分歧案例 → docs/compare_1000sat_divergence.csv")
