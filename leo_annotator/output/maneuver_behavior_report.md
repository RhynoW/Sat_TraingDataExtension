# LEO 衛星機動行為分析報告

**資料期間：** 2026-05-01 ～ 2026-05-22（21 天）
**分析樣本：** 1323 顆（maneuver_detected=True）
**機動偵測閾值：** Δa > 1.0 km | Δi > 0.02° | Δe > 0.001 | RAAN_res > 0.1°

## 1. 行為類別總覽

| 類別代號 | 中文名稱 | 顆數 | 佔比 |
|---------|---------|------|------|
| DragMakeup | 大氣阻力補償 | 758 | 57.3% |
| OrbitLowering | 軌道降低 / 離軌 | 252 | 19.0% |
| PhasingManeuver | 相位調整 | 91 | 6.9% |
| OrbitRaising | 軌道抬升 | 81 | 6.1% |
| Stationkeeping | 站位保持 | 69 | 5.2% |
| UnknownFP | 未知 FP | 39 | 2.9% |
| DragDecay | 大氣阻力衰減（無推進） | 21 | 1.6% |
| InclinationChange | 傾角調整 | 6 | 0.5% |
| ComplexManeuver | 複合機動 | 4 | 0.3% |
| UnknownRAANAnomaly | RAAN 異常（身份待查） | 2 | 0.2% |

## 2. 推進類別 × 行為分佈

| 推進類別 | DragMakeup | OrbitLowering | PhasingManeuver | OrbitRaising | Stationkeeping | UnknownFP | DragDecay | InclinationChange | ComplexManeuver | UnknownRAANAnomaly |
|---|---|---|---|---|---|---|---|---|---|---|
| Chemical | 13 | 1 | 0 | 2 | 0 | 0 | 0 | 0 | 1 | 0 |
| Electric_EP | 742 | 249 | 90 | 79 | 69 | 0 | 0 | 6 | 3 | 0 |
| Hybrid/Other | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Micro/ColdGas | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 未標註 | 0 | 0 | 0 | 0 | 0 | 39 | 21 | 0 | 0 | 2 |

## 3. 各行為類別詳細說明與代表案例

### 3.1 DragMakeup（大氣阻力補償）— 758 顆

**說明：** 電推或小推力系統持續補償大氣阻力造成的軌道衰減，da 呈現週期性小幅正向修正，累積 da 接近零或微正。

- 平均 |Δa| 最大值：3.19 km
- 平均淨 Δa（21 天）：-6.79 km
- 平均旗標次數：3.8 次
- 平均旗標率（flags/transitions）：8.7%
- 平均軌道高度（SMA）：479 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 64543 | W-SERIES 4 | Chemical | -74.2 | 63.94 | 5 | da+de |
| 63785 | STARLINK-33906 | Electric_EP | -75.7 | 30.44 | 11 | da |
| 45057 | STARLINK-1159 | Electric_EP | -94.8 | 29.82 | 13 | da |
| 46462 | JILIN-01 GAOFEN 3J | Electric_EP | -117.0 | 27.99 | 32 | da |
| 59615 | STARLINK-31761 | Electric_EP | -55.6 | 26.66 | 14 | da |
| 46558 | STARLINK-1680 | Electric_EP | -96.2 | 22.16 | 19 | da |
| 63876 | STARLINK-34061 | Electric_EP | -166.9 | 20.47 | 31 | da |
| 56195 | GHOST-1 | Hybrid/Other | -59.9 | 19.76 | 7 | da |
| 63457 | STARLINK-33795 | Electric_EP | +0.1 | 14.52 | 5 | da+de |
| 47573 | STARLINK-1975 | Electric_EP | -50.4 | 12.75 | 7 | da |
| 57076 | STARLINK-6155 | Electric_EP | -2.5 | 12.43 | 5 | da+de |
| 48641 | STARLINK-2754 | Electric_EP | +0.0 | 12.12 | 4 | da+de |
| 53044 | STARLINK-4349 | Electric_EP | -59.4 | 11.78 | 11 | da |
| 48576 | STARLINK-2228 | Electric_EP | +0.0 | 11.68 | 4 | da+de |
| 48655 | STARLINK-2657 | Electric_EP | +0.0 | 11.61 | 4 | da |
| … | （另 743 顆） | | | | | |

