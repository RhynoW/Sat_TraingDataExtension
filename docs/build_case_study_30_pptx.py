# -*- coding: utf-8 -*-
"""build_case_study_pptx.py — 案例研究簡報：10 衛星偵測總覽與 STARLINK-37471 逐層解析
產出：docs/案例研究_30顆衛星偵測總覽與單星逐層解析_20261021.pptx（2026-10-21 新增第五節：批次偵測 Starlink V3 26 顆）
底本：docs/案例研究_十衛星偵測總覽與單星逐層解析_20261007.md 之延伸版（原10顆基礎上擴充至30顆，新增20顆數字直接以現行程式重新算出）
樣式沿用本專案既有簡報（深海軍藍主題），本檔獨立維護。
"""
import sys, math
import json as _json
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DOCS = Path(__file__).parent
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
W, H = Inches(13.333), Inches(7.5)


def _fill(shape, color):
    shape.fill.solid(); shape.fill.fore_color.rgb = color
    shape.line.fill.background(); shape.shadow.inherit = False


def _bg(slide):
    r = slide.shapes.add_shape(1, 0, 0, W, H); _fill(r, BG); r.shadow.inherit = False


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


def _footer(slide, n):
    _txt(slide, Inches(0.5), Inches(7.06), Inches(10), Inches(0.32),
         [("TASA-S-1150268　案例研究：30 衛星偵測總覽與單星逐層解析＋Starlink V3 批次偵測", 9.5, MUTE, False)])
    _txt(slide, Inches(12.4), Inches(7.06), Inches(0.7), Inches(0.32),
         [(str(n), 9.5, MUTE, False)], align=PP_ALIGN.RIGHT)


def bullets(slide, x, y, w, items, size=14.5, gap=1.22, h=Inches(4.8)):
    tb = slide.shapes.add_textbox(x, y, w, h); tf = tb.text_frame; tf.word_wrap = True
    for i, (mc, runs) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.line_spacing = gap; p.space_after = Pt(3)
        b = p.add_run(); b.text = "▍ "; b.font.name = FONT; b.font.size = Pt(size); b.font.color.rgb = mc
        for (text, sz, color, bold) in runs:
            r = p.add_run(); r.text = text
            r.font.name = FONT; r.font.size = Pt(sz); r.font.color.rgb = color; r.font.bold = bold
    return tb


def table(slide, x, y, w, rows, col_w, head=True, size=11.5, row_h=Inches(0.42)):
    nrows, ncols = len(rows), len(rows[0])
    t = slide.shapes.add_table(nrows, ncols, x, y, w, row_h * nrows).table
    for c, cw in enumerate(col_w):
        t.columns[c].width = cw
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = t.cell(r, c); cell.text = str(val)
            cell.fill.solid()
            cell.fill.fore_color.rgb = PANEL2 if (head and r == 0) else (PANEL if r % 2 else BG)
            p = cell.text_frame.paragraphs[0]
            p.font.name = FONT; p.font.size = Pt(size)
            p.font.color.rgb = ACCENT2 if (head and r == 0) else INK
            p.font.bold = head and r == 0
    return t


prs = Presentation(); prs.slide_width = W; prs.slide_height = H
BLANK = prs.slide_layouts[6]
def slide():
    s = prs.slides.add_slide(BLANK); _bg(s); return s


def divider(title, sub):
    s = slide()
    band = s.shapes.add_shape(1, 0, Inches(2.7), W, Inches(2.0)); _fill(band, PANEL)
    bar = s.shapes.add_shape(1, Inches(0.9), Inches(2.9), Inches(0.18), Inches(1.6)); _fill(bar, ACCENT)
    _txt(s, Inches(1.3), Inches(3.0), Inches(11), Inches(1.0), [(title, 34, INK, True)])
    _txt(s, Inches(1.3), Inches(4.05), Inches(11), Inches(0.6), [(sub, 16, ACCENT, False)])
    return s


N = [0]
def foot():
    N[0] += 1
    _footer(prs.slides[-1], N[0])


# ══ 1 封面 ═══════════════════════════════════════════════════════════════
s = slide()
band = s.shapes.add_shape(1, 0, Inches(2.3), W, Inches(2.7)); _fill(band, PANEL)
_txt(s, Inches(0.9), Inches(1.5), Inches(11.5), Inches(0.6),
     [("案　例　研　究", 20, ACCENT, True)])
_txt(s, Inches(0.9), Inches(2.55), Inches(11.6), Inches(1.3),
     [("30 顆衛星偵測總覽", 38, INK, True)])
_txt(s, Inches(0.9), Inches(3.5), Inches(11.6), Inches(0.9),
     [("與單星三層判斷邏輯逐層解析", 38, INK, True)])
_txt(s, Inches(0.9), Inches(5.15), Inches(11.6), Inches(0.6),
     [("把 Web App 的判斷邏輯，從一筆 TLE 差值講到最終判定", 16, ACCENT, False)])
_txt(s, Inches(0.9), Inches(5.65), Inches(11.6), Inches(0.6),
     [("＋ 批次偵測 Starlink V3（Flight 14）26 顆入軌後軌道機動", 16, ACCENT2, False)])
_txt(s, Inches(0.9), Inches(6.55), Inches(11.6), Inches(0.5),
     [("計畫案號 TASA-S-1150268　｜　數字核算日 2026-10-07（第五節 Starlink V3：2026-10-21）", 12, MUTE, False)])
foot()

# ══ 2 大綱 ═══════════════════════════════════════════════════════════════
s = slide(); _chip(s, "簡報大綱")
rows = [
    ("一", "30 顆衛星樣本與選取理由", "福衛五號／福衛八號／國際太空站＋29 顆涵蓋GEO RPO/星系/IDS真值等對照", ACCENT),
    ("二", "30 顆衛星偵測總覽表", "統一偵測摘要，全部歷史 TLE 實跑", ACCENT2),
    ("三", "單星深入解析：STARLINK-37471", "規則層→統計層→機器學習層，逐層看判斷依據（含一次誠實更正）", GOOD),
    ("四", "其餘 29 顆衛星逐層解析", "每顆衛星：卡片摘要＋時間序列圖（日期標註）＋機動日期清單", ACCENT2),
    ("五", "批次偵測：Starlink V3（Flight 14）26 顆", "同一套流程一次跑完一整批新入軌衛星，對照升軌期與 MEME 精密星曆", WARN),
    ("六", "結語：三十個案例，同一套邏輯", "多層交叉驗證的實際運作樣貌", ACCENT),
]
y = Inches(1.3)
for tag, title, desc, col in rows:
    card = s.shapes.add_shape(1, Inches(0.6), y, Inches(12.1), Inches(0.78)); _fill(card, PANEL)
    bar = s.shapes.add_shape(1, Inches(0.6), y, Inches(0.16), Inches(0.78)); _fill(bar, col)
    _txt(s, Inches(0.95), y + Inches(0.04), Inches(1.0), Inches(0.7),
         [(tag, 18, col, True)], anchor=MSO_ANCHOR.MIDDLE)
    _txt(s, Inches(1.95), y + Inches(0.04), Inches(10.5), Inches(0.7),
         [[(title, 15.5, INK, True)], [(desc, 12.5, MUTE, False)]], anchor=MSO_ANCHOR.MIDDLE, sp=1.1)
    y += Inches(0.9)
foot()

# ══ 一、樣本 ══════════════════════════════════════════════════════════════
divider("一、30 顆衛星樣本", "福衛五號／福衛八號／國際太空站 ＋ 27 顆對照樣本")
foot()

s = slide(); _chip(s, "樣本涵蓋三種軌道、Starlink 與非 Starlink 域")
table(s, Inches(0.5), Inches(1.35), Inches(12.3), [
    ["衛星", "NORAD", "類型", "選取理由"],
    ["FORMOSAT-5", "42920", "台灣光學遙測，SSO", "指定樣本；長期自主衛星對照"],
    ["FORMOSAT-8A", "66666", "台灣新一代星系首星", "指定樣本；新發射早期調校行為"],
    ["ISS (ZARYA)", "25544", "國際太空站，LEO", "指定樣本；長年定期拉高軌道"],
    ["STARLINK-37471", "68802", "Starlink，SSO", "深入解析對象；已知真實大型爬升"],
    ["STARLINK-30805／5846", "58214／56492", "Starlink，LEO", "高頻率小幅站位維持對照"],
    ["QZS-7", "100270", "日本準天頂衛星，GEO", "非 Starlink／非 LEO 真實公開案例"],
    ["FORMOSAT7-1/COSMIC2-1", "44349", "福衛七號星系，LEO", "已知追蹤缺口，觀察資料品質影響"],
    ["YAOGAN-35 A", "49390", "中國遙感衛星，LEO", "非 Starlink／非台美系對照"],
    ["JASON 3", "41240", "法美海洋測高衛星，LEO", "IDS 第二真值集成員"],
], col_w=[Inches(2.7), Inches(1.8), Inches(3.0), Inches(4.8)], row_h=Inches(0.52), size=11)
foot()

