<!-- 由 docs/export_storymap_md.py 自 maneuver_app_2026November.py 匯出；線上版：https://rhynowu-maneuver-detection-i18n.hf.space/?mode=storymap&case=case29 -->

# 案例二十九：一次真實的人工迴避機動——孟加拉衛星以自力計算躲過印度退役衛星碎片

### 沒有 VCM、沒有商用避碰工具，一個小國團隊仍靠公開預警與人工計算躲過碰撞——這呼應案例二十八的資料落差，也呼應本專案的立場：公開資料加上正確方法，仍能做出有意義的判斷

> **誠實揭露**：本案例整理自 2026 年孟加拉及台灣媒體公開報導，屬**外部真實事件引用**，並非本專案偵測管線的分析對象——本專案資料庫未收錄孟加拉 BS-1（NORAD 43463）或印度 INSAT-1A（NORAD 13129）的 TLE，也未對此事件做任何重算、驗證或機動偵測。放進 StoryMap 的理由是它與案例二十八討論的 VCM/TLE 資料落差高度呼應的真實前例，不是本專案的驗證成果。

## ① 事件經過

- 2026-08-09 前後：孟加拉衛星公司（BSCL）地面站收到美國 Space-Track 太空監視網的預警，示警一塊碎片正快速接近其同步軌道衛星 BS-1（原名 Bangabandhu-1，NORAD 43463，位於東經 119.1°）。
- 工程團隊在加濟布爾（Gazipur）地面站自行計算可行的位移方向與幅度。
- 2026-08-13：BSCL 將 BS-1 向左小幅位移並維持至碎片通過，隨後移回原位；碎片最終與 BS-1 最近距離僅 852 公尺，衛星未受損。
- BSCL 董事總經理 Imadur Rahman 公開說明，全程計算與操作由孟加拉本土工程師獨立完成。

## ② 碎片來源

- 碎片來自印度 1982 年發射的 INSAT-1A（NORAD 13129），該衛星發射後數月即因姿態控制／推進劑問題失控，同年遭放棄，之後長期是軌道上的無控物體。
- 各報導對失控退役的確切時間點記載略有差異（有寫 1982 年 9 月，亦有寫推進劑耗盡於 1983 年 9 月），建議以 ISRO 官方紀錄為準，本案例不另行查證。

## ③ 為什麼這個案例放進本 StoryMap

- 案例二十八說明了 TLE 與 VCM 的根本落差：沒有 covariance，就算不出可信的碰撞機率 Pc。這起事件是一個真實世界的對照組——BSCL 同樣沒有 VCM，甚至沒有商用避碰軟體，仍靠公開預警＋人工計算做出避碰決策。
- 這正呼應本專案的立場：本專案從頭到尾只用公開 TLE，沒有任何特權資料來源，卻一路證明「公開資料＋正確方法＋誠實揭露限制」仍能產出有意義的機動偵測與態勢判斷。BSCL 的案例，是「資源有限的團隊靠對的方法做出正確決策」在真實世界的縮影。
- 換句話說：本專案與 BSCL 面對的是同一種結構性限制（缺乏私有／軍方級的精確資料），但都選擇在限制之內把能做的事做到最好，而不是因為拿不到最好的資料就放棄判斷。

## ④ 查證限制（誠實揭露）

- 本案例所有細節均來自孟加拉媒體（The Daily Star、TBS News）及台灣媒體（民生電子報）轉述 BSCL 高層的說法，查證時沒有找到印度官方或獨立第三方對「碎片確實來自 INSAT-1A」或「852 公尺」數字的佐證。
- 查證時發現部分報導的發布時間標記（如「1 天前」）與系統當前日期（2026-10-09）對不上，不排除是舊聞被重新轉載；因此「事件確切發生於 2026 年 8 月」這一點，本案例**無法百分之百確認**，僅依來源報導的敘述呈現。
- 原始敘述中「孟加拉官方強調全程未向衛星製造商（泰雷茲阿萊尼亞航太公司）尋求操作協助」一句，查證時沒有在任一篇報導中找到逐字對應的引述，比較接近是對「工程師自主完成」敘事的合理延伸；本案例採用時僅以「自主完成」呈現，不逐字複述未經證實的細節。

**判讀**：這起事件無法作為本專案偵測能力的證據（本專案完全沒有分析這兩顆衛星），但它是一個誠實、有紀律的對照：告訴我們「沒有最好的資料」不等於「做不出有意義的判斷」——只要方法對，而且願意誠實說清楚自己能做到哪裡、做不到哪裡。

## ⑤ 來源

- The Daily Star, "Bangladesh satellite saved from space debris by local engineers" — https://www.thedailystar.net/news/news/bangladesh-satellite-saved-space-debris-local-engineers-4293136
- TBS News, "US space tracking alert helps Bangladesh's satellite avoid Indian satellite debris" — https://www.tbsnews.net/tech/us-space-tracking-alert-helps-bangladeshs-satellite-avoid-indian-satellite-debris-1565871
- 民生電子報，〈國際太空碎片威脅升溫 美國示警助孟加拉衛星避險〉— https://lifenews.com.tw/594777
- Wikipedia, "INSAT-1A" — https://en.wikipedia.org/wiki/INSAT-1A
- Gunter's Space Page, "Bangabandhu 1 (BD 1)" — https://space.skyrocket.de/doc_sdat/bangabandhu-1.htm

---
線上互動版：<https://rhynowu-maneuver-detection-i18n.hf.space/?mode=storymap&case=case29>
