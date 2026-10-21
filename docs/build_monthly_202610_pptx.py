# -*- coding: utf-8 -*-
"""build_monthly_202610_pptx.py — 2026 年 10 月進度月報簡報
產出：docs/進度月報_202610.pptx
底本：docs/進度月報_202610.md（三個重點：期末報告準備、Starlink V3 26 顆軌道機動、L3 口徑修正與 v2）
樣式沿用 build_case_study_30_pptx.py（深海軍藍主題），本檔獨立維護。
L3 擂台數字由 data/benchmark/three_layer_common_eval_20261021*.csv 讀入。
"""
import sys
from pathlib import Path
import pandas as pd
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DOCS = Path(__file__).parent
BM = DOCS.parent / "data" / "benchmark"
OUT = DOCS / "進度月報_202610.pptx"
FONT = "Microsoft JhengHei"
BG      = RGBColor(0x0E, 0x1B, 0x2E)
PANEL   = RGBColor(0x16, 0x27, 0x40)
PANEL2  = RGBColor(0x1E, 0x33, 0x52)
ACCENT  = RGBColor(0x4F, 0xC3, 0xF7)
ACCENT2 = RGBColor(0xFF, 0xD5, 0x4F)
INK     = RGBColor(0xEC, 0xF2, 0xF9)
MUTE    = RGBColor(0x9F, 0xB3, 0xC8)
GOOD    = RGBColor(0x66, 0xBB, 0x6A)
WARN    = RGBColor(0xEF, 0x9A, 0x9A)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
W, H = Inches(13.333), Inches(7.5)

AR_NEW = pd.read_csv(BM / "three_layer_common_eval_20261021.csv").set_index("method")
AR_OLD = pd.read_csv(BM / "three_layer_common_eval_20261021_legacyquiet.csv").set_index("method")
L1, L2, L3, L3V2 = "L1 規則 P1–P6", "L2 cusum（單通道）", "L3 融合評分器 OOF", "L3 v2 融合評分器 OOF"


def _fill(shape, color):
    shape.fill.solid(); shape.fill.fore_color.rgb = color
    shape.line.fill.background(); shape.shadow.inherit = False


def _bg(slide):
    r = slide.shapes.add_shape(1, 0, 0, W, H); _fill(r, BG)


def _txt(slide, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, sp=1.0):
    tb = slide.shapes.add_textbox(x, y, w, h); tf = tb.text_frame
    tf.word_wrap = True; tf.vertical_anchor = anchor
    if runs and isinstance(runs[0], tuple):
        runs = [runs]
    for i, line in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align; p.line_spacing = sp
        for (text, size, color, bold) in line:
            r = p.add_run(); r.text = text
            r.font.name = FONT; r.font.size = Pt(size); r.font.color.rgb = color; r.font.bold = bold
    return tb


def _chip(slide, text, color=ACCENT):
    c = slide.shapes.add_shape(1, Inches(0.6), Inches(0.45), Inches(0.14), Inches(0.5)); _fill(c, color)
    _txt(slide, Inches(0.88), Inches(0.41), Inches(11.8), Inches(0.6),
         [(text, 23, INK, True)], anchor=MSO_ANCHOR.MIDDLE)


def _panel(slide, x, y, w, h, color=PANEL):
    p = slide.shapes.add_shape(1, x, y, w, h); _fill(p, color); return p


def _verdict(slide, text, y=Inches(1.15), color=ACCENT2):
    """標題下方的一句結論（先結論後細節）"""
    _panel(slide, Inches(0.6), y, Inches(12.1), Inches(0.62), PANEL2)
    bar = slide.shapes.add_shape(1, Inches(0.6), y, Inches(0.08), Inches(0.62)); _fill(bar, color)
    _txt(slide, Inches(0.85), y, Inches(11.7), Inches(0.62), [(text, 14.5, INK, True)], anchor=MSO_ANCHOR.MIDDLE)


def bullets(slide, x, y, w, items, size=14, gap=1.2, h=Inches(4.8)):
    tb = slide.shapes.add_textbox(x, y, w, h); tf = tb.text_frame; tf.word_wrap = True
    for i, (mc, runs) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = gap; p.space_after = Pt(6)
        b = p.add_run(); b.text = "▍ "; b.font.name = FONT; b.font.size = Pt(size); b.font.color.rgb = mc
        for (text, sz, color, bold) in runs:
            r = p.add_run(); r.text = text
            r.font.name = FONT; r.font.size = Pt(sz); r.font.color.rgb = color; r.font.bold = bold
    return tb


