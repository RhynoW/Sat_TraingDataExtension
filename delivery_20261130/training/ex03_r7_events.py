"""練習 3：以 R7 流程產生候選事件、證據等級與低置信複核項（需網路）

學習目標
1. 呼叫 build_report_data()（App 頁面與 PDF 報表共用之同一函式）。
2. 看懂候選事件之欄位：淨 Δa、SNR、顯著性、輔助通道、證據等級、E3 判定依據、ML 輔助上限。
3. 看懂偵測下限與低置信複核項（支線）的輸出。

執行：python training/ex03_r7_events.py [NORAD] [起日] [迄日]
預設：HAISHAO 1（62190），2025-03-01 至 2025-06-30（約 1 分鐘）
"""
import sys
from collections import Counter
from datetime import date

import _common  # noqa: F401

rb = _common.load_builder()
norad = int(sys.argv[1]) if len(sys.argv) > 1 else 62190
d0 = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date(2025, 3, 1)
d1 = date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else date(2025, 6, 30)

r = rb.build_report_data(norad, d0, d1, with_ai=False, with_external=False)
print(f"{r['name']}（NORAD {norad}），{d0} 至 {d1}；TLE {r['n_tle']} 筆、平均高度 {r['alt_km_avg']:.0f} km、"
      f"軌道 {r['orbit_class']}／{r['inc_family']}")
print(f"① L1：{r['l1']['n_transitions']} 個轉換中 {r['l1']['n_flagged']} 個規則候選點 → "
      f"合併為 {len(r['events'])} 件候選事件；等級分布 {r['counts']['grades']}")

print("\n② 候選事件")
print("   #  起始時間           淨Δa(km)   SNR  顯著性  輔助通道                  等級  E3依據  ML上限")
for e in r["events"]:
    ev = e.get("evidence") or []
    ev_s = "、".join(ev) if isinstance(ev, (list, tuple)) else str(ev)
    print(f"  {e['no']:2d}  {e['t_start']:%Y-%m-%d %H:%M}  {e['net_da']:+8.2f}  {e['snr']:5.1f}  "
          f"{str(e['significance']):5s}  {ev_s[:24]:24s}  {e['grade']:4s}  {str(e['e3_basis'] or '—'):6s}  "
          f"{'是' if e['ml_capped'] else '—'}")

cap = r["detect_cap"] or {}
if cap:
    s = cap["sigma_med_m"]
    print(f"\n③ 偵測下限：TLE 雜訊 σ = {s:.0f} m → 5σ 候選下限 {5*s:.0f} m、20σ 高顯著下限 {20*s:.0f} m")

lc = r["low_conf"] or []
print(f"\n④ 低置信複核項（支線）：{len(lc)} 項，合併為 {len({x['case'] for x in lc})} 個案件")
print("   來源分布：", dict(Counter(x["source"] for x in lc)))
print("   優先序分布：", dict(Counter(x["priority"] for x in lc)))
print("   L2 統計變點項：")
for x in [x for x in lc if str(x["source"]).startswith("L2")]:
    print(f"   {str(x['epoch'])[:16]}  {x['source']}  {x['value']}  優先序 {x['priority']}  標記 {x['tags']}")