s = slide(); _chip(s, "樣本涵蓋三種軌道、Starlink 與非 Starlink 域（續，20 顆新增樣本之一）")
table(s, Inches(0.5), Inches(1.15), Inches(12.3), [
    ["衛星", "NORAD", "類型", "選取理由"],
    ["TJS-10", "58204", "中國技術試驗衛星，GEO", "GEO RPO 案例（與 TJS-3 共組）"],
    ["TJS-3", "43874", "中國技術試驗衛星，GEO", "GEO RPO 案例（與 TJS-10 共組）"],
    ["USA 271", "41745", "美國軍用衛星，GEO", "GEO RPO 案例（與 SKYNET 5A 共組）"],
    ["SKYNET 5A", "30794", "英國軍用通訊衛星，GEO", "GEO RPO 案例（與 USA 271 共組）"],
    ["ONEWEB-0063", "45448", "中型通訊星系，LEO", "與 Starlink 不同規模之通訊星系對照"],
    ["QIANFAN-146", "69105", "中國千帆星系，LEO", "中國新興巨型通訊星系對照"],
    ["GAOFEN 1-03", "43260", "中國高分遙測星系，LEO", "中國遙測星系對照"],
    ["JILIN-01-09", "43943", "中國吉林遙測星系，LEO", "中國遙測星系對照"],
    ["SENTINEL-6B", "66514", "歐美海洋測高衛星，LEO", "IDS 第二真值集成員"],
    ["CRYOSAT 2", "36508", "歐洲極地觀測衛星，LEO", "IDS 真值集；ΔV 反解高精度案例（r=0.975）"],
], col_w=[Inches(2.7), Inches(1.8), Inches(3.0), Inches(4.8)], row_h=Inches(0.52), size=11)
foot()

s = slide(); _chip(s, "樣本涵蓋三種軌道、Starlink 與非 Starlink 域（續，20 顆新增樣本之二）")
table(s, Inches(0.5), Inches(1.15), Inches(12.3), [
    ["衛星", "NORAD", "類型", "選取理由"],
    ["SWOT", "54754", "美法地表水文衛星，LEO", "IDS 真值集；鄰近機動污染案例（r=0.512）"],
    ["GRACE-FO 1／2", "43476／43477", "美德重力測量衛星對，LEO", "編隊飛行雙星對照"],
    ["SPOT 5", "27421", "法國長壽命遙測衛星，LEO", "28 年超長歷史對照"],
    ["JASON 2", "33105", "法美海洋測高衛星，LEO", "IDS 真值集；Jason-3 前代任務"],
    ["FORMOSAT7-2/COSMIC2-2", "44351", "福衛七號星系，LEO", "與 4349 同星系之另一成員"],
    ["FORMOSAT 3A", "29047", "台灣已退役氣象衛星，LEO", "退役星系，物理模型素淨對照"],
    ["NAVSTAR 59", "29601", "美國 GPS 導航衛星，MEO", "導航星系對照（非遙測/通訊用途）"],
    ["GAOFEN 12", "44819", "中國高分遙測星系，LEO", "與高分 1-03 同星系之另一成員"],
    ["JILIN-01 GAOFEN 3H", "46460", "中國吉林遙測星系，LEO", "與吉林 01-09 同星系之另一成員"],
], col_w=[Inches(2.7), Inches(1.8), Inches(3.0), Inches(4.8)], row_h=Inches(0.52), size=11)
foot()

# ══ 二、總覽表 ════════════════════════════════════════════════════════════
divider("二、30 顆衛星偵測總覽", "統一偵測摘要，對全部歷史 TLE 實際跑一次")
foot()

s = slide(); _chip(s, "路由主判、融合旗標、Model 2 異常次數（全部為實跑結果）")
table(s, Inches(0.4), Inches(1.3), Inches(12.5), [
    ["衛星", "TLE筆數", "軌域", "路由主判", "融合旗標", "融合最高機率", "Model2異常"],
    ["FORMOSAT-5", "11,980", "LEO", "Model2+NRLMSIS", "3", "0.830", "11"],
    ["FORMOSAT-8A", "1,278", "LEO", "Model2+NRLMSIS", "11", "0.767", "16"],
    ["ISS (ZARYA)", "47,687", "LEO", "Model2+NRLMSIS", "1,700", "0.967", "644"],
    ["STARLINK-37471", "510", "LEO/Starlink", "Model1+融合評分器", "43", "0.912", "64"],
    ["STARLINK-30805", "421", "LEO/Starlink", "Model1+融合評分器", "12", "0.911", "12"],
    ["STARLINK-5846", "530", "LEO/Starlink", "Model1+融合評分器", "18", "0.956", "7"],
    ["QZS-7", "111", "GEO", "Model2+NRLMSIS", "0", "0.499", "16"],
    ["FORMOSAT7-1/COSMIC2-1", "1,985", "LEO", "Model2+NRLMSIS", "13", "0.776", "26"],
    ["YAOGAN-35 A", "3,093", "LEO", "Model2+NRLMSIS", "48", "0.812", "22"],
    ["JASON 3", "10,212", "LEO", "Model2+NRLMSIS", "4", "0.697", "27"],
], col_w=[Inches(2.5), Inches(1.4), Inches(1.5), Inches(2.3), Inches(1.4), Inches(1.7), Inches(1.7)], row_h=Inches(0.47), size=10.5)
foot()

with open(DOCS.parent / "data" / "benchmark" / "case_study_cards_20261007" / "overview20.json", encoding="utf-8") as _f:
    _OV20 = _json.load(_f)
_ov20_rows = [["衛星", "TLE筆數", "軌域", "路由主判", "融合旗標", "融合最高機率", "Model2異常"]]
for _nid, _r in _OV20.items():
    if _r.get("status") != "ok":
        _ov20_rows.append([_r.get("name", _nid), "—", "—", "錯誤", "—", "—", "—"])
        continue
    _ov20_rows.append([
        _r.get("name", _nid),
        f"{_r.get('n_tle', 0):,}",
        _r.get("orbit_class", "—"),
        _r.get("routed_primary", "—").split("(")[0].split("+")[0].strip(),
        str(_r.get("fusion_flags", "—")) if _r.get("fusion_flags") is not None else "—",
        f"{_r.get('fusion_max_prob', 0):.3f}" if _r.get("fusion_max_prob") is not None else "—",
        str(_r.get("model2_anomalies", "—")) if _r.get("model2_anomalies") is not None else "—",
    ])
_half = (len(_ov20_rows) - 1 + 1) // 2 + 1
for _chunk, _lab in [(_ov20_rows[0:1] + _ov20_rows[1:_half], "之一"), (_ov20_rows[0:1] + _ov20_rows[_half:], "之二")]:
    s = slide(); _chip(s, f"路由主判、融合旗標、Model 2 異常次數（續，20 顆新增樣本{_lab}）")
    table(s, Inches(0.4), Inches(1.3), Inches(12.5), _chunk,
          col_w=[Inches(2.5), Inches(1.4), Inches(1.5), Inches(2.3), Inches(1.4), Inches(1.7), Inches(1.7)],
          row_h=Inches(0.47), size=10.5)
    foot()

s = slide(); _chip(s, "怎麼讀這張表")
bullets(s, Inches(0.7), Inches(1.45), Inches(12.0), [
    (ACCENT2, [("路由主判取決於是不是 Starlink", 16, INK, True)]),
    (MUTE, [("Starlink → Model 1(LightGBM)+融合評分器；其餘（含福衛、太空站、QZS-7）→ Model 2(無監督)+NRLMSIS 物理殘差。", 14, INK, False)]),
    (ACCENT2, [("異常次數跟歷史長短有關，不代表「比較危險」", 16, INK, True)]),
    (MUTE, [("ISS 歷史最長（26年、47,687筆），異常次數也最多（644次），因為長年需要定期拉高軌道。", 14, INK, False)]),
    (ACCENT2, [("QZS-7 融合旗標 0 次，但不是沒偵測到", 16, INK, True)]),
    (MUTE, [("它是 GEO、非 Starlink，融合評分器不是它的主判路徑；真正依據是 16 次 Model 2 異常，對應其 2026 年真實軌道提升事件。", 14, INK, False)]),
], size=14.5, gap=1.3)
foot()