def table(slide, x, y, w, rows, col_w, head=True, size=12, row_h=Inches(0.42), hl_rows=(), align_right=()):
    nrows, ncols = len(rows), len(rows[0])
    t = slide.shapes.add_table(nrows, ncols, x, y, w, row_h * nrows).table
    for c, cw in enumerate(col_w):
        t.columns[c].width = cw
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = t.cell(r, c); cell.text = str(val)
            cell.fill.solid()
            cell.fill.fore_color.rgb = PANEL2 if (head and r == 0) else (PANEL if r % 2 else BG)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            p = cell.text_frame.paragraphs[0]
            if c in align_right and r > 0:
                p.alignment = PP_ALIGN.RIGHT
            p.font.name = FONT; p.font.size = Pt(size)
            p.font.color.rgb = ACCENT2 if (head and r == 0) else (ACCENT2 if r in hl_rows else INK)
            p.font.bold = (head and r == 0) or r in hl_rows
    return t


def _stat(slide, x, y, w, big, label, color=ACCENT2, big_size=36):
    _txt(slide, x, y, w, Inches(0.75), [(big, big_size, color, True)], align=PP_ALIGN.CENTER)
    _txt(slide, x, y + Inches(0.8), w, Inches(0.7), [(label, 12, MUTE, False)], align=PP_ALIGN.CENTER)


def _figure(slide, path, x, y, w):
    """白底圖：先墊白色面板，讓淺色圖在深色主題上清楚"""
    from PIL import Image
    iw, ih = Image.open(path).size
    h = int(w * ih / iw)
    pad = Inches(0.08)
    _panel(slide, x - pad, y - pad, w + 2 * pad, h + 2 * pad, WHITE)
    slide.shapes.add_picture(str(path), x, y, w, h)
    return h


prs = Presentation(); prs.slide_width = W; prs.slide_height = H
BLANK = prs.slide_layouts[6]


def slide():
    s = prs.slides.add_slide(BLANK); _bg(s); return s


N = [0]
def foot():
    N[0] += 1
    s = prs.slides[-1]
    _txt(s, Inches(0.5), Inches(7.06), Inches(10), Inches(0.32),
         [("TASA-S-1150268　2026 年 10 月進度月報", 9.5, MUTE, False)])
    _txt(s, Inches(12.4), Inches(7.06), Inches(0.7), Inches(0.32),
         [(str(N[0]), 9.5, MUTE, False)], align=PP_ALIGN.RIGHT)


def divider(no, title, sub):
    s = slide()
    _panel(s, 0, Inches(2.7), W, Inches(2.0))
    bar = s.shapes.add_shape(1, Inches(0.9), Inches(2.9), Inches(0.18), Inches(1.6)); _fill(bar, ACCENT)
    _txt(s, Inches(1.3), Inches(2.95), Inches(11), Inches(1.0), [(f"{no}　{title}", 34, INK, True)])
    _txt(s, Inches(1.3), Inches(4.0), Inches(11), Inches(0.6), [(sub, 16, ACCENT, False)])
    foot()


# ══ 封面 ═════════════════════════════════════════════════════════════════
s = slide()
_panel(s, 0, Inches(2.3), W, Inches(2.5))
_txt(s, Inches(0.9), Inches(1.5), Inches(11.5), Inches(0.6), [("進　度　月　報", 20, ACCENT, True)])
_txt(s, Inches(0.9), Inches(2.7), Inches(11.6), Inches(1.2), [("2026 年 10 月", 44, INK, True)])
_txt(s, Inches(0.9), Inches(3.75), Inches(11.6), Inches(0.8),
     [("期末報告準備｜Starlink V3 入軌升軌觀察｜L3 融合評分器口徑修正與 v2", 20, INK, False)])
_txt(s, Inches(0.9), Inches(5.3), Inches(11.6), Inches(0.5),
     [("計畫案號 TASA-S-1150268", 14, MUTE, False)])
_txt(s, Inches(0.9), Inches(5.75), Inches(11.6), Inches(0.5),
     [("資料截至：TLE 2026-10-20　｜　文件 2026-10-21", 14, MUTE, False)])
foot()