### 3.2 OrbitLowering（軌道降低 / 離軌）— 252 顆

**說明：** 衛星執行主動降軌或離軌機動，半長軸淨減 >5 km。可能為任務結束降軌、再入燃燒或碰撞規避後的軌道修正。

- 平均 |Δa| 最大值：5.73 km
- 平均淨 Δa（21 天）：-13.09 km
- 平均旗標次數：3.4 次
- 平均旗標率（flags/transitions）：7.8%
- 平均軌道高度（SMA）：464 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 47487 | ASTROCAST-0103 | Micro/ColdGas | -47.7 | 34.64 | 3 | da |
| 62447 | STARLINK-32730 | Electric_EP | -60.2 | 20.94 | 8 | da |
| 64772 | STARLINK-34652 | Electric_EP | -9.9 | 17.39 | 9 | da+de |
| 64106 | STARLINK-33970 | Electric_EP | -9.9 | 17.12 | 6 | da+de |
| 55340 | STARLINK-5675 | Electric_EP | -18.5 | 13.46 | 4 | da+de |
| 65825 | STARLINK-35397 | Electric_EP | -12.4 | 12.81 | 3 | da |
| 64439 | STARLINK-34456 | Electric_EP | -12.4 | 12.47 | 1 | da |
| 65863 | STARLINK-35469 | Electric_EP | -12.5 | 12.46 | 1 | da |
| 46699 | STARLINK-1799 | Electric_EP | -34.1 | 12.16 | 5 | da |
| 65878 | STARLINK-35453 | Electric_EP | -12.6 | 12.15 | 1 | da |
| 58106 | STARLINK-30612 | Electric_EP | -12.4 | 12.14 | 2 | da+draan |
| 64441 | STARLINK-34453 | Electric_EP | -12.4 | 12.07 | 1 | da |
| 64780 | STARLINK-34491 | Electric_EP | -12.5 | 11.75 | 1 | da |
| 64097 | STARLINK-34174 | Electric_EP | -12.5 | 11.72 | 1 | da |
| 63032 | STARLINK-32776 | Electric_EP | -12.4 | 11.60 | 1 | da |
| … | （另 237 顆） | | | | | |

### 3.3 PhasingManeuver（相位調整）— 91 顆

**說明：** 少量旗標（≤3 次）但 da 幅度大，表示衛星在短時間內執行一次或數次明顯的軌道相位調整，後續軌道趨於穩定。

- 平均 |Δa| 最大值：7.21 km
- 平均淨 Δa（21 天）：-0.21 km
- 平均旗標次數：2.2 次
- 平均旗標率（flags/transitions）：5.1%
- 平均軌道高度（SMA）：502 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 57077 | STARLINK-6194 | Electric_EP | +2.5 | 14.35 | 3 | da |
| 65826 | STARLINK-35381 | Electric_EP | +0.1 | 12.96 | 2 | da |
| 64117 | STARLINK-34122 | Electric_EP | -4.4 | 12.63 | 3 | da+de |
| 57104 | STARLINK-6130 | Electric_EP | +0.1 | 12.47 | 2 | da+de |
| 63433 | STARLINK-33682 | Electric_EP | -0.1 | 11.65 | 3 | da+de |
| 60283 | STARLINK-32037 | Electric_EP | -0.0 | 11.61 | 2 | da |
| 48107 | STARLINK-2443 | Electric_EP | -0.3 | 11.57 | 2 | da+de |
| 65462 | STARLINK-35180 | Electric_EP | -0.0 | 11.57 | 2 | da+de |
| 62784 | STARLINK-33581 | Electric_EP | +0.1 | 11.54 | 2 | da+de |
| 65919 | STARLINK-35519 | Electric_EP | -0.0 | 11.54 | 2 | da+de |
| 64111 | STARLINK-34148 | Electric_EP | +0.1 | 11.04 | 2 | da |
| 59379 | STARLINK-31698 | Electric_EP | +0.1 | 11.02 | 2 | da+de |
| 65480 | STARLINK-35040 | Electric_EP | -3.9 | 10.14 | 3 | da+de |
| 58947 | STARLINK-31116 | Electric_EP | -0.0 | 10.04 | 2 | da+de |
| 65876 | STARLINK-34438 | Electric_EP | +0.0 | 10.03 | 3 | da+de |
| … | （另 76 顆） | | | | | |