# ══ 三、深入案例 ══════════════════════════════════════════════════════════
divider("三、單星深入解析：STARLINK-37471", "從一筆 TLE 差值，講到最終判定")
foot()

s = slide(); _chip(s, "⚠ 製作過程中的一次誠實更正")
bullets(s, Inches(0.7), Inches(1.45), Inches(12.0), [
    (WARN, [("原文件記載：", 16, INK, True), ("「2026-06-21 09:38:42Z 執行 Δa=+50.3km 大型升軌」", 15, WARN, True)]),
    (MUTE, [("重新查核完整 TLE 半長軸時序後發現：實際爬升集中在 06-15～06-18（約3天），06-18 已穩定，", 14.5, INK, False)]),
    (MUTE, [("06-21 其實是軌道已穩定後的時間點。", 14.5, INK, False)]),
    (ACCENT2, [("真正原因", 16, INK, True)]),
    (MUTE, [("「06-21」來自 MEME 真值檔兩筆取樣點中較晚的一筆（相隔近7天），真值檔把整段期間的淨變化", 14, INK, False)]),
    (MUTE, [("（+50.3km）整筆記在這個區間——+50.3 公里數字正確，但不能理解成「06-21 那天發生了爬升」。", 14, INK, False)]),
    (GOOD, [("本投影片之後的分析，改用實際可觀測到爬升訊號的時間點（06-16）。", 14.5, GOOD, True)]),
], size=14, gap=1.25)
foot()

s = slide(); _chip(s, "軌道爬升軌跡：半長軸隨時間變化")
table(s, Inches(0.8), Inches(1.4), Inches(6.0), [
    ["日期", "半長軸 a (km)"],
    ["06-14", "6797.1（爬升前）"],
    ["06-15", "6797.4 → 6809.6"],
    ["06-16", "6820.2 → 6832.3"],
    ["06-17", "6832.9 → 6841.8"],
    ["06-18", "6843.8（爬升完成）"],
    ["06-19～06-24", "6843.6～6843.9（穩定）"],
], col_w=[Inches(2.2), Inches(3.8)], row_h=Inches(0.56), size=13)
_txt(s, Inches(7.1), Inches(1.5), Inches(5.6), Inches(4.5), [
    [("淨變化", 15, ACCENT2, True)],
    [("約 3 天內爬升 +46.7 公里", 14, INK, False)],
    [("（與 MEME 真值 +50.3km 量級一致）", 13, MUTE, False)],
    [("", 10, INK, False)],
    [("代表性單筆轉移（本案例分析對象）", 15, ACCENT2, True)],
    [("06-16 14:00 → 06-16 20:00（6小時）", 14, INK, False)],
    [("Δa = +7.67 公里", 14, GOOD, True)],
    [("Δi / Δe / RAAN殘差 幾乎無變化", 13, MUTE, False)],
    [("（符合「沿軌推力只改變軌道大小」的物理預期）", 12, MUTE, False)],
], sp=1.3)
foot()

s = slide(); _chip(s, "Layer 1 規則層：六條規則怎麼看這筆 +7.67km")
table(s, Inches(0.5), Inches(1.35), Inches(12.3), [
    ["規則", "判定", "為什麼"],
    ["P1 單調衰減抑制", "不抑制", "Δa 為正值，不符合大氣衰減特徵"],
    ["P2 高度自適應閾值", "✅ 觸發", "此高度門檻約1.4~1.5km，+7.67km遠超過"],
    ["P3 B*抑制", "不抑制", "B*不足以解釋這麼大的上升量"],
    ["P4 多窗口補充", "✅ 觸發", "短窗重掃同樣抓到"],
    ["P5 F10.7自適應倍率", "✅ 觸發", "F10.7=116.6 sfu調整後，+7.67km仍遠超標"],
    ["P6 星座/軌域感知", "✅ 觸發", "SSO倍率調整後仍判定異常"],
    ["合併結果", "✅ 判定為機動候選", "4條規則同時觸發，無抑制規則介入"],
], col_w=[Inches(3.0), Inches(2.3), Inches(7.0)], row_h=Inches(0.52), size=12)
foot()

s = slide(); _chip(s, "Layer 2 統計層：四種方法交叉比對")
table(s, Inches(0.5), Inches(1.35), Inches(12.3), [
    ["方法", "分數", "是否觸發", "白話意義"],
    ["CUSUM（累積和）", "歸零後重新累積", "✅ 觸發", "偵測到持續性位移的起點"],
    ["BOCPD（貝氏線上變點）", "0.055~0.07（偏低）", "❌ 未觸發", "對漸進爬升不如對瞬間跳變敏感"],
    ["SSA（奇異譜分析）", "61.2（遠高於平常）", "✅ 觸發", "濾掉正常趨勢後，突兀程度明顯"],
    ["3σ-MAD（同儕比較）", "223.1（遠高於門檻3）", "✅ 觸發", "跟自己、跟其他衛星比都是異常"],
], col_w=[Inches(2.8), Inches(2.6), Inches(1.6), Inches(5.3)], row_h=Inches(0.6), size=12.5)
_txt(s, Inches(0.5), Inches(4.5), Inches(12.0), Inches(0.8),
     [("四個方法有三個明確觸發，只有 BOCPD 沒有搶先反應——這正是用四種方法而非一種的原因：", 13.5, MUTE, False)])
_txt(s, Inches(0.5), Inches(4.85), Inches(12.0), Inches(0.5),
     [("單一方法可能會漏掉，多種方法交叉比對比較不容易被騙。", 13.5, MUTE, False)])
foot()

s = slide(); _chip(s, "Layer 3 機器學習層：Model 1 與融合評分器")
bullets(s, Inches(0.7), Inches(1.4), Inches(12.0), [
    (ACCENT2, [("Model 1（逐窗口監督式判斷）", 16, INK, True)]),
    (MUTE, [("這一刻機率 61.2%（門檻 48.2%，超過）；阻力殘差 7.68km（遠超 0.30km 門檻）→ ", 14, INK, False),
            ("✅ 標記為機動", 14, GOOD, True)]),
    (ACCENT2, [("融合評分器（整合五通道，前後24小時窗）", 16, INK, True)]),
    (MUTE, [("爬升當下（06-16 20:00）分數僅 9.5%（偏低）；約2.5天後（06-19 06:00）分數衝到 ", 14, INK, False),
            ("87.4%（門檻65.9%，超過）", 14, GOOD, True)]),
    (WARN, [("為什麼融合評分器不是在當下反應最強？", 15, INK, True)]),
    (MUTE, [("融合評分器看的是「前後24小時整體有多異常」，要等訊號在窗口內累積到最濃縮才衝過門檻——", 13.5, INK, False)]),
    (MUTE, [("這跟 Model 1 當下就反應的節奏剛好互補，不是矛盾。", 13.5, INK, False)]),
], size=14, gap=1.25)
foot()



def episode_table_slide(nid, title, kind):
    """研判為機動之日期清單：對應TASA委託需求，具體列出時間點供委員核對。
    連續 <=48h 之判定已合併為同一事件（episode），峰值為該事件內最高分數。"""
    eps = EPISODES.get(nid, [])
    s = slide(); _chip(s, f"{title}：研判為機動之日期清單（共 {len(eps)} 次事件）")
    val_label = "峰值信心指數" if kind == "fusion" else "峰值殘差(km)"
    header = ["日期範圍", "筆數", val_label]
    if eps:
        ncols = min(3, max(1, math.ceil(len(eps) / 15)))
        rows_per_col = math.ceil(len(eps) / ncols)
        total_w = 12.3
        col_total_w = total_w / ncols
        for c in range(ncols):
            chunk = eps[c * rows_per_col:(c + 1) * rows_per_col]
            if not chunk:
                continue
            rows = [header] + [
                [d0 if d0 == d1 else f"{d0}~{d1}", str(n),
                 f"{peak:.3f}" if kind == "fusion" else f"{peak:.2f}"]
                for d0, d1, n, peak in chunk]
            table(s, Inches(0.5 + col_total_w * c), Inches(1.2), Inches(col_total_w - 0.15), rows,
                  col_w=[Inches(col_total_w * 0.5), Inches(col_total_w * 0.18), Inches(col_total_w * 0.32)],
                  row_h=Inches(0.36), size=10.5)
    else:
        _txt(s, Inches(0.5), Inches(2.5), Inches(12), Inches(1),
             [("此衛星於本圖資料範圍內無判定為機動之事件", 16, MUTE, False)])
    note = "判定門檻：融合評分器 >= 0.659" if kind == "fusion" else "判定門檻：阻力殘差絕對值 > 0.30 km"
    _txt(s, Inches(0.5), Inches(6.85), Inches(12.3), Inches(0.3),
         [(note + "；相隔 48 小時內之判定點合併為同一事件", 10, MUTE, False)])
    foot()
    return s