# ══ 本月重點摘要 ═════════════════════════════════════════════════════════
s = slide(); _chip(s, "本月三個重點")
cards = [
    ("1", "期末報告準備", ACCENT, "4 / 4",
     "招標規範要求的四項期末交付物都已有完整版本",
     "目前在補入新成果、處理少數待定項目、定稿；沒有尚未動工的交付項目。"),
    ("2", "Starlink V3 26 顆", ACCENT2, "23 / 26",
     "已分三段升軌到約 345.7 km",
     "在此高度只觀察 2–3 天，尚不能確認是最終高度；3 顆落後，其中 100858 約 10 天沒有升軌。"),
    ("3", "L3 融合評分器", GOOD, "0.813 → 0.859",
     "修正「安靜樣本」定義後 AUC 下降，v2 回升",
     "召回率也明顯提升；但換到未來時段仍弱（AUC 約 0.60），是下一步要處理的問題。"),
]
for i, (no, head, col, big, line1, line2) in enumerate(cards):
    x = Inches(0.6 + i * 4.1)
    _panel(s, x, Inches(1.35), Inches(3.85), Inches(4.2))
    bar = s.shapes.add_shape(1, x, Inches(1.35), Inches(3.85), Inches(0.09)); _fill(bar, col)
    _txt(s, x + Inches(0.3), Inches(1.65), Inches(3.3), Inches(0.5), [(f"{no}｜{head}", 17, INK, True)])
    _txt(s, x + Inches(0.1), Inches(2.4), Inches(3.65), Inches(0.9), [(big, 34, col, True)], align=PP_ALIGN.CENTER)
    _txt(s, x + Inches(0.3), Inches(3.55), Inches(3.3), Inches(0.9), [(line1, 14, INK, True)], sp=1.15)
    _txt(s, x + Inches(0.3), Inches(4.5), Inches(3.3), Inches(2.0), [(line2, 12.5, MUTE, False)], sp=1.25)
foot()

# ══ 一、期末報告準備情況 ═════════════════════════════════════════════════
divider("一", "期末報告準備情況", "四項交付物皆已完成主體，進入補入新成果與定稿階段")

s = slide(); _chip(s, "交付物現況：四項皆已有完整版本")
_verdict(s, "結論：沒有尚未動工的交付項目；結案簡報待與報告最新內容同步。")
table(s, Inches(0.6), Inches(2.05), Inches(12.1), [
    ["招標規範交付項目", "對應文件", "狀態"],
    ["1. 期末報告電子檔", "期末報告（決策版）＋技術附錄", "✅ 主體完成，本月持續更新"],
    ["2. 完整原始程式碼", "程式庫＋精簡可交付包＋可重跑封包說明", "✅"],
    ["3. 技術說明文件", "技術附錄（演算法流程、使用技術、測試基準、驗證結果、參考資料）", "✅"],
    ["4. 教育訓練文件", "App 操作手冊（完整版＋精簡版）", "✅"],
    ["（附帶）結案簡報", "期末結案簡報", "🟡 待與報告最新內容同步"],
], col_w=[Inches(2.7), Inches(6.4), Inches(3.0)], size=13, row_h=Inches(0.55))
foot()

s = slide(); _chip(s, "本月完成項目")
_panel(s, Inches(0.6), Inches(1.25), Inches(7.4), Inches(4.7))
_txt(s, Inches(0.85), Inches(1.4), Inches(7.0), Inches(0.45), [("NASA/ILRS 標竿章節：納入 TASA 10/14 逐星結果", 16, ACCENT, True)])
_txt(s, Inches(0.85), Inches(1.95), Inches(7.0), Inches(1.0),
     [("相同真值（14 星、1,420 個機動事件，雙方事件數一致）上直接對照；採 TASA 確認的 ±1.5 天容差。", 12.5, INK, False)], sp=1.2)
