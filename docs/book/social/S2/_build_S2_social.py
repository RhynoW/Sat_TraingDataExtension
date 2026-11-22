"""延伸篇 S2 LinkedIn 素材：中文貼圖 5 張＋輪播 PDF，以及全文文章版。內容取自 S2 正文，不新增事實。

用法：python docs/book/social/S2/_build_S2_social.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
from _ext_social import ROOT, article, card_big, card_cover, card_fig, card_rows, render_cards  # noqa: E402

CH = "延伸篇 S2"
cards = [
    card_cover(CH, "op_s2.jpg", "巨型星座的外部成本：<br>壅擠與光害",
               "星座變大之後，<br>接近與光跡的成本，<br>落在誰身上？",
               "星座壅擠模擬畫面：10 萬 Starlink 情境｜本專案 Rust 單機版，2026-11-22"),
    card_big(CH, 2, "協調假設決定倍數",
             ("×6.3", "營運者完全協調自家星座<br>（同星座不計）", "#35C6FF"),
             ("×62.7", "沒有任何協調<br>（全部都計）", "#FF6B4A"),
             "同一個情境，倍數相差約十倍",
             "10 萬 Starlink 情境的物件是現況的 4.6 倍。全系統每天 1 公里內的接近次數，協調有效時增加 6.3 倍，協調失效時增加 63 倍。把大量衛星塞進少數殼層時，協調是否有效比衛星總數更能決定風險。",
             "以 1 公里為避碰代理門檻；取樣 2 小時、每 60 秒一個快照；教學模型示意"),
    card_fig(CH, 3, "第三方付出的代價", "s2_coordination.png",
             "星座以外的 21,047 個物件，每顆每年 1 公里內的接近從約 35 次增加到約 65 次（各家計畫全數）或約 109 次（10 萬 Starlink），三種協調規則下幾乎相同。營運者能協調自己的衛星，卻不能替別人避碰。",
             "左：全系統接近次數相對現況的倍數（對數軸）；右：星座以外物件每顆每年的接近次數"),
    card_fig(CH, 4, "光跡集中在昏影後", "s2_lulin_night.png",
             "鹿林天文台、Rubin 級巡天望遠鏡、正北仰角 45°：昏影後第一小時，每次 30 秒曝光看得見的光跡從平均 0.7 條增加到 3.4 條；19:10 以後兩者相同。太陽沉得更深，低軌衛星就進入地影。",
             "疊加情境：當天目錄全部保留，再加上 10 萬 Starlink、2 萬 Kuiper、1 萬千帆；每 10 分鐘一次曝光"),
    card_rows(CH, 5, "成本落在誰身上",
              [("交會篩選", "全系統每天 1 公里內接近：3,488 次 → 24,052 次（各家計畫全數）"),
               ("第三方物件", "每顆每年 1 公里內接近：約 35 次 → 約 109 次（10 萬 Starlink）"),
               ("光學觀測", "昏影結束時的一張曝光：0 條 → 2 條約 3.7 等的光跡")],
              "巨型星座的成本，有一大部分落在星座以外的人身上。",
              "本篇沒有量化對特定國家、衛星或觀測站的實際影響；數值皆為教學模型示意"),
]
render_cards(OUT, "S2", cards)

HEADER = """# 延伸篇 S2 LinkedIn 文章版（全文）

使用方式：
- LinkedIn 一般貼文上限 3,000 字，放不下全文；本檔供 LinkedIn「撰寫文章」（Write article）使用。短貼文見 `LinkedIn_貼文_延伸篇S2.md`。
- 從「標題」以下複製。「▍」開頭的行請在編輯器中設為標題；表格已改寫為條列（每列一行，「欄名：值」）。
- 【插圖】標記處請上傳對應圖檔，路徑相對於 docs/book/sim_chapters/（即 C:\\Github\\Sat_TrainDataExtension\\docs\\book\\sim_chapters\\img\\…）。封面建議用 img/op_s2.jpg 或 social/S2/cards_zh/S2_zh_1.png。
- 註腳以 [n] 標示，對應文末「資料來源」。
- 由 _build_S2_social.py 從 S2 正文自動轉換，內容與單篇 PDF 同源，未新增事實。
"""
n = article(next((ROOT / "docs/book/sim_chapters").glob("S2_*_初稿.md")), OUT / "LinkedIn_文章_延伸篇S2_全文.md", HEADER)
print("S2：5 張貼圖＋輪播 PDF；文章版", n, "字")
