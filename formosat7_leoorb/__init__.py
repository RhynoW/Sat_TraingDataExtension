"""福衛七號（COSMIC-2）TACC leoOrb 精密定軌取數管線。

用途：作為 TLE 誤差評估的**真值來源**。leoOrb 自身重疊一致性 3D RMS 約 0.25 m，
比待測的 TLE 誤差（km 級）小約 3000 倍。

資料服務 https://tacc.cwa.gov.tw/data-service/fs7rt_tdpc/daily_tar/ ，無需帳號，
每日約 1.4-1.6 MB，實測涵蓋 2019.274 起。

模組
----
download : TLS 相容層 + 每日包下載與快取
archive  : tar 展開、SP3 解析、單位與框架換算、自我檢核
satmap   : SP3 代號 L76-L81 <-> NORAD 對照

適用範圍
--------
由本管線導出的 TLE 誤差統計有明確的適用範圍限制（福衛七號是配合良好的操作中
衛星，是**下界不是代表值**）。五條限制寫在 repo 根目錄的 tle_ric_sigma.FS7_CAVEATS，
引用數字前務必一併閱讀。
"""

__all__ = ["download", "archive", "satmap"]