_panel(s, Inches(0.85), Inches(2.95), Inches(3.3), Inches(1.6), PANEL2)
_panel(s, Inches(4.45), Inches(2.95), Inches(3.3), Inches(1.6), PANEL2)
_stat(s, Inches(0.85), Inches(3.05), Inches(3.3), "0.496", "本法 平均 F1", GOOD)
_stat(s, Inches(4.45), Inches(3.05), Inches(3.3), "0.330", "TASA 全域最佳組態 平均 F1＊", ACCENT2)
_txt(s, Inches(0.85), Inches(4.75), Inches(7.0), Inches(1.9), [
    [("＊此平均值由本計畫依 TASA 逐星表計算。", 11.5, MUTE, False)],
    [("結論會隨容差改變，且 TASA 偵測區間寬度尚待核對，報告中列為「暫定」。", 12.5, WARN, False)],
    [("報告分開標註三種數字：TASA 7/31 版、本計畫依 TASA 方法重做版、TASA 10/14 版", 12.5, INK, False)],
], sp=1.25)
bullets(s, Inches(8.3), Inches(1.35), Inches(4.4), [
    (ACCENT2, [("案例研究擴充\n", 15, INK, True),
               ("單星逐層解析由 10 顆擴充至 30 顆，列出每顆研判為機動的日期，方便委員逐筆核對。", 12.5, MUTE, False)]),
    (ACCENT2, [("文獻探討獨立成冊\n", 15, INK, True),
               ("分類整理 34 筆參考文獻，並更正其中的 DOI 與期刊名稱。", 12.5, MUTE, False)]),
    (ACCENT2, [("App 操作手冊精簡版\n", 15, INK, True),
               ("以淺白文字撰寫，供非專業背景人員使用。", 12.5, MUTE, False)]),
], gap=1.2, h=Inches(5.3))
foot()

s = slide(); _chip(s, "定稿前待辦")
_verdict(s, "五項待辦中，只有「TASA 原始偵測清單重算」需要 TASA 協助。", color=WARN)
table(s, Inches(0.6), Inches(2.05), Inches(12.1), [
    ["項目", "說明", "需 TASA 協助"],
    ["TASA 原始偵測清單重算", "取得清單後，以同一支評分程式重算雙方結果並回傳核對，再更新報告中的暫定結論", "是（等待提供）"],
    ["Starlink V3 評估母體處理", "26 顆新星入軌初期的升軌被誤計為誤報（見第二節；本月已實作，見第三節）", "否"],
    ["部分指標重新驗算", "Average Precision、F1-macro 依最新資料庫重算核對（契約附表 8 判定數字不受影響）", "否"],
    ["論文措辭同步", "論文一相關段落依 CDM 弱監督除列決議調整，需先確認投稿狀態", "否"],
    ["定稿與版本凍結", "報告、簡報、操作手冊統一轉檔並鎖定版本，確保審查時可依版本重現", "否"],
], col_w=[Inches(3.0), Inches(7.3), Inches(1.8)], size=12.5, row_h=Inches(0.62), hl_rows=(1,))
foot()

# ══ 二、Starlink V3 ══════════════════════════════════════════════════════
divider("二", "Starlink V3（26 顆）入軌後軌道機動觀察", "2026-09-30 入軌｜NORAD 100855–100880｜傾角約 30.5°")

s = slide(); _chip(s, "升軌三段式：23 顆已到約 345.7 km，但還不能確認是最終高度", ACCENT2)
_figure(s, DOCS / "fig_starlink_v3_raising_202610.png", Inches(0.7), Inches(1.35), Inches(7.6))
_txt(s, Inches(0.6), Inches(5.5), Inches(7.8), Inches(0.4),
     [("圖 1　26 顆入軌後高度變化（灰線為主隊 23 顆，彩色為 3 顆落後星）", 11, MUTE, False)])
table(s, Inches(8.75), Inches(1.3), Inches(4.0), [
    ["階段", "主隊到達", "高度"],
    ["入軌", "09-30", "≈ 270 km"],
    ["第一次停留", "10-03～10-05", "≈ 296 km"],
    ["第二次停留", "10-07～10-10", "≈ 316 km"],
    ["目前高度", "10-14～10-18", "≈ 345.7 km"],
], col_w=[Inches(1.35), Inches(1.45), Inches(1.2)], size=11.5, row_h=Inches(0.48), hl_rows=(4,))
_txt(s, Inches(8.75), Inches(3.9), Inches(4.0), Inches(2.9), [
    [("10/18 後主隊高度變化中位數僅 0.21 km，看起來已停止升軌。", 12.5, INK, False)],
    [("", 6, INK, False)],
    [("但前兩段停留也都維持了好幾天，345.7 km 可能仍是中途停留。", 12.5, WARN, False)],
    [("", 6, INK, False)],
    [("建議再觀察 1–2 週後判定。", 12.5, ACCENT2, True)],
], sp=1.2)
foot()

