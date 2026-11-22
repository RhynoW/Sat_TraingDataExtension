"""延伸篇 S3 LinkedIn 素材：中文貼圖 5 張＋輪播 PDF，以及全文文章版。內容取自 S3 正文，不新增事實。

用法：python docs/book/social/S3/_build_S3_social.py
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(OUT.parent))
from _ext_social import ROOT, article, card_big, card_cover, card_rows, render_cards  # noqa: E402

CH = "延伸篇 S3"
cards = [
    card_cover(CH, "op_s3.jpg", "兵棋推演：<br>海纜中斷下的<br>太空通訊韌性",
               "在寫清楚的假設下，<br>哪些選擇比較好？<br>假設改變時，結論會不會翻轉？",
               "太空兵棋模擬畫面：想定 C 的一局｜本專案 Rust 單機版，2026-11-22"),
    card_rows(CH, 2, "推演中的數字有四種來源",
              [("想定依據", "DIA 報告的公開描述：抹除商用數據機、干擾 GPS、共軌接近、直升式反衛星"),
               ("示意參數", "抹除 30%、SAR 成功率 80%、規避後服務降 30%：教學設定，DIA 沒有提供"),
               ("AI 行為假設", "紅方被監視就降低出手率；藍方有備援，紅方就換目標"),
               ("計分權重", "偵察每次成功 3 分、定位授時每少 10% 扣 2 分")],
              "海纜中斷是遊戲原有的設定，DIA 2026 報告沒有討論海底電纜；把案例移植到台灣周邊，是推演假設。"),
    card_big(CH, 3, "同一個打法，兩種命運",
             ("−1.7", "想定 A 灰色地帶<br>重 GEO 的攻擊代價（百分點）", "#35C6FF"),
             ("−12.4", "想定 C 共軌接近<br>重 GEO 的損失（百分點）", "#FF6B4A"),
             "A 最穩的打法，在 C 最脆弱",
             "本遊戲的 GEO 租用不受干擾與網攻影響，「重 GEO 最穩」是模型結構的結果。真實的 GEO 服務同樣可能被攻擊，Viasat KA-SAT 本身就是 GEO 服務。",
             "想定 A：紅方灰色地帶，對照組為同樣預置終端、未被攻擊；想定 C：紅方升級；每組 500 局"),
    card_rows(CH, 4, "對照組與配對差值",
              [("只接近、不攻擊", "監視＋規避 81.8%，均衡 85.8%：紅方不出手，藍方仍少 4.0 個百分點"),
               ("配對差值", "想定 A 攻擊代價 −3.21：95% 區間 ±0.01；當成獨立樣本會算成 ±0.63"),
               ("名次穩不穩", "重抽 1,000 次：A、B 的第一名 100% 相同；C 為 53% 對 47%，D 各 44%")],
              "紅方不必出手，只要停在旁邊，藍方就得一直花點數規避；要量出這筆代價，必須有「只接近、不攻擊」的對照組。",
              "頻寬可用率為 8 回合平均；共同亂數，種子 1000–1499"),
    card_rows(CH, 5, "敏感度分析之後",
              [("A｜高", "重 GEO 最穩：抹除 15%、30%、60% 都是第一"),
               ("B｜中高", "均衡＋備援在八成以上的權重組合中第一；翻轉只在角落"),
               ("C｜低", "監視＋規避打平均衡，只在監視不中斷、規避必成功時成立"),
               ("D｜低", "「商業影像讓反衛星落空」主要來自紅方 AI 換目標的假設")],
              "兵棋推演的產出是「在什麼假設下，哪個選擇比較好」，不是「哪個選擇最好」。",
              "模型內穩健度只表示結論對掃描過參數的敏感程度，不代表真實情況下的可信度"),
]
render_cards(OUT, "S3", cards)

HEADER = """# 延伸篇 S3 LinkedIn 文章版（全文）

使用方式：
- LinkedIn 一般貼文上限 3,000 字，放不下全文；本檔供 LinkedIn「撰寫文章」（Write article）使用。短貼文見 `LinkedIn_貼文_延伸篇S3.md`。
- 從「標題」以下複製。「▍」開頭的行請在編輯器中設為標題；表格已改寫為條列（每列一行，「欄名：值」）。
- 【插圖】標記處請上傳對應圖檔，路徑相對於 docs/book/sim_chapters/（即 C:\\Github\\Sat_TrainDataExtension\\docs\\book\\sim_chapters\\img\\…）。封面建議用 img/op_s3.jpg 或 social/S3/cards_zh/S3_zh_1.png。
- 註腳以 [n] 標示，對應文末「資料來源」。
- 由 _build_S3_social.py 從 S3 正文自動轉換，內容與單篇 PDF 同源，未新增事實。
"""
n = article(next((ROOT / "docs/book/sim_chapters").glob("S3_*_初稿.md")), OUT / "LinkedIn_文章_延伸篇S3_全文.md", HEADER)
print("S3：5 張貼圖＋輪播 PDF；文章版", n, "字")