### 3.4 OrbitRaising（軌道抬升）— 81 顆

**說明：** 衛星執行主動升軌機動，半長軸淨增 >5 km。常見於新星座部署、任務相位調整或規避目標後返回工作軌道。

- 平均 |Δa| 最大值：8.59 km
- 平均淨 Δa（21 天）：+31.38 km
- 平均旗標次數：11.1 次
- 平均旗標率（flags/transitions）：19.7%
- 平均軌道高度（SMA）：493 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 66628 | STARLINK-35862 | Electric_EP | +22.9 | 23.01 | 1 | da |
| 66625 | STARLINK-35929 | Electric_EP | +22.9 | 22.17 | 1 | da |
| 67873 | STARLINK-36783 | Electric_EP | +23.1 | 21.79 | 2 | da |
| 66631 | STARLINK-35965 | Electric_EP | +19.9 | 20.10 | 1 | da |
| 66637 | STARLINK-35953 | Electric_EP | +19.8 | 20.09 | 1 | da |
| 66633 | STARLINK-35948 | Electric_EP | +19.9 | 20.06 | 1 | da |
| 66623 | STARLINK-35920 | Electric_EP | +19.9 | 20.03 | 1 | da |
| 67858 | STARLINK-36837 | Electric_EP | +23.1 | 20.02 | 5 | da |
| 66643 | STARLINK-35918 | Electric_EP | +23.0 | 20.00 | 3 | da |
| 66632 | STARLINK-35973 | Electric_EP | +22.9 | 19.66 | 2 | da |
| 54847 | STARLINK-5061 | Electric_EP | +17.3 | 19.55 | 9 | da+de+draan |
| 66634 | STARLINK-35967 | Electric_EP | +22.9 | 19.49 | 2 | da |
| 68040 | STARLINK-36711 | Electric_EP | +22.2 | 19.29 | 2 | da |
| 67788 | KUIPER-00262 | Electric_EP | +64.0 | 14.78 | 35 | da+di |
| 63710 | STARLINK-33920 | Electric_EP | +7.9 | 12.39 | 2 | da+de |
| … | （另 66 顆） | | | | | |

### 3.5 Stationkeeping（站位保持）— 69 顆

**說明：** 衛星在觀測窗口內頻繁執行小幅機動（旗標率 >25%），維持精確工作軌道高度或相位。典型於 EO/SAR 星座的重訪週期維持。