s = slide(); _chip(s, "三顆落後星：100858 已約 10 天沒有升軌，值得持續追蹤", WARN)
lag = [("100865", "341.8 km", ACCENT,
        "10/14 升到約 337 km 後停留，10/18 又開始升軌，可能在追趕主隊。"),
       ("100870", "315.8 km", ACCENT2,
        "從入軌起就比主隊慢，目前停在第二次停留高度，還沒開始最後一段升軌。"),
       ("100858", "315.3 km", WARN,
        "10/9 前後到第二次停留高度後就沒有再升軌；10/10 起由 316.0 km 緩降到 315.3 km，符合不推進、只受大氣阻力的特徵。")]
for i, (nid, alt, col, note) in enumerate(lag):
    x = Inches(0.6 + i * 4.1)
    _panel(s, x, Inches(1.3), Inches(3.85), Inches(3.6))
    bar = s.shapes.add_shape(1, x, Inches(1.3), Inches(3.85), Inches(0.09)); _fill(bar, col)
    _txt(s, x + Inches(0.3), Inches(1.55), Inches(3.3), Inches(0.5), [(f"NORAD {nid}", 16, INK, True)])
    _txt(s, x + Inches(0.3), Inches(2.05), Inches(3.3), Inches(0.75), [(alt, 30, col, True)])
    _txt(s, x + Inches(0.3), Inches(2.9), Inches(3.3), Inches(1.9), [(note, 12.5, INK, False)], sp=1.25)
_panel(s, Inches(0.6), Inches(5.15), Inches(12.1), Inches(1.15), PANEL2)
_txt(s, Inches(0.9), Inches(5.3), Inches(11.5), Inches(1.4), [
    [("100858 可能是暫時延後升軌，也可能是異常或準備退役——僅憑 TLE 無法分辨。", 14, INK, True)],
    [("如果之後持續下降，就可以作為本系統「異常衰減」偵測的實際驗證案例。", 13, ACCENT2, False)],
], sp=1.3)
foot()

s = slide(); _chip(s, "對系統評估的影響：被算成誤報的，其實多是真實升軌")
_verdict(s, "原因：這 26 顆還沒有真值，評估時把「沒有真值」預設為「沒有機動」，真實機動就被算成了誤報。", color=WARN)
_panel(s, Inches(0.6), Inches(2.05), Inches(5.0), Inches(3.6))
_txt(s, Inches(0.85), Inches(2.2), Inches(4.5), Inches(0.45), [("10/7 評估重跑，L1 規則層誤報率", 14, INK, True)])
_stat(s, Inches(0.6), Inches(2.95), Inches(2.5), "43.6%", "V3 26 顆", WARN, 34)
_stat(s, Inches(3.1), Inches(2.95), Inches(2.5), "5.2%", "其餘負樣本", GOOD, 34)
_txt(s, Inches(0.85), Inches(4.65), Inches(4.5), Inches(2.0),
     [("從升軌觀察可以看出，這段期間被標記的事件大多是真實的升軌機動，不是誤報。", 12.5, MUTE, False)], sp=1.25)
bullets(s, Inches(6.0), Inches(2.15), Inches(6.7), [
    (ACCENT, [("1. 評估時排除升軌期\n", 15, INK, True),
              ("入軌到確認穩定之前的資料不納入誤報率計算；穩定滿 1–2 週後，再當作安靜樣本納入。", 12.5, MUTE, False)]),
    (ACCENT, [("2. 之後補登真值\n", 15, INK, True),
              ("本計畫已取得 V3 的 SpaceX 精密星曆（MEME），可從中標出升軌期間的機動，把這 26 顆變成真正的正樣本。", 12.5, MUTE, False)]),
    (GOOD, [("契約附表 8 判定數字不受影響\n", 15, INK, True),
            ("判定以已通過期中審查的 08-03 快照為準。第 1 種方式本月已實作，見第三節。", 12.5, MUTE, False)]),
], gap=1.2, h=Inches(4.6))
foot()

# ══ 三、L3 ═══════════════════════════════════════════════════════════════
divider("三", "L3 融合評分器：評估口徑修正與 v2 改進", "0.855（舊定義）→ 0.813（修正後）→ 0.859（L3 v2）")

