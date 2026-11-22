"""想定 D 的「賽後成本」：反衛星碎片在遊戲 48 小時之後還留多久（實測資料，不是遊戲模擬）。

- 低高度參考：俄羅斯 Nudol 2021-11-15 擊毀 Cosmos 1408（約 480 km）。資料取自 CelesTrak SATCAT（國際編號 1982-092，
  NORAD ≥ 49000 的碎片），與 docs/book/sim_validation/cosmos1408/ 共用同一份 CSV。
- 高高度參考：中國 2007 年擊毀退役氣象衛星（800 km 以上）：DIA 2026 p.32「超過 3,500 塊可追蹤碎片；其中超過 2,400 塊仍在軌道上」。
  這一列只引用 DIA 數字，沒有下載 SATCAT。

用法（repo 根目錄）：python docs/book/sim_wargame/scenario_d/debris_after_game.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
CSV = HERE.parents[1] / "sim_validation" / "cosmos1408" / "satcat_1982-092.csv"
T0 = pd.Timestamp("2021-11-15")
DAYS = [2, 30, 180, 365, 730, 1095, 1825]


def main():
    sc = pd.read_csv(CSV)
    deb = sc[(sc.OBJECT_TYPE == "DEB") & (sc.NORAD_CAT_ID >= 49000)].copy()
    deb["decay"] = pd.to_datetime(deb.DECAY_DATE, errors="coerce")
    n = len(deb)
    rows = []
    for d in DAYS:
        alive = ((deb.decay.isna()) | (deb.decay > T0 + pd.Timedelta(days=d))).sum()
        rows.append({"day": d, "alive": int(alive), "share": alive / n})
    out = {"source": "CelesTrak SATCAT 1982-092, DEB, NORAD>=49000", "n": n, "t0": str(T0.date()), "rows": rows,
           "fy1c_dia_p32": {"tracked": 3500, "still_in_orbit": 2400, "note": "DIA 2026 p.32：超過 3,500 塊，其中超過 2,400 塊仍在軌（資訊截止 2026-07）"}}
    (HERE / "debris_after_game.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Cosmos 1408（約 480 km）已編目碎片 {n} 件：")
    for r in rows:
        print(f"  第 {r['day']:>4} 天：仍在軌 {r['alive']:>4} 件（{r['share']:.1%}）")
    print("2007 年中國試射（800 km 以上）：3,500 塊以上，約 19 年後仍有 2,400 塊以上在軌（≈ 69%，DIA p.32）")


if __name__ == "__main__":
    main()