- 平均 |Δa| 最大值：4.87 km
- 平均淨 Δa（21 天）：+0.11 km
- 平均旗標次數：7.7 次
- 平均旗標率（flags/transitions）：16.4%
- 平均軌道高度（SMA）：529 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 61664 | STARLINK-32301 | Electric_EP | -0.1 | 11.55 | 7 | da |
| 66152 | STARLINK-35455 | Electric_EP | +0.0 | 11.18 | 7 | da+de |
| 48375 | STARLINK-2603 | Electric_EP | -2.4 | 11.07 | 9 | da+de |
| 64276 | STARLINK-34350 | Electric_EP | +0.1 | 9.47 | 8 | da+de |
| 64295 | STARLINK-34424 | Electric_EP | -0.1 | 9.01 | 11 | da |
| 58157 | STARLINK-30803 | Electric_EP | -0.0 | 8.08 | 10 | da+de |
| 63872 | STARLINK-34059 | Electric_EP | +0.0 | 7.38 | 9 | da+de |
| 63877 | STARLINK-33778 | Electric_EP | +0.5 | 6.99 | 9 | da+de |
| 55783 | STARLINK-5825 | Electric_EP | -0.1 | 6.68 | 7 | da |
| 55744 | STARLINK-5601 | Electric_EP | +0.1 | 6.61 | 15 | da |
| 55742 | STARLINK-5594 | Electric_EP | +0.0 | 6.58 | 11 | da+de |
| 55663 | STARLINK-5473 | Electric_EP | +0.0 | 6.55 | 10 | da |
| 55293 | STARLINK-5287 | Electric_EP | -2.8 | 6.55 | 9 | da |
| 63082 | STARLINK-32933 | Electric_EP | +0.9 | 6.37 | 8 | da |
| 64036 | STARLINK-34085 | Electric_EP | +0.1 | 6.24 | 11 | da |
| … | （另 54 顆） | | | | | |

### 3.6 UnknownFP（未知 FP）— 39 顆

**說明：** 無推進標註但觸發機動旗標，可能為資料噪聲、TLE 品質問題或推進系統標註遺漏。

- 平均 |Δa| 最大值：2.77 km
- 平均淨 Δa（21 天）：-7.74 km
- 平均旗標次數：1.9 次
- 平均旗標率（flags/transitions）：8.6%
- 平均軌道高度（SMA）：395 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 62693 | SKYLINK-1 | — | -29.6 | 22.00 | 2 | da |
| 51657 | INSPIRESAT-1 | — | -26.6 | 15.60 | 2 | da |
| 63492 | HADES-ICM (SO-125) | — | -39.2 | 9.25 | 11 | da |
| 51844 | OBJECT W | — | -7.1 | 7.15 | 1 | da |
| 57037 | OBJECT AK | — | +1.3 | 5.17 | 2 | da |
| 63992 | OBJECT L | — | +1.9 | 2.79 | 1 | da |
| 59806 | OBJECT B | — | +2.2 | 2.63 | 1 | da |
| 58503 | OBJECT B | — | -15.8 | 2.38 | 5 | da |
| 58467 | LILIUM-1 | — | -20.3 | 2.18 | 6 | da |
| 58555 | HONGHU 2 | — | -10.4 | 2.04 | 1 | da |
| 63431 | HJS-6D | — | +10.1 | 2.03 | 4 | da |
| 63430 | HJS-6C | — | +9.9 | 1.98 | 4 | da |
| 44537 | ZHUHAI-1 03C | — | -20.5 | 1.91 | 2 | da |
| 64573 | MUSAT3 | — | -2.6 | 1.81 | 1 | da |
| 63429 | HJS-6B | — | +10.0 | 1.78 | 3 | da |
| … | （另 24 顆） | | | | | |

### 3.7 DragDecay（大氣阻力衰減（無推進））— 21 顆

**說明：** 無推進衛星在低軌道因大氣阻力導致半長軸持續單調下降，非主動機動，為 FP 誤判目標。