s = slide(); _chip(s, "發現的問題：「沒有真值」被當成「沒有機動」", WARN)
_verdict(s, "原本做法：凡是沒有被機動事件涵蓋的時段，一律當成「安靜」。其中有兩類時段其實沒有任何真值。", color=WARN)
for i, (head, body) in enumerate([
        ("① 還沒有真值的衛星",
         "例如 9 月底入軌的 Starlink V3 26 顆。它們正在大幅升軌，卻被當成「安靜」，"
         "造成 L1 在這 26 顆上的誤報率高達 43.6%。"),
        ("② 真值範圍以外的時段",
         "MEME 真值目前只整理到 09-17，但 TLE 已更新到 10 月。"
         "所有衛星在 09-17 之後的時段，都被預設成安靜。")]):
    x = Inches(0.6 + i * 6.15)
    _panel(s, x, Inches(2.05), Inches(5.95), Inches(2.55))
    _txt(s, x + Inches(0.3), Inches(2.2), Inches(5.4), Inches(0.5), [(head, 17, ACCENT2, True)])
    _txt(s, x + Inches(0.3), Inches(2.8), Inches(5.4), Inches(1.7), [(body, 13.5, INK, False)], sp=1.3)
_panel(s, Inches(0.6), Inches(4.85), Inches(12.1), Inches(1.4), PANEL2)
_txt(s, Inches(0.9), Inches(5.0), Inches(11.5), Inches(1.6), [
    [("修正方式（本月已實作）", 15, GOOD, True)],
    [("每顆衛星只在自己的真值涵蓋期間內取安靜樣本；完全沒有真值的衛星（27 顆）不納入評估。", 13.5, INK, False)],
    [("這也就是第二節建議的處理方式。", 12.5, MUTE, False)],
], sp=1.3)
foot()

s = slide(); _chip(s, "修正前後：L3 AUC 由 0.855 降為 0.813，但新數字才有真值支撐")
_txt(s, Inches(0.6), Inches(1.2), Inches(7.2), Inches(0.4),
     [("同一份資料庫（2026-10-21），三層同一擂台", 12, MUTE, False)])
rows = [["項目", "原本的定義", "修正後"],
        ["納入評估的衛星", "310 顆", "283 顆"],
        ["安靜樣本（負樣本）", "11,373", "4,209"],
        ["L1 規則層誤報率", f"{AR_OLD.loc[L1, 'fpr']:.3f}", f"{AR_NEW.loc[L1, 'fpr']:.3f}"],
        ["L2 統計層最佳單通道 AUC", f"{AR_OLD.loc[L2, 'auc']:.3f}", f"{AR_NEW.loc[L2, 'auc']:.3f}"],
        ["L3 融合評分器 AUC", f"{AR_OLD.loc[L3, 'auc']:.3f}", f"{AR_NEW.loc[L3, 'auc']:.3f}"]]
table(s, Inches(0.6), Inches(1.65), Inches(7.2), rows, col_w=[Inches(3.4), Inches(1.9), Inches(1.9)],
      size=13.5, row_h=Inches(0.6), hl_rows=(5,), align_right=(1, 2))
_panel(s, Inches(8.15), Inches(1.65), Inches(4.55), Inches(3.65))
_txt(s, Inches(8.4), Inches(1.8), Inches(4.1), Inches(0.5), [("為什麼 AUC 反而下降？", 16, ACCENT2, True)])
_txt(s, Inches(8.4), Inches(2.4), Inches(4.1), Inches(4.3), [
    [("被剔除的 7,000 多個「安靜」樣本，大多是衛星平靜運行、模型很容易判對的時段。", 13, INK, False)],
    [("", 6, INK, False)],
    [("舊的評估把這些未經驗證的時段都算成答對，AUC 因此偏高。", 13, INK, False)],
    [("", 6, INK, False)],
    [("修正後的 0.813 雖然較低，卻是有真值支撐的數字。", 13, GOOD, True)],
], sp=1.3)
_txt(s, Inches(0.6), Inches(5.45), Inches(7.2), Inches(1.3), [
    [("口徑說明：本節 0.855、0.813、0.859 都是同一份資料庫上的同條件比較"
      "（283 顆 Starlink，以 MEME 精密星曆為真值，衛星分組交叉驗證）。"
      "期末報告中契約附表 8 的正式判定以 08-03 快照為準，不受本節影響。", 11, MUTE, False)],
], sp=1.2)
foot()

