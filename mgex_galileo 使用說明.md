mgex_galileo 使用說明
安裝依賴

pip install requests pandas numpy duckdb
# 若需解壓舊格式 .Z 檔（2022 年以前的資料）：
pip install unlzw3
# 若需高精度 ECEF→ECI 轉換：
pip install astropy
方法一：命令列（CLI）
1. 下載 SP3 檔案

# 下載 2023 年 1 月整月，優先用 CODE，備援 GFZ
python -m mgex_galileo.cli download \
    --start 2023-01-01 \
    --end   2023-01-31 \
    --out-dir data/mgex/sp3 \
    --ac-priority COD GFZ

# 只下載最近 7 天（GFZ rapid 比 CODE final 更快釋出）
python -m mgex_galileo.cli download \
    --start 2026-05-01 \
    --end   2026-05-07 \
    --out-dir data/mgex/sp3 \
    --ac-priority GFZ COD
2. 建立索引

# 掃描所有已下載的 SP3，建立 DuckDB 索引
python -m mgex_galileo.cli index \
    --sp3-root data/mgex/sp3 \
    --db       data/mgex/sp3_index.duckdb
3. 匯出某天的 Galileo 軌道

# 輸出為 Parquet（推薦）
python -m mgex_galileo.cli dump-day \
    --date 2023-01-15 \
    --db   data/mgex/sp3_index.duckdb \
    --out  data/mgex/galileo_2023-01-15.parquet

# 或輸出 CSV
python -m mgex_galileo.cli dump-day \
    --date 2023-01-15 \
    --db   data/mgex/sp3_index.duckdb \
    --out  data/mgex/galileo_2023-01-15.csv
加 -v 可看 debug 輸出：python -m mgex_galileo.cli -v download ...

方法二：Python API
下載

import datetime
from pathlib import Path
from mgex_galileo import download_galileo_sp3

paths = download_galileo_sp3(
    start_date   = datetime.date(2023, 1, 1),
    end_date     = datetime.date(2023, 1, 31),
    out_dir      = Path("data/mgex/sp3"),
    ac_priority  = ["COD", "GFZ"],   # None → 用預設順序
)
# paths: list[Path]，每個元素是已下載的 .SP3 檔路徑
解析單一檔案

from pathlib import Path
from mgex_galileo import parse_sp3_galileo

df = parse_sp3_galileo(Path("data/mgex/sp3/COD0MGXFIN_2023001...SP3"))

print(df.columns.tolist())
# ['sat_id', 't_gps', 'x_m', 'y_m', 'z_m',
#  'v_x_mps', 'v_y_mps', 'v_z_mps',
#  'ac', 'file_epoch_start', 'file_epoch_end']

print(df.head())
#   sat_id                     t_gps           x_m           y_m           z_m
# 0    E01 2023-01-01 00:00:00+00:00   4873408.524  23434834.842 -10481940.600
# 1    E02 2023-01-01 00:00:00+00:00  20067895.246  14765000.219  13068843.028
# ...

# 取出單顆衛星
e11 = df[df["sat_id"] == "E11"].copy()
建立索引 + 查詢

from pathlib import Path
import pandas as pd
from mgex_galileo import build_sp3_index, query_sp3_files_for_interval

# 建立索引（增量更新，重複執行安全）
sp3_files = list(Path("data/mgex/sp3").glob("**/*.SP3"))
build_sp3_index(sp3_files, Path("data/mgex/sp3_index.duckdb"))

# 查詢某時間段有哪些 SP3 覆蓋
files = query_sp3_files_for_interval(
    index_db       = Path("data/mgex/sp3_index.duckdb"),
    start_time     = pd.Timestamp("2023-01-15 00:00:00", tz="UTC"),
    end_time       = pd.Timestamp("2023-01-15 23:59:59", tz="UTC"),
    require_galileo = True,
)
# files: list[Path]
批次解析 + 合併

import pandas as pd
from mgex_galileo import parse_sp3_galileo, query_sp3_files_for_interval

files = query_sp3_files_for_interval(db, t_start, t_end)
df = pd.concat([parse_sp3_galileo(f) for f in files], ignore_index=True)
df = df.sort_values(["sat_id", "t_gps"]).reset_index(drop=True)
df.to_parquet("galileo_week.parquet", index=False)
ECEF → ECI 轉換（選用）

from mgex_galileo.sp3_parser import ecef_to_eci_galileo

# 高精度（需 astropy）
df_eci = ecef_to_eci_galileo(df, method="astropy")

# 快速近似（純 numpy，誤差 ~arcsec）
df_eci = ecef_to_eci_galileo(df, method="approx")

# 新增欄位：r_x, r_y, r_z (m)  和  v_x, v_y, v_z (m/s)  in GCRS
注意事項
項目	說明
時間欄位 t_gps	數值是 GPS time，非 UTC。GPS − UTC = 18 秒（2024）。需精確 UTC 時減去 pd.Timedelta(seconds=18)
舊資料（< 2022-11-27）	檔案為 .sp3.Z，需 pip install unlzw3，否則自動跳過改試下一個 AC
CODE final vs GFZ rapid	CODE final 延遲 ~2 週；GFZ rapid 延遲 ~1 天。近期資料建議優先 GFZ
CDDIS 鏡像	需要 NASA Earthdata 帳號，目前未內建支援；可手動下載後用 index + parse
座標單位	x_m/y_m/z_m 單位為公尺（SP3 原始 km 已轉換）；速度為 m/s