- 平均 |Δa| 最大值：9.87 km
- 平均淨 Δa（21 天）：-50.40 km
- 平均旗標次數：10.6 次
- 平均旗標率（flags/transitions）：40.1%
- 平均軌道高度（SMA）：286 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 61782 | TUSUR GO | — | -113.0 | 34.90 | 16 | da |
| 43805 | AL FARABI 2 | — | -111.5 | 30.35 | 17 | da |
| 66907 | RHOK-SAT | — | -80.6 | 24.75 | 11 | da |
| 57323 | STRATOSAT-TK1-E | — | -132.4 | 24.11 | 13 | da |
| 60557 | CELESTIS 24/TROOP-F2 | — | -101.2 | 23.65 | 23 | da |
| 66908 | CU-ALPHA | — | -57.7 | 14.64 | 7 | da |
| 60502 | FLOCK 4BE 33 | — | -79.6 | 10.60 | 17 | da |
| 61757 | HORIZON GORIZONT | — | -63.0 | 9.04 | 20 | da |
| 54691 | OBJECT K | — | -65.5 | 8.24 | 18 | da |
| 66910 | EAGLESAT-2 | — | -48.2 | 4.82 | 14 | da |
| 51841 | OBJECT T | — | -19.2 | 2.73 | 3 | da |
| 57326 | STRATOSAT-TK1-D | — | -16.5 | 2.56 | 8 | da |
| 47958 | KMSL | — | -16.9 | 2.42 | 9 | da |
| 59812 | OBJECT C | — | -24.4 | 2.11 | 9 | da |
| 58665 | MDQUBESAT-2 | — | -18.8 | 2.10 | 8 | da |
| … | （另 6 顆） | | | | | |

### 3.8 InclinationChange（傾角調整）— 6 顆

**說明：** 僅 di 旗標觸發，衛星執行軌道傾角變更，典型於任務轉換或初始部署後的面調整。

- 平均 |Δa| 最大值：0.14 km
- 平均淨 Δa（21 天）：+0.13 km
- 平均旗標次數：1.7 次
- 平均旗標率（flags/transitions）：4.7%
- 平均軌道高度（SMA）：471 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 62890 | STARLINK-11431 | Electric_EP | +0.8 | 0.29 | 1 | di |
| 59857 | STARLINK-31569 | Electric_EP | -0.0 | 0.23 | 2 | di+de |
| 62209 | STARLINK-32671 | Electric_EP | -0.0 | 0.18 | 2 | di |
| 52659 | STARLINK-3960 | Electric_EP | -0.0 | 0.07 | 2 | di |
| 67118 | STARLINK-35701 | Electric_EP | -0.1 | 0.05 | 2 | di |
| 58231 | STARLINK-30867 | Electric_EP | +0.1 | 0.02 | 1 | di |

### 3.9 ComplexManeuver（複合機動）— 4 顆

**說明：** 同時觸發 da 與 di 旗標，衛星在觀測期間執行了包含軌道面變換在內的複合機動。

- 平均 |Δa| 最大值：11.50 km
- 平均淨 Δa（21 天）：-0.82 km
- 平均旗標次數：10.2 次
- 平均旗標率（flags/transitions）：19.8%
- 平均軌道高度（SMA）：506 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 55786 | STARLINK-5823 | Electric_EP | -0.1 | 22.27 | 18 | da+di+de+draan |
| 56105 | STARLINK-6066 | Electric_EP | -2.5 | 19.78 | 17 | da+di+de+draan |
| 62673 | IMPULSE-2 MIRA | Chemical | +3.7 | 2.52 | 2 | da+di+draan |
| 47831 | STARLINK-2420 | Electric_EP | -4.5 | 1.42 | 4 | da+di |

### 3.10 UnknownRAANAnomaly（RAAN 異常（身份待查））— 2 顆

**說明：** 觸發 RAAN 殘差但無 da/di，物體身份或推進系統不確定，需進一步研究。

- 平均 |Δa| 最大值：0.02 km
- 平均淨 Δa（21 天）：-0.24 km
- 平均旗標次數：26.0 次
- 平均旗標率（flags/transitions）：43.0%
- 平均軌道高度（SMA）：551 km

**代表衛星：**