with open(DOCS / "case_study_figs" / "episodes_all.json", encoding="utf-8") as _f:
    EPISODES = {int(k): [tuple(e) for e in v] for k, v in _json.load(_f).items()}
FIGDIR = DOCS / "case_study_figs"


def timeline_slide(nid, title, caption=None):
    """全幅時間序列圖：對應 TASA 委託需求，讓委員會一目瞭然機動發生的時間點。"""
    img = FIGDIR / f"{nid}_timeline.png"
    s = slide(); _chip(s, f"{title}：機動偵測時間序列")
    if img.exists():
        s.shapes.add_picture(str(img), Inches(0.25), Inches(1.1), width=Inches(12.83))
    else:
        _txt(s, Inches(0.5), Inches(3.0), Inches(12), Inches(1), [("圖檔未生成", 16, WARN, True)])
    if caption:
        _txt(s, Inches(0.5), Inches(6.78), Inches(12.3), Inches(0.3), [(caption, 10.5, MUTE, False)])
    foot()
    return s


timeline_slide(68802, "STARLINK-37471",
                "白色虛線＝本報告逐層解析選定事件（06-16）；顏色依融合評分器信心指數分級：藍低／黃中／紅高或已判定")
episode_table_slide(68802, "STARLINK-37471", "fusion")


# ══ 四、其餘 29 顆衛星逐層解析 ══════════════════════════════════════════════
divider("四、其餘 29 顆衛星逐層解析", "選取規則：全歷史｜Δa｜最大的已判定機動候選轉移（無則改選｜Δa｜最大者）")
foot()


def sat_card(title, bg_note, rows, verdict, verdict_color=GOOD):
    s = slide(); _chip(s, title)
    if bg_note:
        _txt(s, Inches(0.7), Inches(1.1), Inches(11.8), Inches(0.4),
             [(bg_note, 12.5, MUTE, False)])
    table(s, Inches(0.5), Inches(1.6), Inches(12.3), rows,
          col_w=[Inches(2.2), Inches(10.1)], row_h=Inches(0.56), size=12.5)
    y = Inches(1.6) + Inches(0.56) * len(rows) + Inches(0.25)
    _txt(s, Inches(0.5), y, Inches(12.3), Inches(1.2),
         [("判讀：", 13, ACCENT2, True), (verdict, 13, INK, False)] if isinstance(verdict, str) else verdict,
         sp=1.2)
    foot()
    return s


sat_card("4.1 FORMOSAT-5（福衛五號）", "事件：2017-08-24 22:01Z，發射隔天第一筆轉移，Δa=+3.49km", [
    ["L1 規則層", "P2/P4/P5/P6 四條觸發 → 合併判定：機動候選"],
    ["L2 統計層", "CUSUM/SSA/MAD 觸發，BOCPD 未觸發"],
    ["L3（非Starlink）", "阻力殘差 3.49km（超門檻）→ 判定機動；Model2 判為異常"],
    ["全歷史", "9,194 筆轉移中 22 筆合併判定；Model2 異常 11 次"],
], "發射入軌後的早期軌道調整，四層一致判定為真實事件，屬預期中的行為。")

timeline_slide(42920, "福衛五號",
                "白色虛線＝本報告逐層解析選定事件；顏色依阻力殘差量級分級：藍低／黃中／紅高")
episode_table_slide(42920, "福衛五號", "drag")


sat_card("4.2 FORMOSAT-8A（福衛八號 A 星）", "事件：2026-02-02 05:12Z，上線後約1.5個月（調校期），Δa=+2.12km", [
    ["L1 規則層", "P2/P4/P5/P6 四條觸發 → 合併判定：機動候選"],
    ["L2 統計層", "CUSUM/SSA/MAD 觸發，BOCPD 未觸發"],
    ["L3（非Starlink）", "阻力殘差 2.12km（超門檻）→ 判定機動；Model2 判為異常"],
    ["全歷史", "925 筆轉移中 24 筆合併判定（比例約2.6%，高於福衛五號的0.24%）"],
], "新衛星早期調校機動，各層一致確認；合併判定比例符合新衛星調整較頻繁之預期。")

timeline_slide(66666, "福衛八號A星",
                "白色虛線＝本報告逐層解析選定事件；顏色依阻力殘差量級分級：藍低／黃中／紅高")
episode_table_slide(66666, "福衛八號A星", "drag")


sat_card("4.3 國際太空站（ISS/ZARYA）", "事件：1998-11-23 08:22Z，Zarya曙光號發射後資料庫最早大型提升之一，Δa=+51.84km", [
    ["L1 規則層", "P2/P4/P5/P6 + Δi/Δe/ΔΩ 其中之一 → 合併判定：機動候選"],
    ["L2 統計層", "CUSUM/SSA/MAD 觸發，BOCPD 未觸發"],
    ["L3（非Starlink）", "阻力殘差 51.91km → 判定機動；Model2 z值達519（10顆中最極端）"],
    ["全歷史", "47,129筆中592筆合併判定；Model2異常644次（10顆中最多）"],
], "長年需定期拉高軌道抵銷阻力，644次異常反映正常營運模式，不是風險訊號。")

timeline_slide(25544, "國際太空站",
                "白色虛線＝本報告逐層解析選定事件；顏色依阻力殘差量級分級：藍低／黃中／紅高")
episode_table_slide(25544, "國際太空站", "drag")


sat_card("4.4 STARLINK-30805 — 「沒有機動」對照範例", "全部387筆轉移「零」合併判定；改選全歷史最大Δa：2026-09-21 11:06Z，+0.59km", [
    ["L1 規則層", "P1~P6 全部 False → 合併判定：非機動候選"],
    ["L2 統計層", "三方法技術上「觸發」但分數量級遠低於其他案例（SSA僅25.4）"],
    ["L3（Starlink）", "Model1機率42.9%（門檻48.2%，未達標）；阻力殘差0.60km"],
    ["融合評分器", "此刻僅13.4%；全歷史最高點86.8%發生在另一天（07-04）"],
], [("判讀：", 13, ACCENT2, True),
    ("四層一致同意「這不是機動」，純站位維持波動。但此衛星07-04另有一次真實86.8%高分偵測，", 13, INK, False),
    ("說明「這次沒事」不代表「全程沒事」。", 13, INK, False)])

timeline_slide(58214, "STARLINK-30805",
                "白色虛線＝本報告逐層解析選定事件；顏色依融合評分器信心指數分級：藍低／黃中／紅高或已判定")
episode_table_slide(58214, "STARLINK-30805", "fusion")


sat_card("4.5 STARLINK-5846", "事件：2026-04-09 14:00Z，Δa=+2.89km", [
    ["L1 規則層", "P2/P4/P5/P6 四條觸發 → 合併判定：機動候選"],
    ["L2 統計層", "CUSUM/SSA/MAD 觸發，BOCPD 未觸發"],
    ["L3（Starlink）", "Model1機率52.5%（超門檻）"],
    ["融合評分器", "此刻僅3.3%；全歷史最高點94.9%發生在07-13"],
], "融合評分器峰值與規則層判定時刻不同步，與4.4、第三節STARLINK-37471案例一致印證「整合窗口」設計特性。")

timeline_slide(56492, "STARLINK-5846",
                "白色虛線＝本報告逐層解析選定事件；顏色依融合評分器信心指數分級：藍低／黃中／紅高或已判定")
episode_table_slide(56492, "STARLINK-5846", "fusion")


sat_card("4.6 QZS-7 — 物理模型邊界案例 ⚠", "唯一仍在軌道轉移階段的衛星；事件：2026-08-12 12:23Z，Δa=+8,407km", [
    ["L1 規則層", "P2/P4/P5/P6/其他 全數觸發（Δi -16.1°、Δe -0.44 同時大幅變化）"],
    ["L2 統計層", "SSA/MAD 達數十萬量級，CUSUM 亦觸發"],
    ["L3（非Starlink）", "阻力殘差8,407km、Model2 z值84,076（數值失去定量意義）"],
], [("⚠ 誠實揭露：", 13, WARN, True),
    ("NRLMSIS模型為近圓軌道設計，QZS-7此時仍在GTO轉移段，數字真實但不可字面解讀為", 12.5, INK, False),
    ("「阻力異常8,407km」。規則層與統計層仍正確判定「異常」，但物理殘差的絕對數值在此情境下不具定量意義。", 12.5, INK, False)])

