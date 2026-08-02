# 以 DORIS 認證安靜期實測低軌 TLE 半長軸雜訊底及其高度相依性——兼論福衛系列之機動觀測與推導

**Empirical Semi-Major-Axis Noise Floor of TLE from DORIS-Certified Quiescent Arcs and its Altitude Dependence, with Application to FORMOSAT Maneuver Detection**

作者：（待填）　　機構：（待填）　　通訊：（待填）
會議：（待填）　　主題領域：太空態勢感知（SSA）／軌道動力學

---

## 摘要

雙行軌道根數（TLE）廣泛用於低軌（LEO）衛星機動偵測，然其半長軸（SMA, *a*）之「純雜訊底」長期以合成注入假設值代替，缺乏在 800 km 以上、由操作方認證「保證無機動」期間之實測校準。本文選取 IDS（International DORIS Service）精密測高衛星，利用其操作方公布之點火日誌界定「認證安靜期」，於安靜弧段內以「相鄰差分」與「去趨勢殘差」兩種抗趨勢法穩健估計 TLE 半長軸雜訊 σ。實測顯示：涵蓋 719–1338 km 之七顆測高衛星，σ 中位僅 **≈0.3 m**，最佳者（Jason-3、Sentinel-6A）低至 **0.1 m**，較低軌 Starlink 帶（~350–550 km，σ≈24–75 m）小 **1/80–1/250**。此結果證明 TLE 半長軸雜訊底**強烈隨高度變化**，主控因子為大氣阻力所引致之未建模密度擾動；同時揭示既有偵測門檻表在高高度帶（假設 σ=50 m）高估雜訊達兩個數量級。作為在地應用，本文以福衛系列驗證此雜訊底：福衛三號（788 km、無推進）安靜段 σ_diff≈0.8–1.1 m 作為對照；福衛五號（723 km）近一年偵得 4 次 |Δa|>50 m 之明確機動（最大 798 m，推得 Δv≈0.42 m/s），訊噪比遠高於雜訊底而可穩健觀測與 Δv 反演。本文據此主張：機動偵測門檻應以**高度相依之 σ 正規化**取代固定絕對值。

**關鍵詞**：兩行軌道根數（TLE）、半長軸雜訊、精密定軌、DORIS、機動偵測、福衛、太空態勢感知

## Abstract

Two-Line Elements (TLE) are widely used for low-Earth-orbit (LEO) maneuver detection, yet the *pure noise floor* of the TLE-derived semi-major axis (SMA) has historically been assumed from synthetic injection rather than measured, and was never calibrated above ~800 km. We use IDS (International DORIS Service) precise altimetry satellites, whose operators publish thrust logs that certify quiescent (maneuver-free) arcs, to measure the TLE-SMA noise σ during those arcs using two trend-immune estimators (adjacent differencing and detrended residuals). Across seven altimetry satellites spanning 719–1338 km, the median σ is **≈0.3 m** (as low as **0.1 m** for Jason-3 and Sentinel-6A), i.e. **80–250× smaller** than the Starlink band (~350–550 km, σ≈24–75 m). The floor is thus strongly **altitude-dependent**, driven by drag-induced unmodeled density variation, and prior threshold tables over-estimate the high-altitude σ (assumed 50 m) by two orders of magnitude. As a regional application, FORMOSAT satellites confirm the floor: FORMOSAT-3 (788 km, no propulsion) yields σ_diff≈0.8–1.1 m as a control, while FORMOSAT-5 (723 km) shows 4 clear maneuvers (>50 m, max 798 m → Δv≈0.42 m/s) at very high SNR. We argue that maneuver-detection thresholds should be **altitude-dependent, σ-normalized** rather than fixed absolute values.

---

## 1. 前言與研究動機

低軌機動偵測的常見管線，以連續 TLE 之半長軸 *a* 的階梯跳變 |Δ*a*| 作為主判量。判定「這是機動、非雜訊」的關鍵，在於**雜訊底 σ**：唯有當 |Δ*a*| 顯著大於 σ（訊噪比 SNR≫1）時，跳變才可歸因於推進。

然而現行門檻設定普遍存在兩個問題：

1. **雜訊底來自合成假設而非實測**。既有門檻表（本文稱「表 11」）對 >700 km 帶採 σ=0.05 km（50 m），該值源自合成注入，且**從未在 800 km 以上以真實資料校準**（過去最高僅到福衛三號的 789 km）。
2. **忽略雜訊底的高度相依性**。低軌大氣密度隨高度近指數衰減，阻力所引致的未建模 *a* 擾動理應隨高度巨幅下降；以單一絕對門檻套用全高度帶，將在高軌過度保守、在低軌過度靈敏。