| NORAD | 衛星名稱 | 推進類別 | 淨Δa (km) | |Δa|max (km) | 旗標數 | 觸發維度 |
|-------|---------|---------|-----------|----------|--------|---------|
| 49954 | IXPE | — | -0.4 | 0.02 | 42 | draan |
| 42921 | ORS 5 SENSORSAT | — | -0.1 | 0.02 | 10 | draan |

## 4. 特殊案例分析

### 4.1 半長軸最大變化量（前 5 顆）

| norad_id | sat_name | propulsion_class | behavior | max_da_km | net_da_km | n_flagged |
|---|---|---|---|---|---|---|
| 64543 | W-SERIES 4 | Chemical | DragMakeup | 63.94 | -74.16 | 5 |
| 61782 | TUSUR GO | None | DragDecay | 34.903 | -112.98 | 16 |
| 47487 | ASTROCAST-0103 | Micro/ColdGas | OrbitLowering | 34.642 | -47.69 | 3 |
| 63785 | STARLINK-33906 | Electric_EP | DragMakeup | 30.441 | -75.67 | 11 |
| 43805 | AL FARABI 2 | None | DragDecay | 30.35 | -111.47 | 17 |

### 4.2 旗標次數最多（前 5 顆）

| norad_id | sat_name | propulsion_class | behavior | n_flagged | flag_rate | max_da_km |
|---|---|---|---|---|---|---|
| 49954 | IXPE | None | UnknownRAANAnomaly | 42 | 0.656 | 0.022 |
| 67784 | KUIPER-00225 | Electric_EP | OrbitRaising | 40 | 0.645 | 8.794 |
| 67786 | KUIPER-00259 | Electric_EP | OrbitRaising | 40 | 0.645 | 7.114 |
| 67782 | KUIPER-00222 | Electric_EP | OrbitRaising | 39 | 0.629 | 6.026 |
| 67787 | KUIPER-00260 | Electric_EP | OrbitRaising | 38 | 0.613 | 9.134 |

### 4.3 高頻機動衛星（>1 次/天，前 10 顆）

| norad_id | sat_name | propulsion_class | behavior | burn_freq_per_day | n_flagged |
|---|---|---|---|---|---|
| 49954 | IXPE | None | UnknownRAANAnomaly | 2.0 | 42 |
| 67786 | KUIPER-00259 | Electric_EP | OrbitRaising | 1.905 | 40 |
| 67784 | KUIPER-00225 | Electric_EP | OrbitRaising | 1.905 | 40 |
| 67782 | KUIPER-00222 | Electric_EP | OrbitRaising | 1.857 | 39 |
| 67787 | KUIPER-00260 | Electric_EP | OrbitRaising | 1.81 | 38 |
| 54080 | STARLINK-5160 | Electric_EP | DragMakeup | 1.714 | 36 |
| 62823 | STARLINK-32823 | Electric_EP | DragMakeup | 1.667 | 35 |
| 67788 | KUIPER-00262 | Electric_EP | OrbitRaising | 1.667 | 35 |
| 54837 | STARLINK-5369 | Electric_EP | DragMakeup | 1.619 | 34 |
| 67153 | KUIPER-00248 | Electric_EP | OrbitRaising | 1.571 | 33 |

## 5. 殘餘 FP 分析（無推進標註但觸發機動旗標）

共 62 顆殘餘 FP，細分如下：

| 子類別 | 顆數 | 主要特徵 |
|-------|------|---------|
| 未知 FP | 39 | 無推進標註但觸發機動旗標，可能為資料噪聲、TLE 品質問題或推進系統標註遺漏。… |
| 大氣阻力衰減（無推進） | 21 | 無推進衛星在低軌道因大氣阻力導致半長軸持續單調下降，非主動機動，為 FP 誤判目標。… |
| RAAN 異常（身份待查） | 2 | 觸發 RAAN 殘差但無 da/di，物體身份或推進系統不確定，需進一步研究。… |

**殘餘 FP 完整列表：**