timeline_slide(100270, "QZS-7",
                "白色虛線＝本報告逐層解析選定事件；顏色依阻力殘差量級分級：藍低／黃中／紅高")
episode_table_slide(100270, "QZS-7", "drag")


sat_card("4.7 福衛七號一號星/COSMIC2-1 — 已知追蹤缺口衛星", "事件：2025-07-17 04:21Z，Δa=+7.97km", [
    ["L1 規則層", "P2/P4/P5/P6 四條觸發；另有106筆被P3正確抑制"],
    ["L2 統計層", "CUSUM/SSA/MAD 觸發，BOCPD 未觸發"],
    ["L3（非Starlink）", "阻力殘差8.02km → 判定機動；Model2 判為異常"],
    ["全歷史", "1,947筆中44筆合併判定；96%（1,875筆）被P1判為自然衰減"],
], "長期緩慢降軌衛星，少數真正機動訊號能在大量自然衰減雜訊中被正確篩出，無缺口干擾痕跡。")

timeline_slide(44349, "福衛七號一號星/COSMIC2-1",
                "白色虛線＝本報告逐層解析選定事件；顏色依阻力殘差量級分級：藍低／黃中／紅高")
episode_table_slide(44349, "福衛七號一號星/COSMIC2-1", "drag")


sat_card("4.8 YAOGAN-35 A", "事件：2025-03-21 12:38Z，Δa=+13.82km", [
    ["L1 規則層", "P2/P4/P5/P6 四條觸發 → 合併判定：機動候選"],
    ["L2 統計層", "四種方法全數觸發（含BOCPD，本9例中少數同步反應案例）"],
    ["L3（非Starlink）", "阻力殘差14.14km → 判定機動；Model2 判為異常"],
    ["全歷史", "3,045筆中60筆合併判定；Model2異常22次"],
], "BOCPD同步觸發代表此次機動的瞬間變點特徵比多數其他案例更明顯，四方法一致，信心度高。")

timeline_slide(49390, "YAOGAN-35 A",
                "白色虛線＝本報告逐層解析選定事件；顏色依阻力殘差量級分級：藍低／黃中／紅高")
episode_table_slide(49390, "YAOGAN-35 A", "drag")


sat_card("4.9 JASON 3", "事件：2016-02-04 19:09Z，IDS真值集成員，資料庫最早大型事件，Δa=+19.90km", [
    ["L1 規則層", "P2/P4/P5/P6 四條觸發 → 合併判定：機動候選"],
    ["L2 統計層", "四種方法全數觸發，SSA/MAD達7~20萬量級（本案例研究最極端之一）"],
    ["L3（非Starlink）", "阻力殘差19.90km → 判定機動；Model2 判為異常"],
    ["全歷史", "9,739筆中49筆合併判定；83%（8,110筆）被P1判為自然衰減"],
], "海洋測高任務軌道維持要求極高精度，機動次數少而每次都清楚可辨，訊噪比優於大量生產之Starlink星系。")

timeline_slide(41240, "JASON 3",
                "白色虛線＝本報告逐層解析選定事件；顏色依阻力殘差量級分級：藍低／黃中／紅高")
episode_table_slide(41240, "JASON 3", "drag")


# ══ 4.10–4.29　20 顆新增衛星（2026-10-07 擴充，通用卡片格式）══════════════════
with open(DOCS.parent / "data" / "benchmark" / "case_study_cards_20261007" / "cards.json", encoding="utf-8") as _f:
    _CARDS = _json.load(_f)

_NEW_ORDER = [58204, 43874, 41745, 30794, 45448, 69105, 43260, 43943, 66514, 36508,
              54754, 43476, 43477, 27421, 33105, 44351, 29047, 29601, 44819, 46460]

_STRAT_LABEL = {"P1_suppress": "P1", "P2": "P2", "P3_suppress": "P3", "P4": "P4",
                "P5": "P5", "P6": "P6", "other(di/de/dΩ)": "其他(Δi/Δe/ΔΩ)"}

for _i, _nid in enumerate(_NEW_ORDER):
    _rec = _CARDS.get(str(_nid))
    if not _rec or "event" not in _rec:
        continue
    _title = f"4.{10+_i} {_rec['name']}"
    _ev = _rec["event"]
    _bgnote = f"事件：{_ev['epoch'][:16]}Z，Δa={_ev['da_km']:+.2f}km（全歷史最大{'已判定' if _rec['combined_flag'] else '未判定'}轉移）"

    _fired = [_STRAT_LABEL[k] for k, v in _rec["per_strategy"].items() if v]
    _l1 = (("、".join(_fired) + " 觸發") if _fired else "P1–P6 皆未觸發") +           f" → 合併判定：{'機動候選' if _rec['combined_flag'] else '非機動候選'}"

    _l2d = _rec["l2"]
    _l2_fired = [k.upper() for k, v in _l2d.items() if v.get("event_at_idx")]
    _l2 = (("、".join(_l2_fired) + " 觸發") if _l2_fired else "四方法皆未於此刻觸發")

    _nr = _rec.get("nrlmsis", {})
    _m2 = _rec.get("model2", {})
    _l3 = (f"阻力殘差 {_nr.get('drag_resid_da', float('nan')):.2f}km"
           f"（{'> 0.30km 門檻，判定機動' if _nr.get('is_maneuver') else '未達 0.30km 門檻'}）"
           f"；Model2 全歷史異常 {_m2.get('n_total_anomaly', '—')} 次（共 {_m2.get('n_total', '—')} 筆）")

    _rows = [
        ["層級", "結果"],
        ["L1 規則層", _l1],
        ["L2 統計層", _l2],
        ["L3（非Starlink）", _l3],
        ["全歷史統計", f"{_rec['n_transitions']:,} 筆轉移中 {_rec['n_flagged']} 筆合併判定"],
    ]

    if _rec["combined_flag"] and _nr.get("is_maneuver"):
        _verdict = "規則層與物理殘差通道判定一致，為真實機動候選事件。"
    elif not _rec["combined_flag"]:
        _verdict = "此為全歷史最大 Δa 之轉移，但未達規則層合併判定門檻（可能為正常站位維持或資料雜訊）。"
    else:
        _verdict = "規則層判定為機動候選；與物理殘差通道判定略有出入，建議搭配統計層分數交叉確認。"

    sat_card(_title, _bgnote, _rows, _verdict)
    _kind = "fusion" if _rec["domain"] == "Starlink" else "drag"
    timeline_slide(_nid, _rec["name"],
                    "白色虛線＝本報告逐層解析選定事件；顏色依阻力殘差量級分級：藍低／黃中／紅高" if _kind == "drag" else
                    "白色虛線＝本報告逐層解析選定事件；顏色依融合評分器信心指數分級：藍低／黃中／紅高或已判定")
    episode_table_slide(_nid, _rec["name"], _kind)



s = slide(); _chip(s, "29 顆衛星的共同模式小結")
table(s, Inches(0.5), Inches(1.35), Inches(12.3), [
    ["觀察", "說明"],
    ["BOCPD 經常慢半拍", "多數案例中 BOCPD 於選定時刻分數仍偏低；擅長突然單步跳變，對漸進機動較不敏感"],
    ["融合評分器峰值常不同步", "多個 Starlink 案例顯示融合評分器整合窗口而非逐點反應，峰值常落在規則層判定時刻之外"],
    ["P1對低軌長歷史衛星貢獻大", "福衛七號96%/Jason-3 83%/太空站92%/福衛五號85%之轉移被P1正確判為自然衰減"],
    ["物理模型有設計邊界", "QZS-7轉移軌道案例：脫離近圓假設後數值失去定量意義，但方向性判斷仍正確"],
    ["GEO RPO 配對衛星可交叉驗證", "TJS-10/TJS-3、USA 271/SKYNET 5A 兩組配對樣本，可對照同一事件在雙方視角下之判定一致性"],
    ["新增樣本以 Model2+NRLMSIS 為主判", "20 顆新增樣本皆非 Starlink，路由邏輯與原 7 顆非 Starlink 樣本一致，驗證路由規則跨樣本穩定"],
], col_w=[Inches(3.2), Inches(9.1)], row_h=Inches(0.56), size=11.5)
foot()