要真正量測「純雜訊底」，需一組滿足兩條件的衛星：**(i) 精密定軌、(ii) 操作方認證的無機動期間**。IDS（International DORIS Service）之測高衛星恰好同時滿足——DORIS 系統為其提供公分級精密定軌，且各任務操作方公布點火日誌，兩次機動之間即為「認證安靜期」，期間 TLE 半長軸的任何變化**皆為純雜訊**。

本文即以此為工具，實測 719–1338 km 帶之 TLE 半長軸雜訊底，量化其高度相依性，並將所得之高度—σ 關係回饋至在地的福衛系列機動觀測與 Δv 推導。

## 2. 資料與方法

### 2.1 認證安靜期之來源

安靜期取自 IDS/操作方之機動日誌（`ids_quiet.csv`，欄位 `quiet_start_tai`／`quiet_end_tai`，時間為 TAI，轉換為 UTC 時扣除 TAI–UTC=37 s）。每一區間為「操作方保證無點火」之弧段。為避開機動前後暫態，於每段兩端各內縮 **0.75 天**；並要求每段至少 **12 個可用點**、跨度至少 **3 天**。

TLE 半長軸取自本地 `space_db.duckdb` 之 `raw_tle_archive`（由 Space-Track gp_history 匯入）。為消除重複與近重複 epoch（會使穩健統計假性偏小），先以 **≥3 小時**間隔稀釋序列。

### 2.2 抗趨勢之雜訊估計（trend-immune）

安靜段內 *a* 仍含大氣阻力造成的慢變趨勢，須先消去，殘差方為雜訊。採兩獨立估計互為交叉驗證：

- **去趨勢殘差法（主）**：於段內以多項式擬合（跨度 <10 d 取一次、<40 d 取二次、否則三次）消去阻力慢變曲率，殘差之穩健標準差
  $$\sigma_{\text{res}} = 1.4826 \cdot \mathrm{median}\big(|a_i - \hat a_i|\big)$$
- **相鄰差分法（交叉驗證）**：相鄰 *a* 差分消去趨勢，
  $$\sigma_{\text{diff}} = \frac{1.4826 \cdot \mathrm{median}\big(|\,a_{i+1}-a_i\,|\big)}{\sqrt{2}}$$

其中 1.4826 為 MAD→σ 之常態換算係數，$\sqrt 2$ 修正差分之變異加倍。兩法一致即判可信。

### 2.3 對照基準

以既有門檻表之高度分帶假設值為對照：<450 km 取 0.15 km、<700 km 取 0.08 km、≥700 km 取 0.05 km（即 150/80/50 m）。

## 3. 結果：TLE 半長軸雜訊底與高度相依性

表 1 為各測高衛星於認證安靜期之實測 σ。凡安靜段內 TLE 不足者（Envisat、HY-2A、Jason-1/2）略去。

**表 1　IDS 測高衛星 TLE 半長軸雜訊實測（認證安靜期）**

| 衛星 | NORAD | 高度 (km) | 安靜段數 | 點數 | σ_res (m) | σ_diff (m) | 表 11 假設 (m) | 實測/表 11 |
|---|---|---|---|---|---|---|---|---|
| CryoSat-2 | 36508 | 719 | 3 | 252 | 0.8 | **0.3** | 50 | 0.016 |
| SARAL | 39086 | 782 | 1 | 280 | 1.0 | **0.2** | 50 | 0.020 |
| Sentinel-3A | 41335 | 803 | 4 | 310 | 0.5 | **0.2** | 50 | 0.009 |
| Sentinel-3B | 43437 | 803 | 4 | 230 | 0.4 | **0.3** | 50 | 0.009 |
| HY-2C | 46469 | 952 | 23 | 2575 | 0.6 | **0.3** | 50 | 0.011 |
| HY-2D | 49206 | 1190 | 1 | 49 | 42.7 | 1.6 | 50 | 0.853 |
| Jason-3 | 41240 | 1311 | 3 | 246 | 0.2 | **0.1** | 50 | 0.004 |
| Sentinel-6A | 46984 | 1338 | 1 | 113 | 0.1 | **0.1** | 50 | 0.003 |
| SWOT | 55160 | 1194 | 2 | 131 | 2.6 | 1.2 | 50 | 0.053 |