| NORAD | 衛星名稱 | 行為 | |Δa|max (km) | 旗標數 | 觸發 |
|-------|---------|------|----------|--------|------|
| 61782 | TUSUR GO | 大氣阻力衰減（無推進） | 34.90 | 16 | da |
| 43805 | AL FARABI 2 | 大氣阻力衰減（無推進） | 30.35 | 17 | da |
| 66907 | RHOK-SAT | 大氣阻力衰減（無推進） | 24.75 | 11 | da |
| 57323 | STRATOSAT-TK1-E | 大氣阻力衰減（無推進） | 24.11 | 13 | da |
| 60557 | CELESTIS 24/TROOP-F2 | 大氣阻力衰減（無推進） | 23.65 | 23 | da |
| 62693 | SKYLINK-1 | 未知 FP | 22.00 | 2 | da |
| 51657 | INSPIRESAT-1 | 未知 FP | 15.60 | 2 | da |
| 66908 | CU-ALPHA | 大氣阻力衰減（無推進） | 14.64 | 7 | da |
| 60502 | FLOCK 4BE 33 | 大氣阻力衰減（無推進） | 10.60 | 17 | da |
| 63492 | HADES-ICM (SO-125) | 未知 FP | 9.25 | 11 | da |
| 61757 | HORIZON GORIZONT | 大氣阻力衰減（無推進） | 9.04 | 20 | da |
| 54691 | OBJECT K | 大氣阻力衰減（無推進） | 8.24 | 18 | da |
| 51844 | OBJECT W | 未知 FP | 7.15 | 1 | da |
| 57037 | OBJECT AK | 未知 FP | 5.17 | 2 | da |
| 66910 | EAGLESAT-2 | 大氣阻力衰減（無推進） | 4.82 | 14 | da |
| 63992 | OBJECT L | 未知 FP | 2.79 | 1 | da |
| 51841 | OBJECT T | 大氣阻力衰減（無推進） | 2.73 | 3 | da |
| 59806 | OBJECT B | 未知 FP | 2.63 | 1 | da |
| 57326 | STRATOSAT-TK1-D | 大氣阻力衰減（無推進） | 2.56 | 8 | da |
| 47958 | KMSL | 大氣阻力衰減（無推進） | 2.42 | 9 | da |
| 58503 | OBJECT B | 未知 FP | 2.38 | 5 | da |
| 58467 | LILIUM-1 | 未知 FP | 2.18 | 6 | da |
| 59812 | OBJECT C | 大氣阻力衰減（無推進） | 2.11 | 9 | da |
| 58665 | MDQUBESAT-2 | 大氣阻力衰減（無推進） | 2.10 | 8 | da |
| 58319 | FLOCK 4Q 15 | 大氣阻力衰減（無推進） | 2.07 | 5 | da |
| 58555 | HONGHU 2 | 未知 FP | 2.04 | 1 | da |
| 63431 | HJS-6D | 未知 FP | 2.03 | 4 | da |
| 63430 | HJS-6C | 未知 FP | 1.98 | 4 | da |
| 44537 | ZHUHAI-1 03C | 未知 FP | 1.91 | 2 | da |
| 43184 | LEMUR 2 KADI | 大氣阻力衰減（無推進） | 1.85 | 4 | da |
| 64573 | MUSAT3 | 未知 FP | 1.81 | 1 | da |
| 62393 | OBJECT S | 大氣阻力衰減（無推進） | 1.80 | 5 | da |
| 63429 | HJS-6B | 未知 FP | 1.78 | 3 | da |
| 61762 | ARCTICSAT-1 | 大氣阻力衰減（無推進） | 1.70 | 4 | da |
| 63987 | OBJECT F | 未知 FP | 1.49 | 2 | da |
| 51846 | OBJECT Y | 未知 FP | 1.47 | 1 | da |
| 58272 | TIGER-6 | 大氣阻力衰減（無推進） | 1.45 | 3 | da |
| 63982 | OBJECT A | 未知 FP | 1.44 | 1 | da |
| 58313 | FLOCK 4Q 20 | 大氣阻力衰減（無推進） | 1.43 | 8 | da |
| 51839 | OBJECT R | 未知 FP | 1.42 | 2 | da |
| 61440 | H-2A R/B | 未知 FP | 1.34 | 1 | da |
| 67482 | OBJECT BE | 未知 FP | 1.29 | 1 | da |
| 46461 | JILIN-01 GAOFEN 3I | 未知 FP | 1.27 | 1 | da |
| 53450 | OBJECT G | 未知 FP | 1.21 | 2 | da |
| 67751 | OBJECT F | 未知 FP | 1.17 | 1 | da |
| 66912 | CONTENTCUBE | 未知 FP | 1.14 | 1 | da |
| 41340 | HORYU 4 | 未知 FP | 1.14 | 1 | da |
| 62643 | FLOCK 4G 32 | 未知 FP | 1.14 | 1 | da |
| 66298 | SEMI-1P | 未知 FP | 1.12 | 1 | da |
| 39472 | SMDC ONE 2.4 | 未知 FP | 1.12 | 1 | da |
| 58329 | FLOCK 4Q 21 | 未知 FP | 1.09 | 2 | da |
| 44495 | BRO-1 | 未知 FP | 1.05 | 1 | da |
| 56185 | BRO-9 | 未知 FP | 1.04 | 1 | da |
| 60558 | FLOCK 4BE 35 | 未知 FP | 1.04 | 1 | da |
| 51948 | OBJECT C | 未知 FP | 1.03 | 1 | da |
| 60484 | FLOCK 4BE 26 | 未知 FP | 1.02 | 1 | da |
| 63292 | OBJECT B | 未知 FP | 1.01 | 1 | da |
| 65489 | OBJECT-B | 未知 FP | 1.00 | 3 | da+di+de+draan |
| 46818 | CE-SAT IIB | 未知 FP | 1.00 | 1 | da |
| 64231 | GLOBAL-32 | 未知 FP | 0.11 | 1 | di |
| 49954 | IXPE | RAAN 異常（身份待查） | 0.02 | 42 | draan |
| 42921 | ORS 5 SENSORSAT | RAAN 異常（身份待查） | 0.02 | 10 | draan |