# ══ 五、批次偵測 Starlink V3（2026-10-21 新增）══════════════════════════════
# 資料：docs/batch_detect_starlink_v3.py → data/benchmark/case_study_v3_20261021/overview.json、
#       docs/case_study_figs/v3_{altitude,raster}.png；MEME 比對：compare_v3_meme_tle.py 之輸出
import pandas as _pd

with open(DOCS.parent / "data" / "benchmark" / "case_study_v3_20261021" / "overview.json", encoding="utf-8") as _f:
    _V3 = {int(k): v for k, v in _json.load(_f).items()}


def _v3_segments(days):
    """連續（相隔 ≤1 天）之升軌日合併為一段。"""
    segs = []
    for d in sorted(_pd.to_datetime(days)):
        if segs and (d - segs[-1][-1]).days <= 1:
            segs[-1].append(d)
        else:
            segs.append([d])
    return segs


def _v3_covered(eps, seg):
    lo, hi = seg[0] - _pd.Timedelta(days=1), seg[-1] + _pd.Timedelta(days=1)
    return any(_pd.Timestamp(d0) <= hi and _pd.Timestamp(d1) >= lo for d0, d1, *_ in eps)


_v3_n_tle = sum(v["n_tle"] for v in _V3.values())
_v3_seg = {k: _v3_segments(v["raising_days"]) for k, v in _V3.items()}
_v3_nseg = sum(len(x) for x in _v3_seg.values())
_v3_l1 = sum(len(v["l1_episodes"]) for v in _V3.values())
_v3_l1_in = sum(v["l1_in_raise"] for v in _V3.values())
_v3_f = sum(len(v["fusion_episodes"]) for v in _V3.values())
_v3_f_in = sum(v["fusion_in_raise"] for v in _V3.values())
_v3_seg_l1 = sum(_v3_covered(_V3[k]["l1_episodes"], s) for k, ss in _v3_seg.items() for s in ss)
_v3_seg_f = sum(_v3_covered(_V3[k]["fusion_episodes"], s) for k, ss in _v3_seg.items() for s in ss)
_v3_sat_f = sum(1 for v in _V3.values() if v["fusion_episodes"])
_v3_last = max(v["last_epoch"] for v in _V3.values())[:16]


def _stat(slide_, x, y, w, big, label, color=ACCENT2):
    c = slide_.shapes.add_shape(1, x, y, w, Inches(1.15)); _fill(c, PANEL)
    _txt(slide_, x + Inches(0.15), y + Inches(0.05), w - Inches(0.3), Inches(0.62),
         [(big, 26, color, True)], anchor=MSO_ANCHOR.MIDDLE)
    _txt(slide_, x + Inches(0.15), y + Inches(0.66), w - Inches(0.3), Inches(0.42),
         [(label, 11.5, MUTE, False)])


divider("五、批次偵測：Starlink V3（Flight 14）26 顆",
        "同一套偵測流程，一次跑完一整批新入軌衛星——對照升軌期與 MEME 精密星曆")
foot()

s = slide(); _chip(s, "一次跑完 26 顆：入軌後三段升軌，同一流程逐星偵測", WARN)
_sw = Inches(2.95)
for _i, (_big, _lab, _col) in enumerate([
        ("26 顆", "Flight 14 同批發射", ACCENT2),
        (f"{_v3_n_tle:,} 筆", f"TLE，09-30 入軌至 {_v3_last[5:10]}", ACCENT2),
        (f"{_v3_nseg} 段", "升軌段（TLE 高度日增 > 1 km 之連續日）", GOOD),
        ("3 層", "偵測流程與前 30 顆完全相同", ACCENT)]):
    _stat(s, Inches(0.5) + (_sw + Inches(0.17)) * _i, Inches(1.15), _sw, _big, _lab, _col)
s.shapes.add_picture(str(FIGDIR / "v3_altitude.png"), Inches(1.4), Inches(2.5), width=Inches(10.5))
_txt(s, Inches(0.5), Inches(6.68), Inches(12.3), Inches(0.35),
     [("升軌分三段：270 → 約 296 → 約 316 → 約 345.7 km（TLE 平均高度）；主隊 23 顆已到位，彩色為 3 顆落後星", 10.5, MUTE, False)])
foot()

s = slide(); _chip(s, "逐星偵測事件 vs 升軌日：L1 與升軌期高度吻合，融合評分器只抓到少數", WARN)
s.shapes.add_picture(str(FIGDIR / "v3_raster.png"), Inches(0.35), Inches(1.1), width=Inches(12.6))
_txt(s, Inches(0.5), Inches(6.68), Inches(12.3), Inches(0.35),
     [("綠帶＝升軌日（由 TLE 高度推得之代理真值，非精密星曆）；黃＝L1 規則層事件；紅＝融合評分器事件；事件以相隔 48 小時內合併", 10.5, MUTE, False)])
foot()

_v3_rows = [["衛星", "NORAD", "TLE筆數", "目前高度(km)", "升軌段", "L1事件（升軌期內）", "融合事件（升軌期內）", "融合最高機率"]]
for _nid in sorted(_V3):
    _v = _V3[_nid]
    _v3_rows.append([_v["name"], str(_nid), str(_v["n_tle"]), f"{_v['alt_now']:.1f}", str(len(_v3_seg[_nid])),
                     f"{len(_v['l1_episodes'])}（{_v['l1_in_raise']}）",
                     f"{len(_v['fusion_episodes'])}（{_v['fusion_in_raise']}）",
                     f"{_v['fusion_max']:.3f}" if _v["fusion_max"] is not None else "—"])
for _chunk, _lab in [(_v3_rows[0:1] + _v3_rows[1:14], "之一"), (_v3_rows[0:1] + _v3_rows[14:], "之二")]:
    s = slide(); _chip(s, f"26 顆逐星偵測結果（{_lab}）", WARN)
    table(s, Inches(0.4), Inches(1.15), Inches(12.5), _chunk,
          col_w=[Inches(2.2), Inches(1.2), Inches(1.1), Inches(1.6), Inches(1.0), Inches(1.95), Inches(2.05), Inches(1.4)],
          row_h=Inches(0.39), size=10.5)
    _txt(s, Inches(0.5), Inches(6.68), Inches(12.3), Inches(0.35),
         [("「升軌期內」＝事件期間 ±1 天內有升軌日；路由主判全部為 Model 1（LightGBM）＋融合評分器（Starlink 路徑）", 10.5, MUTE, False)])
    foot()

s = slide(); _chip(s, "判讀：三層各自看到什麼", WARN)
_cw = Inches(3.95)
for _i, (_head, _big, _col, _lines) in enumerate([
        ("L1 規則層", f"{_v3_seg_l1}／{_v3_nseg}", GOOD,
         [f"升軌段被 L1 涵蓋；{_v3_l1} 次事件中 {_v3_l1_in} 次落在升軌期內。",
          "注意：升軌期本身是用 TLE 高度定義的，L1 偵測的也是 TLE 高度跳變——兩者看同一個訊號，吻合是預期，不是獨立驗證。",
          "真正的意義：先前「L1 對 V3 誤報率 43.6%」的旗標，確實都對應到真實升軌。"]),
        ("融合評分器", f"{_v3_seg_f}／{_v3_nseg}", WARN,
         [f"升軌段被涵蓋；只有 {_v3_sat_f}／26 顆出現事件（{_v3_f} 次，{_v3_f_in} 次在升軌期內）。",
          "它以一般 Starlink 的日常站位保持訓練；V3 剛入軌、在 30.5° 傾角大幅升軌，屬訓練分布之外。",
          "不能據此判定它準或不準，這不是它設計要處理的情境。"]),
        ("落後星", "2 顆", ACCENT2,
         ["100858、100870 仍停在約 315 km，沒有開始最後一段升軌。",
          "100865 已於 10 月中追上主隊（約 345.6 km）。",
          "100858 一直沒有排定升軌，可能延後、異常或預定退役，是後續最值得追蹤的一顆。"])]):
    _x = Inches(0.5) + (_cw + Inches(0.22)) * _i
    _c = s.shapes.add_shape(1, _x, Inches(1.2), _cw, Inches(5.0)); _fill(_c, PANEL)
    _txt(s, _x + Inches(0.2), Inches(1.3), _cw - Inches(0.4), Inches(0.5), [(_head, 16, INK, True)])
    _txt(s, _x + Inches(0.2), Inches(1.8), _cw - Inches(0.4), Inches(0.8), [(_big, 34, _col, True)])
    _txt(s, _x + Inches(0.2), Inches(2.75), _cw - Inches(0.4), Inches(3.6),
         [ln for t in _lines for ln in ([(t, 12.5, INK, False)], [("", 6, INK, False)])][:-1], sp=1.25)