> 註：HY-2D、SWOT 因安靜段數少（1–2 段）、點數偏低，σ 估計較不穩健，故不列入下述「良好取樣」之七顆統計。

![圖 1　TLE 半長軸純雜訊底隨高度之關係（DORIS 認證安靜期實測）。藍點為 IDS 測高衛星，橘三角為福衛三號在地對照，紅框為 Starlink 低軌帶；灰虛線為既有門檻表對高軌之 50 m 假設。](fig_sigma_vs_altitude.png)

**圖 1** 以對數縱軸呈現 σ 與高度之關係：≥700 km 各測高衛星密集落於 0.1–0.3 m 之次公尺平台，福衛三號（788 km，無推進）約 1 m，而 Starlink 低軌帶（350–550 km）高達 24–75 m，兩者相差 1/80–1/250；既有門檻表對高軌之 50 m 假設（灰虛線）遠高於實測，凸顯其在高高度帶之高估。

**核心結果**：於良好取樣、涵蓋 **719–1338 km** 之七顆測高衛星（CryoSat-2、SARAL、Sentinel-3A/3B、HY-2C、Jason-3、Sentinel-6A），σ_diff 中位為 **≈0.3 m**，最佳者低至 **0.1 m**。此值：

1. **僅為表 11 假設（50 m）的約 1%**——證明既有門檻表在高高度帶高估雜訊達**兩個數量級**；
2. 較低軌 **Starlink 帶（~350–550 km）之 σ≈24–75 m** 小 **1/80–1/250**（Starlink 之 σ 由本專案逐星 σ 校準得 ~25–50 m，與此比值一致）。

**高度相依性**（本文主結論）：TLE 半長軸雜訊底並非常數，而**隨高度陡降**。物理成因為熱氣層密度隨高度近指數衰減，故阻力所引致之未建模 *a* 擾動（雜訊主控項）在高軌趨於消失；≥700 km 帶已進入**次公尺級平台**，而 Starlink 所在之 350–550 km 帶因強且多變之阻力，雜訊底高達數十公尺。此高度—σ 關係即為機動偵測門檻必須「按高度自適應」的實證基礎。

## 4. 兼論：福衛系列之機動觀測與推導

將上節之高度—σ 關係應用於在地的福衛系列（表 2）。福衛諸星橫跨 675–827 km，正落在本文校準區間之下緣，可直接引用其雜訊底進行機動觀測與 Δv 推導。

**表 2　福衛系列 TLE 概況（space_db.duckdb，2024–2026）**

| 衛星 | NORAD | 高度 (km) | 推進 | 角色 |
|---|---|---|---|---|
| 福衛三號 A–F | 29047–29052 | 675–789 | 無 | **無機動對照** |
| 福衛五號 | 42920 | 723 | 有 | 機動觀測 |
| 福衛七號 A–F | 43010–43015 | 519–827 | 有 | 部署/維持機動 |

### 4.1 福衛三號——無推進對照，驗證在地雜訊底

福衛三號（COSMIC-1）六星無推進系統，軌道純受大氣阻力自然衰減（3D 已降至 675 km）。取近 30 天安靜段，實測 σ_diff≈**0.8–1.1 m**（σ_res 1.9–3.4 m，因老化小衛星之 TLE 擬合較差且處衰減段）。此值雖高於 IDS 同高度之最佳者（SARAL 782 km，σ_diff 0.2 m），仍屬**次公尺至約 1 公尺級**，與「≥700 km 進入次公尺平台」之結論一致，並提供以**在地衛星**確認之雜訊底：福衛三號在無機動期間，|Δ*a*| 雜訊僅約 1 m。

### 4.2 福衛五號——機動偵測與 Δv 反演

福衛五號（723 km 太陽同步、具推進）近一年之相鄰 |Δ*a*| 分布：中位 0.5 m、p90 1.5 m、p99 3.6 m，但**最大達 798 m**，且有 **4 次 |Δ*a*|>50 m** 之明確階梯。以 4.1 之在地雜訊底（~1 m）為基準，這些機動之訊噪比：

$$\text{SNR} = \frac{|\Delta a|_{\max}}{\sigma} \approx \frac{798\,\text{m}}{1\,\text{m}} \approx 8\times10^2$$

遠高於偵測門檻（SNR≥2），故可**穩健觀測**且無誤報之虞。