s = slide(); _chip(s, "為挽回 AUC 所做的努力：五步累計 0.813 → 0.858", GOOD)
steps = [("基準\n原 L3", 0.813), ("①\n既有特徵", 0.840), ("②\n新增特徵", 0.847),
         ("③\n調整參數", 0.850), ("④\nLightGBM", 0.853), ("⑤\n背景常數", 0.858)]
cd = CategoryChartData(); cd.categories = [a for a, _ in steps]; cd.add_series("AUC（5 次平均）", [b for _, b in steps])
gf = s.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(0.6), Inches(1.25), Inches(6.6), Inches(5.0), cd)
ch = gf.chart
ch.has_legend = False; ch.has_title = False
ch.font.name = FONT; ch.font.size = Pt(11); ch.font.color.rgb = MUTE
va = ch.value_axis; va.minimum_scale = 0.80; va.maximum_scale = 0.87; va.major_unit = 0.01
va.has_major_gridlines = True; va.major_gridlines.format.line.color.rgb = PANEL2
va.tick_labels.number_format = "0.00"; va.tick_labels.number_format_is_linked = False
va.format.line.fill.background(); ch.category_axis.format.line.color.rgb = MUTE
pl = ch.plots[0]; pl.gap_width = 60
pl.has_data_labels = True; dl = pl.data_labels
dl.number_format = "0.000"; dl.number_format_is_linked = False; dl.position = XL_LABEL_POSITION.OUTSIDE_END
dl.font.size = Pt(12); dl.font.bold = True; dl.font.color.rgb = INK
ser = pl.series[0]
for i, pt_ in enumerate(steps):
    p = ser.points[i]; p.format.fill.solid()
    p.format.fill.fore_color.rgb = MUTE if i == 0 else (GOOD if i == len(steps) - 1 else ACCENT)
_txt(s, Inches(0.6), Inches(6.3), Inches(6.6), Inches(0.5),
     [("同一份資料、5 種不同衛星分組各做一次交叉驗證，取平均（標準差約 0.002）", 10.5, MUTE, False)])
bullets(s, Inches(7.5), Inches(1.3), Inches(5.2), [
    (ACCENT, [("① 評估程式早已算好、但 L3 從未使用的特徵：", 12.5, INK, True),
              ("訊號的時間結構、統計證據與物理阻力的對比、窗內訊噪比", 12, MUTE, False)]),
    (ACCENT, [("② 本月新增特徵：", 12.5, INK, True),
              ("機動前後高度位準差、窗內淨高度變化、傾角與離心率變化、B* 偏離", 12, MUTE, False)]),
    (ACCENT, [("③ 調整模型參數　④ 改用 LightGBM", 12.5, INK, True)]),
    (GOOD, [("⑤ 加入 4 個衛星背景常數：", 12.5, INK, True),
            ("高度、傾角、TLE 更新頻率、雜訊大小", 12, MUTE, False)]),
    (WARN, [("沒有採用：", 12.5, INK, True),
            ("兩個模型取平均（只多 0.001）。刻意不用「時間窗長度」「窗內 TLE 筆數」——"
             "機動與安靜樣本的窗長本來就不同，用了等於偷看答案。", 12, MUTE, False)]),
], gap=1.15, h=Inches(5.5))
foot()