foot()

# ── 進階：處理長時間持續升軌／軌道調整之下一步（建議，尚未實作）──────────────────
_RG = _pd.read_csv(DOCS.parent / "data" / "benchmark" / "orbit_regime_summary_20261021.csv").iloc[0]
_AP = _pd.read_csv(DOCS.parent / "data" / "benchmark" / "applicability_summary_20261021.csv").iloc[0]
s = slide(); _chip(s, "下一步：如何處理長時間持續升軌與軌道調整（步驟 1、2、4 已實作初版）", WARN)
_why = s.shapes.add_shape(1, Inches(0.5), Inches(1.15), Inches(12.3), Inches(1.05)); _fill(_why, PANEL2)
_txt(s, Inches(0.7), Inches(1.2), Inches(11.9), Inches(0.95), [
    [("為什麼現行融合評分器不適合：", 13, ACCENT2, True),
     ("它看前後 24 小時窗口內的「短暫跳變」，並以日常站位保持訓練。持續多日的連續推力，在每個窗口裡都只像緩慢趨勢；"
      "加上 V3 的 30.5° 傾角、350 km 以下高度不在訓練範圍內，模型只會輸出偏低的機率，卻不會說「我不適用」。", 12.5, INK, False)]],
    anchor=MSO_ANCHOR.MIDDLE, sp=1.2)