## 6. 訓練資料建議

### 6.1 高品質正例（TP）建議使用策略

| 行為類別 | 推薦使用 | 建議標籤 |
|---------|---------|---------|
| OrbitRaising | ✅ 高信心 | `maneuver=True, type=raising` |
| OrbitLowering | ✅ 高信心 | `maneuver=True, type=lowering` |
| PhasingManeuver | ✅ 高信心 | `maneuver=True, type=phasing` |
| ComplexManeuver | ✅ 中信心 | `maneuver=True, type=complex` |
| Stationkeeping | ✅ 中信心 | `maneuver=True, type=stationkeeping` |
| DragMakeup | ⚠️ 低信心 | `maneuver=True, type=drag_makeup (區分困難)` |
| DragDecay | ❌ 排除 | `非機動，建議從 TP 集移除` |
| UnknownFP | ❌ 排除或查明 | `身份未確認，不納入訓練` |

### 6.2 Recall 偏低原因分析

本次驗證 Recall ≈ 12.4%，主要原因：

1. **觀測窗口短（21 天）**：電推衛星每次燃燒僅 1–3 km，21 天內不一定執行機動。
2. **閾值偏高**：THR_DA_SM=1.0 km 過濾掉微小機動；低軌 Starlink 電推量約 0.1–0.5 km/burn。
3. **TLE 更新頻率不足**：機動發生於兩個 TLE epoch 之間無法偵測。
4. **多機動抵消**：升軌後降軌的累積 da 趨近零，被視為無機動。

---
*Generated by analyze_maneuver_behavior.py — 分析日期：2026-05-01～2026-05-22*