s = slide(); _chip(s, "L3 v2 的特點：AUC 與召回率都明顯優於原版", GOOD)
_panel(s, Inches(0.6), Inches(1.25), Inches(4.3), Inches(3.95))
_txt(s, Inches(0.85), Inches(1.4), Inches(3.9), Inches(0.45), [("特徵", 16, ACCENT, True)])
_txt(s, Inches(0.85), Inches(1.9), Inches(3.9), Inches(0.8), [("46 個", 32, ACCENT2, True)])
_txt(s, Inches(0.85), Inches(2.8), Inches(3.9), Inches(3.8), [
    [("全部只從 TLE 推得。", 13, INK, False)],
    [("", 6, INK, False)],
    [("B* 的比較基準只用該時刻之前 30 天的資料，線上運作時也能照做。", 13, INK, False)],
    [("", 6, INK, False)],
    [("模型：LightGBM", 13, MUTE, False)],
], sp=1.3)
_txt(s, Inches(5.2), Inches(1.25), Inches(7.5), Inches(0.45), [("正式評估結果（三層同一擂台，誤報率 ≤ 5%）", 15, INK, True)])
o, v = AR_NEW.loc[L3], AR_NEW.loc[L3V2]
table(s, Inches(5.2), Inches(1.75), Inches(7.5), [
    ["指標", "原 L3", "L3 v2"],
    ["AUC", f"{o.auc:.3f}", f"{v.auc:.3f}"],
    ["召回率", f"{o.recall:.3f}", f"{v.recall:.3f}"],
    ["大型機動召回率", f"{o.rec_large:.3f}", f"{v.rec_large:.3f}"],
    ["中型機動召回率", f"{o.rec_medium:.3f}", f"{v.rec_medium:.3f}"],
], col_w=[Inches(3.5), Inches(2.0), Inches(2.0)], size=13.5, row_h=Inches(0.5), align_right=(1, 2))
_txt(s, Inches(5.2), Inches(4.4), Inches(7.5), Inches(0.45), [("可信度檢查", 15, INK, True)])
bullets(s, Inches(5.2), Inches(4.85), Inches(7.5), [
    (GOOD, [("提升來自偵測能力，不是背景資訊：", 12.5, INK, True),
            ("四個傾角族群（43°、53°、70°、97°）各自 AUC 都提升（0.848–0.886）；只用 4 個背景常數時 AUC 僅 0.56，接近亂猜。", 12, MUTE, False)]),
    (GOOD, [("換一批衛星也能用：", 12.5, INK, True),
            ("以從未參與訓練的衛星測試，AUC 0.858（原版 0.808）。", 12, MUTE, False)]),
], gap=1.15, h=Inches(2.0))
foot()

s = slide(); _chip(s, "限制與下一步", WARN)
_txt(s, Inches(0.6), Inches(1.2), Inches(6.0), Inches(0.45), [("限制（如實揭露）", 16, WARN, True)])
_panel(s, Inches(0.6), Inches(1.7), Inches(6.0), Inches(2.7))
_txt(s, Inches(0.85), Inches(1.8), Inches(2.4), Inches(0.5), [("換到未來時段", 14, INK, True)])
_stat(s, Inches(3.2), Inches(1.8), Inches(3.2), "0.600", "時間盲測 AUC（原版 0.593）", WARN, 32)
_txt(s, Inches(0.85), Inches(3.3), Inches(5.5), Inches(1.1),
     [[("前段訓練、後段測試，新舊版都一樣。", 12, MUTE, False)],
      [("0.859 代表「換一批衛星仍可用」，不代表「未來時段也能維持」。", 12, MUTE, False)]], sp=1.2)
_panel(s, Inches(0.6), Inches(4.6), Inches(6.0), Inches(2.15))
_txt(s, Inches(0.85), Inches(4.7), Inches(5.5), Inches(2.0), [
    [("尚未接上線上系統", 14, INK, True)],
    [("v2 部分特徵（如機動前後位準差）需要事件之後 48 小時的資料，接上線上後判定會延遲約 2 天；即時計算的部分尚待實作。", 12, MUTE, False)],
], sp=1.25)
_txt(s, Inches(7.0), Inches(1.2), Inches(5.7), Inches(0.45), [("下一步", 16, GOOD, True)])
for i, (head, body) in enumerate([
        ("研究時間漂移", "找出前後時段落差的原因（如 2026 年多個軌道殼層整體降低高度、太陽活動變化），再決定是否需要定期重新訓練。"),
        ("延長真值範圍", "以 10 月新下載的 MEME 精密星曆更新真值，讓 09-17 之後的時段也能納入評估。"),
        ("接上線上系統", "實作 v2 特徵的即時計算，並在介面標示約 2 天的判定延遲。")]):
    y = Inches(1.7 + i * 1.72)
    _panel(s, Inches(7.0), y, Inches(5.7), Inches(1.55))
    _txt(s, Inches(7.15), y + Inches(0.1), Inches(0.6), Inches(0.7), [(str(i + 1), 28, GOOD, True)])
    _txt(s, Inches(7.8), y + Inches(0.12), Inches(4.8), Inches(0.4), [(head, 14, INK, True)])
    _txt(s, Inches(7.8), y + Inches(0.5), Inches(4.8), Inches(1.0), [(body, 11.5, MUTE, False)], sp=1.15)
foot()

prs.save(OUT)
print("→", OUT, f"（{len(prs.slides)} 頁）")