_steps = [
    ("1", "先判斷軌道狀態，再決定用哪個偵測器", "✔ 已實作初版", GOOD,
     "用 3 日高度斜率（> 1 km／天）把每天分成「升軌／維持／降軌」；升軌期以區段輸出，"
     f"融合評分器只用在維持期。對照 MEME 精密星曆一致率 {_RG.meme_agreement:.0%}。"),
    ("2", "偵測目標從「時間點」改成「區段」", "✔ 已實作初版", GOOD,
     "輸出升軌的起訖時間、總 Δa、平均速率與停留高度，而不是零散的旗標。"
     f"STARLINK-37471：{_RG.s37471_start[5:10]}～{_RG.s37471_end[5:10]}，{_RG.s37471_delta_km:+.1f} km。"),
    ("3", "補真值與特徵，學會持續推力", "中期・需重訓", ACCENT2,
     "真值：MEME 每份只取前 24 小時（升軌期預報超過 24 小時會失準）。特徵：B* 偏離（升軌時負 B* 達 58%）、"
     "多日 Δa 斜率、與同批衛星的高度差。驗證時按發射批次分組，並納入 Kuiper、千帆等新發射批次。"),
    ("4", "加入分布外偵測：不適用時要明說", "✔ 已實作初版", GOOD,
     f"超出訓練範圍時標示「不適用」並列出原因，不再輸出偏低的機率：V3 全部 {int(_AP.v3_tle):,} 筆皆判不適用。"
     "評估端：沒有真值的衛星與時段不再預設為「沒有機動」。"),
]
_bw, _bh = Inches(6.05), Inches(2.08)
for _i, (_n, _head, _tag, _col, _body) in enumerate(_steps):
    _x = Inches(0.5) + (_bw + Inches(0.2)) * (_i % 2)
    _y = Inches(2.4) + (_bh + Inches(0.17)) * (_i // 2)
    _b = s.shapes.add_shape(1, _x, _y, _bw, _bh); _fill(_b, PANEL)
    _txt(s, _x + Inches(0.18), _y + Inches(0.1), Inches(0.5), Inches(0.5), [(_n, 22, _col, True)])
    _txt(s, _x + Inches(0.65), _y + Inches(0.12), _bw - Inches(2.4), Inches(0.45), [(_head, 14, INK, True)])
    _txt(s, _x + _bw - Inches(1.75), _y + Inches(0.14), Inches(1.6), Inches(0.4), [(_tag, 11, _col, True)],
         align=PP_ALIGN.RIGHT)
    _txt(s, _x + Inches(0.65), _y + Inches(0.6), _bw - Inches(0.85), _bh - Inches(0.7), [(_body, 12, INK, False)], sp=1.2)
foot()

# ── 步驟 1、2 實作結果（orbit_regime.py；驗證 eval_orbit_regime.py）────────────────
s = slide(); _chip(s, "步驟 1、2 實作結果：狀態判別與升軌區段，三項驗證", GOOD)
_cols = [
    ("V3 × MEME 精密星曆", f"{int(_RG.meme_raising_hit)}／{int(_RG.meme_raising_truth)}", GOOD,
     [f"MEME 顯示正在升軌的時窗全部判對；{int(_RG.meme_windows_eval)} 個有 TLE 涵蓋的時窗，"
      f"整體一致率 {_RG.meme_agreement:.1%}。",
      f"高度持平的 {int(_RG.meme_flat_truth)} 個時窗中有 {int(_RG.meme_flat_false_raise)} 個被判為升軌，"
      "都是 10/3 在約 296 km 只停留 1–2 天，被 3 日斜率抹平。"]),
    ("已知案例 STARLINK-37471", f"{_RG.s37471_delta_km:+.1f} km", ACCENT2,
     [f"切出的升軌區段：{_RG.s37471_start[5:16]} → {_RG.s37471_end[5:16]}（UTC）。",
      "與第三節逐筆核對的時間線一致（06-14 爬升前、06-18 完成，淨變化 +46.7 km）。"]),
    ("一般 Starlink 近 30 天", f"{_RG.recent_raising_days / _RG.recent_sat_days:.2%}", ACCENT,
     [f"{int(_RG.recent_sats)} 顆、{int(_RG.recent_sat_days):,} 星日中，被判為升軌的星日比例（{int(_RG.recent_sats_raising)} 顆）。",
      f"降軌星日 {_RG.recent_lowering_days / _RG.recent_sat_days:.1%}（{int(_RG.recent_sats_lowering)} 顆），"
      "多為真實調整：退役離軌、殼層整體下降、整批約 2 km 的微調；未逐一以精密星曆驗證，視為上限。"]),
]
_cw = Inches(3.95)
for _i, (_head, _big, _col, _lines) in enumerate(_cols):
    _x = Inches(0.5) + (_cw + Inches(0.22)) * _i
    _c = s.shapes.add_shape(1, _x, Inches(1.2), _cw, Inches(4.55)); _fill(_c, PANEL)
    _txt(s, _x + Inches(0.2), Inches(1.3), _cw - Inches(0.4), Inches(0.5), [(_head, 15, INK, True)])
    _txt(s, _x + Inches(0.2), Inches(1.8), _cw - Inches(0.4), Inches(0.8), [(_big, 32, _col, True)])
    _txt(s, _x + Inches(0.2), Inches(2.75), _cw - Inches(0.4), Inches(2.9),
         [ln for t in _lines for ln in ([(t, 12.5, INK, False)], [("", 6, INK, False)])][:-1], sp=1.25)
_txt(s, Inches(0.5), Inches(5.95), Inches(12.3), Inches(0.7), [
    [("限制：", 12, WARN, True),
     ("狀態以 TLE 逐日判定，時間解析度約 1 天；中途停留 ≥2 天的升軌可分開，1–2 天的短暫停留仍會併段。"
      f"V3 26 顆共切出 {int(_RG.v3_segments)} 段升軌區段。程式：orbit_regime.py；驗證：eval_orbit_regime.py。", 12, MUTE, False)]], sp=1.2)
foot()

# ── 步驟 4 實作結果（applicability.py、satdet.truth_coverage；驗證 eval_applicability.py、three_layer_common_eval.py）──
_BM = DOCS.parent / "data" / "benchmark"
_ar_new = _pd.read_csv(_BM / "three_layer_common_eval_20261021.csv").set_index("method")
_ar_old = _pd.read_csv(_BM / "three_layer_common_eval_20261021_legacyquiet.csv").set_index("method")
_un_new = _pd.read_csv(_BM / "three_layer_perunit_20261021.csv")
_un_old = _pd.read_csv(_BM / "three_layer_perunit_20261021_legacyquiet.csv")
s = slide(); _chip(s, "步驟 4 實作結果：不適用要明說，沒有真值不等於安靜", GOOD)
_c = s.shapes.add_shape(1, Inches(0.5), Inches(1.15), Inches(5.0), Inches(4.6)); _fill(_c, PANEL)
_txt(s, Inches(0.7), Inches(1.25), Inches(4.6), Inches(0.45), [("模型端：適用範圍判定", 15, INK, True)])
_txt(s, Inches(0.7), Inches(1.7), Inches(4.6), Inches(0.7), [(f"{_AP.v3_ood_frac:.0%}", 32, GOOD, True)])
_txt(s, Inches(0.7), Inches(2.45), Inches(4.6), Inches(4.0), [
    [(f"V3 {int(_AP.v3_sats)} 顆、{int(_AP.v3_tle):,} 筆全部判為不適用，原因都列出傾角 30.5° 不屬訓練族群；機率改為 NaN，不再顯示一個看似正常的數值。", 12.5, INK, False)],
    [("", 6, INK, False)],
    [(f"一般 Starlink {int(_AP.sl_sats)} 顆近 30 天：{_AP.sl_applicable_frac:.1%} 適用、"
      f"{_AP.sl_regime_frac:.1%} 改由狀態層處理（升降軌）、{_AP.sl_ood_frac:.1%} 不適用。", 12.5, INK, False)],
    [("", 6, INK, False)],
    [(f"不適用的 {int(_AP.sl_ood_sats)} 顆原因全是高度：退役離軌已降到訓練範圍下限 324 km 以下，判為不適用正確。", 12.5, INK, False)],
], sp=1.25)
_rows = [["", "舊：沒有真值也當安靜", "新：只在真值涵蓋期間"],
         ["納入衛星", f"{_un_old.norad_id.nunique()} 顆", f"{_un_new.norad_id.nunique()} 顆"],
         ["安靜負樣本", f"{int((_un_old.label == 0).sum()):,}", f"{int((_un_new.label == 0).sum()):,}"],
         ["L1 誤報率", f"{_ar_old.loc['L1 規則 P1–P6', 'fpr']:.3f}", f"{_ar_new.loc['L1 規則 P1–P6', 'fpr']:.3f}"],
         ["L2 最佳單通道 AUC", f"{_ar_old.loc['L2 cusum（單通道）', 'auc']:.3f}", f"{_ar_new.loc['L2 cusum（單通道）', 'auc']:.3f}"],
         ["L3 融合評分器 AUC", f"{_ar_old.loc['L3 融合評分器 OOF', 'auc']:.3f}", f"{_ar_new.loc['L3 融合評分器 OOF', 'auc']:.3f}"]]
_txt(s, Inches(5.8), Inches(1.2), Inches(7.0), Inches(0.45), [("評估端：三層同一擂台，修正前後（同日資料庫）", 15, INK, True)])
table(s, Inches(5.8), Inches(1.7), Inches(7.0), _rows,
      col_w=[Inches(2.2), Inches(2.4), Inches(2.4)], row_h=Inches(0.44), size=12)
_txt(s, Inches(5.8), Inches(4.5), Inches(7.0), Inches(2.0), [
    [(f"排除 {_un_old.norad_id.nunique() - _un_new.norad_id.nunique()} 顆沒有真值的衛星（V3 26 顆等），"
      "並刪掉真值涵蓋期以外的「安靜」時段——MEME 真值只到 09-17，之後的 TLE 原本全被當成安靜。", 12, INK, False)],
    [("", 5, INK, False)],
    [("L3 AUC 反而下降：被刪掉的多是容易判對的平靜時段，舊數字因此偏高；新數字才有真值支撐。"
      "精確率會隨正負樣本比例變動，不宜跨版本比較。", 12, WARN, False)],
], sp=1.2)
foot()

_mp = DOCS.parent / "data" / "benchmark" / "v3_meme_vs_tle_samples_20261020.parquet"
if _mp.exists():
    _m = _pd.read_parquet(_mp)
    _m["fd"] = _m.file.str[:10]
    _m["h"] = (_m.t - _m.groupby("file").t.transform("min")).dt.total_seconds() / 3600
    _fresh = _m[(_m.tle_age_h <= 12) & (_m.fd != "2026-10-20")]
    _near = _fresh[_fresh.h <= 12]
    _bins = [(0, 24, "0–24 小時"), (24, 48, "24–48 小時"), (48, 72, "48–72 小時")]
    _rows = [["MEME 預報時距", "中位數（km）", "90 百分位（km）"]]
    for _lo, _hi, _lab in _bins:
        _g = _fresh[(_fresh.h > _lo) & (_fresh.h <= _hi)].pos_err_km
        _rows.append([_lab, f"{_g.median():.2f}", f"{_g.quantile(0.9):.1f}"])
    s = slide(); _chip(s, "TLE 品質：與 SpaceX MEME 精密星曆直接比對", WARN)
    table(s, Inches(0.5), Inches(1.3), Inches(6.3), _rows,
          col_w=[Inches(2.1), Inches(2.1), Inches(2.1)], row_h=Inches(0.5), size=12.5)
    bullets(s, Inches(7.1), Inches(1.25), Inches(5.8), [
        (ACCENT2, [("新鮮 TLE 約 1 公里等級", 15, INK, True)]),
        (MUTE, [(f"MEME 前 12 小時、TLE 不超過 12 小時：位置差中位數 {_near.pos_err_km.median():.2f} km"
                 f"（沿軌 {_near.dr_t_km.abs().median():.2f}、徑向 {_near.dr_r_km.abs().median():.2f}、"
                 f"越軌 {_near.dr_n_km.abs().median():.2f} km）。", 13, INK, False)]),
        (ACCENT2, [("升軌期間，MEME 預報超過約 24 小時就會失準", 15, INK, True)]),
        (MUTE, [("SpaceX 的燃燒計畫一直在變，預報裡排的機動和實際執行的不同。做 V3 真值時，每份 MEME 只能用前約 24 小時。", 13, INK, False)]),
        (ACCENT2, [("高度定義差 4 km，不是誤差", 15, INK, True)]),
        (MUTE, [("MEME 一圈平均高度固定比 TLE 平均半長軸高度高約 4.0 km（兩種平均方式不同）。", 13, INK, False)]),
    ], size=13, gap=1.2)
    _txt(s, Inches(0.5), Inches(6.68), Inches(12.3), Inches(0.35),
         [("資料：compare_v3_meme_tle.py；10-03、10-06 兩份 MEME（每份 72 小時、每分鐘一筆），每 5 分鐘取一點、以當時最新 TLE 經 SGP4 推算比對", 10.5, MUTE, False)])
    foot()

# ══ 六、結語 ══════════════════════════════════════════════════════════════
s = slide()
band = s.shapes.add_shape(1, 0, Inches(2.4), W, Inches(2.5)); _fill(band, PANEL)
_txt(s, Inches(0.9), Inches(2.65), Inches(11.6), Inches(0.9), [("三十個案例，同一套邏輯", 30, INK, True)])
_txt(s, Inches(0.9), Inches(3.7), Inches(11.6), Inches(0.7),
     [("規則層、統計層、機器學習層（逐窗口與融合評分器）分別獨立判斷，橫跨30顆衛星結果一致收斂", 16, ACCENT, False)])
_txt(s, Inches(0.9), Inches(5.0), Inches(11.6), Inches(1.95),
     [[("・STARLINK-37471 深入案例：06-15~06-18 完成+46.7~50.3公里真實爬升，四角度一致佐證", 13.5, INK, False)],
      [("・其餘29顆衛星（含指定的福衛五號/八號/太空站、9顆原有對照樣本＋20顆新增樣本）比照解析", 13.5, GOOD, True)],
      [("・新增樣本涵蓋GEO RPO配對、OneWeb/千帆/高分/吉林星系、IDS真值集、GPS導航衛星等", 13.5, INK, False)],
      [(f"・同一流程批次跑完 Starlink V3 26 顆：L1 涵蓋 {_v3_seg_l1}／{_v3_nseg} 升軌段，融合評分器僅 {_v3_seg_f}／{_v3_nseg}（分布外情境）", 13.5, WARN, True)],
      [("・包含一次「系統正確判斷沒事」的對照案例（STARLINK-30805）與一次物理模型邊界案例（QZS-7）", 13.5, INK, False)],
      [("・過程中發現並誠實更正一處日期誤解，對照 MEME 真值取樣點與 TLE 實際軌跡後確認正確時間", 13, MUTE, False)]], sp=1.25)
foot()

out = DOCS / "案例研究_30顆衛星偵測總覽與單星逐層解析_20261021.pptx"
prs.save(str(out))
print(f"saved {out}  ({out.stat().st_size//1024} KB, {len(prs.slides._sldIdLst)} slides)")
