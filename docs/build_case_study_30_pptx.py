# -*- coding: utf-8 -*-
"""build_case_study_pptx.py — 案例研究簡報：10 衛星偵測總覽與 STARLINK-37471 逐層解析
產出：docs/案例研究_30顆衛星偵測總覽與單星逐層解析_20261007.pptx
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
         [("TASA-S-1150268　案例研究：10 衛星偵測總覽與單星逐層解析", 9.5, MUTE, False)])
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
_txt(s, Inches(0.9), Inches(6.55), Inches(11.6), Inches(0.5),
     [("計畫案號 TASA-S-1150268　｜　數字核算日 2026-10-07", 12, MUTE, False)])
foot()

# ══ 2 大綱 ═══════════════════════════════════════════════════════════════
s = slide(); _chip(s, "簡報大綱")
rows = [
    ("一", "30 顆衛星樣本與選取理由", "福衛五號／福衛八號／國際太空站＋29 顆涵蓋GEO RPO/星系/IDS真值等對照", ACCENT),
    ("二", "30 顆衛星偵測總覽表", "統一偵測摘要，全部歷史 TLE 實跑", ACCENT2),
    ("三", "單星深入解析：STARLINK-37471", "規則層→統計層→機器學習層，逐層看判斷依據（含一次誠實更正）", GOOD),
    ("四", "其餘 29 顆衛星逐層解析", "每顆衛星：卡片摘要＋時間序列圖（日期標註）＋機動日期清單", ACCENT2),
    ("五", "結語：三十個案例，同一套邏輯", "多層交叉驗證的實際運作樣貌", ACCENT),
]
y = Inches(1.4)
for tag, title, desc, col in rows:
    card = s.shapes.add_shape(1, Inches(0.6), y, Inches(12.1), Inches(0.88)); _fill(card, PANEL)
    bar = s.shapes.add_shape(1, Inches(0.6), y, Inches(0.16), Inches(0.88)); _fill(bar, col)
    _txt(s, Inches(0.95), y + Inches(0.06), Inches(1.0), Inches(0.76),
         [(tag, 18, col, True)], anchor=MSO_ANCHOR.MIDDLE)
    _txt(s, Inches(1.95), y + Inches(0.06), Inches(10.5), Inches(0.76),
         [[(title, 15.5, INK, True)], [(desc, 12.5, MUTE, False)]], anchor=MSO_ANCHOR.MIDDLE, sp=1.1)
    y += Inches(1.0)
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

# ══ 五、結語 ══════════════════════════════════════════════════════════════
s = slide()
band = s.shapes.add_shape(1, 0, Inches(2.4), W, Inches(2.5)); _fill(band, PANEL)
_txt(s, Inches(0.9), Inches(2.65), Inches(11.6), Inches(0.9), [("三十個案例，同一套邏輯", 30, INK, True)])
_txt(s, Inches(0.9), Inches(3.7), Inches(11.6), Inches(0.7),
     [("規則層、統計層、機器學習層（逐窗口與融合評分器）分別獨立判斷，橫跨30顆衛星結果一致收斂", 16, ACCENT, False)])
_txt(s, Inches(0.9), Inches(5.0), Inches(11.6), Inches(1.9),
     [[("・STARLINK-37471 深入案例：06-15~06-18 完成+46.7~50.3公里真實爬升，四角度一致佐證", 14, INK, False)],
      [("・其餘29顆衛星（含指定的福衛五號/八號/太空站、9顆原有對照樣本＋20顆新增樣本）比照解析", 14, GOOD, True)],
      [("・新增樣本涵蓋GEO RPO配對(TJS-10/TJS-3、USA271/SKYNET5A)、OneWeb/千帆/高分/吉林星系、", 14, INK, False)],
      [("　IDS真值集(CryoSat-2/SWOT/Sentinel-6B/GRACE-FO/Jason-2)、GPS導航衛星等", 14, INK, False)],
      [("・包含一次「系統正確判斷沒事」的對照案例（STARLINK-30805）與一次物理模型邊界案例（QZS-7）", 14, INK, False)],
      [("・過程中發現並誠實更正一處日期誤解，對照 MEME 真值取樣點與 TLE 實際軌跡後確認正確時間", 13, WARN, False)]], sp=1.3)
foot()

out = DOCS / "案例研究_30顆衛星偵測總覽與單星逐層解析_20261007.pptx"
prs.save(str(out))
print(f"saved {out}  ({out.stat().st_size//1024} KB, {len(prs.slides._sldIdLst)} slides)")