**Δv 推導**：對近圓軌道之小切向脈衝，由能量微分 $v\,\mathrm dv = \frac{\mu}{2a^2}\mathrm da$ 得
$$\Delta v \approx \frac{v}{2a}\,\Delta a,\qquad v=\sqrt{\mu/a}.$$
福衛五號 $a\approx7101$ km、$v\approx7.49$ km/s，最大機動 $\Delta a\approx0.798$ km：
$$\Delta v \approx \frac{7.49}{2\times7101}\times0.798 \approx 4.2\times10^{-4}\ \text{km/s} = \mathbf{0.42\ m/s}.$$
此量級符合太陽同步軌道之例行維持機動。其餘 3 次 |Δ*a*|=50–數百 m 者，推得 Δv 約 0.03–0.2 m/s。

### 4.3 福衛七號——在軌維持之較小機動

福衛七號 A（827 km、部署後在軌）近一年 |Δ*a*| 中位 1.0 m、p99 5.8 m、最大 42 m，無 >50 m 階梯——反映其已完成部署、進入例行維持階段，機動幅度較小。即便如此，其最大 |Δ*a*|=42 m 相對於 ~1 m 之雜訊底仍達 SNR≈40，可靠可辨。

### 4.4 小結

福衛系列以「無推進對照（三號）＋有推進觀測（五號/七號）」構成一組在地閉環：**雜訊底（~1 m）由無機動衛星確立，真實機動（數十至數百 m）遠高於底噪而可觀測，並可由 |Δa| 直接反演 Δv**。此正是本文高度—σ 框架的具體效用。

## 5. 討論

1. **門檻應以高度相依 σ 正規化**。σ 於 719–1338 km 為 0.1–0.3 m、於 350–550 km 為 24–75 m，跨度達 1/80–1/250。以單一絕對 |Δ*a*| 門檻套全高度帶，必然在高軌過度保守、在低軌淹沒小機動；正解為將門檻表示為 $k\cdot\sigma(h)$，即 SNR 判定。
2. **既有門檻表之高軌帶須修正**。表 11 對 ≥700 km 假設 σ=50 m，實測僅 0.3 m（比值 ~0.01），高估兩個數量級；沿用將使高軌機動之靈敏度被人為壓低。
3. **小機動的物理極限落在低軌**。Starlink 帶雜訊底 24–75 m，意味幅度與之相當的小機動（SNR<2）在純 TLE 下**物理不可分**，需精密星曆治本；而在高軌（次公尺底噪），同等 Δv 之機動反而清晰可辨。此解釋了「小機動召回上限」為何是低軌特有的問題。
4. **方法之外部效度**。本文之 σ 來自**操作方認證**之安靜期，非以 TLE 自我標註，避免了自標籤循環，結論可被獨立稽核。

**限制**：部分衛星（HY-2D、SWOT）安靜段少，σ 估計不穩，已排除於主結論之外；福衛三號之較高 σ 反映老化與衰減段之 TLE 品質，屬保守上界。

## 6. 結論

本文以 IDS DORIS 測高衛星於操作方認證安靜期之實測，首次在 719–1338 km 帶校準 TLE 半長軸之純雜訊底，得 σ 中位 **≈0.3 m**（最佳 0.1 m），較低軌 Starlink 小 **1/80–1/250**，並證明此雜訊底**強烈隨高度變化**、既有門檻表在高軌高估雜訊達兩個數量級。將此高度—σ 關係應用於福衛系列，福衛三號（無推進）確立 ~1 m 在地雜訊底，福衛五號之機動（最大 |Δ*a*|=798 m→Δv≈0.42 m/s）在高訊噪比下可穩健觀測與反演。據此，我們主張低軌機動偵測門檻應由**固定絕對值改為高度相依之 σ 正規化（SNR 判定）**，以同時兼顧高軌靈敏度與低軌誤報控制。

## 參考文獻（待補正式格式）

1. International DORIS Service (IDS) — precise orbit ephemerides and maneuver logs.
2. Vallado, D. A., *Fundamentals of Astrodynamics and Applications*.
3. Hoots, F. R., Roehrich, R. L., *Spacetrack Report No. 3 — Models for Propagation of NORAD Element Sets*.
4. 本研究計畫期中報告：智慧化低軌通訊衛星軌道異常及太空事件偵測（TASA-S-1150268）。

---

*資料與可重現性*：σ 校準程式 `ids_truth_set/ids_sigma_calibrate.py`、認證安靜期 `ids_truth_set/ids_quiet.csv`、輸出 `ids_truth_set/ids_sigma_calibration.csv`；福衛觀測取自 `space_db.duckdb::raw_tle_archive`。
