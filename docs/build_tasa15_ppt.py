#!/usr/bin/env python3
"""build_tasa15_ppt.py — TASA 指定 15 顆衛星機動偵測結果簡報（期末報告交付項目）。

版型仿 TASA 系統工程處「TASA方法於NASA機動資料庫偵測結果_20260731」：16:9（13.33″×7.5″）、
深藍 #002B8A 標題（Calibri 粗體）、♦ 條列（微軟正黑體）、深藍表頭表格、右上 TASA logo、右下頁碼。
版型素材（docs/tasa_template/）由該 PDF 取出：封面／結尾背景（已去字）與內頁 logo。

資料：r15.json ＝ maneuver_report_builder.build_report_data() 對 15 顆衛星之輸出
（報表版本 R7，2026-11-15；本機總庫 TLE 至 2026-11-14；含 NRLMSIS 阻力殘差通道）。
用法：python docs/build_tasa15_ppt.py <r15.json>
輸出：docs/期末_TASA15星機動偵測_R7_20261115.pptx、fig_tasa15_timeline_r7.png（PDF 由 docs/export_pptx_pdf.py 匯出）
R6 版（2026-11-13）之簡報保留為 期末_TASA15星機動偵測_20261113.pptx。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

DOCS = Path(__file__).resolve().parent
TPL = DOCS / "tasa_template"
OUT = DOCS / "期末_TASA15星機動偵測_R7_20261115.pptx"
FIG = DOCS / "fig_tasa15_timeline_r7.png"
FIG_DET = DOCS / "fig_tasa15_detect_vs_alt_r7.png"
DATA_END = "2026-11-14"

NAVY = RGBColor(0x00, 0x2B, 0x8A)
BLUE = RGBColor(0x12, 0x6B, 0xFA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLACK = RGBColor(0x00, 0x00, 0x00)
GRAY_ROW = RGBColor(0xE9, 0xEB, 0xF0)
GRAY_ROW2 = RGBColor(0xF6, 0xF7, 0xF9)
MUTED = RGBColor(0x59, 0x59, 0x59)
CJK = "Microsoft JhengHei"
LAT = "Calibri"

# ── 分類（依偵測到的行為型態）────────────────────────────────────────────────
TYPES = [
    ("A", "軌道轉移型", [64199, 62190, 58651]),
    ("B", "星系營運型", [53056, 59711]),
    ("C", "小幅調整型", [69018, 60548]),
    ("D", "無超過下限事件", [68831, 61871, 43081, 43797, 56193, 60507, 65316, 41634]),
]
COUNTRY = {"United States (US)": "US", "People's Republic of China (PRC)": "PRC"}
APP_URL = "https://rhynowu-maneuver-detection-i18n.hf.space"


def f2_url(n, r) -> str:
    """線上儀表板深連結：開啟工具頁並自動產出 F2 技術完整版（app 2026-10-30 起支援 &report=）。"""
    return f"{APP_URL}/?mode=tool&norad={n}&d0={r['start_date']}&d1={r['end_date']}&report=F2&lang=zh"
ORBIT = {"SSO": "SSO", "mid-inc": "中傾角", "53deg": "53°", "other": "其他"}
NAME_NOTE = {69018: "PELICAN-8 300F*"}
GRADE_LABEL = lambda e: e["grade"] + ("（ML 輔助）" if e.get("ml_capped") else "")


def load(path: str) -> dict[int, dict]:
    return {int(k): v for k, v in json.loads(Path(path).read_text(encoding="utf-8")).items()}


def country(r) -> str:
    f = ((r.get("sat_info") or {}).get("sources", {}).get("N2YO", {}) or {}).get("fields", {})
    return COUNTRY.get(f.get("來源國", ""), f.get("來源國", "?"))


def disp(n, r) -> str:
    return NAME_NOTE.get(n, r["name"])


# ── 圖：15 顆衛星事件時間軸（泳道）────────────────────────────────────────────
GRADE_COLOR = {"E3": "#002B8A", "E2": "#3F7BE0", "E1": "#A9C3F0"}


def build_timeline(R: dict[int, dict]) -> None:
    plt.rcParams["font.family"] = [CJK, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, ax = plt.subplots(figsize=(12.4, 5.75), dpi=200)
    rows, y, yt, ylab = [], 0, [], []
    group_y = []
    for code, tname, ids in TYPES:
        y0 = y
        for n in ids:
            rows.append((n, y)); yt.append(y); ylab.append(disp(n, R[n])); y += 1
        group_y.append((code, tname, y0, y - 1))
        y += 0.6
    x0, x1 = pd.Timestamp("2023-12-01"), pd.Timestamp("2026-12-10")
    ytr = ax.get_yaxis_transform()  # x：軸座標比例、y：資料座標 → 類型標籤放在衛星名稱左側
    for i, (code, tname, a, b) in enumerate(group_y):
        if i % 2 == 0:
            ax.axhspan(a - 0.5, b + 0.5, color="#F2F4F8", zorder=0, lw=0)
        ax.text(-0.175, (a + b) / 2, f"{code}\n{tname}", transform=ytr, ha="center", va="center",
                fontsize=11, color="#002B8A", fontweight="bold", linespacing=1.3, clip_on=False)
    for n, yy in rows:
        r = R[n]
        s, e = pd.Timestamp(r["start_date"]), pd.Timestamp(r["end_date"])
        ax.plot([s, e], [yy, yy], color="#C9CED8", lw=5, solid_capstyle="round", zorder=1)
        for sg in r.get("segments") or []:
            ax.plot([pd.Timestamp(sg["t_start"]).tz_localize(None), pd.Timestamp(sg["t_end"]).tz_localize(None)],
                    [yy, yy], color=GRADE_COLOR.get(sg.get("grade"), "#002B8A"), lw=7, solid_capstyle="round", zorder=2)
        for ev in r.get("events") or []:
            t = pd.Timestamp(ev["t_start"]).tz_localize(None)
            size = 28 + 26 * np.log1p(abs(ev["net_da"]))
            if ev["grade"] == "D":
                ax.scatter(t, yy, s=size, facecolor="white", edgecolor="#7F7F7F", lw=1.6, zorder=4)
            else:
                ax.scatter(t, yy, s=size, color=GRADE_COLOR[ev["grade"]], edgecolor="white", lw=1.2, zorder=4)
    ymap = dict(rows)
    notes = [  # (norad, 時間, 文字, dx 天, dy, ha)：dy<0 標在該列上方、dy>0 標在該列與下一列之間
        (64199, "2025-05-29", "−38.7 km", 0, -0.30, "center"),
        (64199, "2026-11-09", "+9.8 km（11/09）", -12, -0.30, "right"),
        (58651, "2024-03-15", "+39.8 km", 0, -0.30, "center"),
        (62190, "2025-04-25", "三件累計 +25.1 km", 0, 0.42, "left"),
        (53056, "2026-07-20", "26 天連續降軌 −83.8 km", 0, -0.30, "center"),
        (69018, "2026-10-19", "−1.6 km", -10, -0.30, "right"),
        (68831, "2026-06-01", "D：回跳型態（資料品質）", 0, 0, "right"),
    ]
    for n, t, txt, dx, dy, ha in notes:
        ax.text(pd.Timestamp(t) + pd.Timedelta(days=dx), ymap[n] + dy, txt, fontsize=9.5, color="#262626",
                ha=ha, va="bottom" if dy < 0 else "center", zorder=5)
    test = pd.Timestamp("2026-10-30")
    ax.axvline(test, color="#C00000", lw=1.2, ls=(0, (4, 3)), zorder=3)
    ax.text(test + pd.Timedelta(days=6), -0.95, "10/30 交付任務，測試15衛星", color="#C00000", fontsize=9.5,
            ha="right", va="bottom")
    ax.set_yticks(yt, ylab, fontsize=10)
    ax.set_ylim(y - 0.6 + 0.1, -1.0)
    ax.set_xlim(x0, x1)
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.tick_params(axis="x", labelsize=9.5, colors="#404040")
    ax.tick_params(axis="y", length=0)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#BFBFBF")
    ax.grid(axis="x", color="#E3E6EC", lw=0.8, zorder=0)
    leg = [Line2D([], [], color="#C9CED8", lw=5, label="TLE 觀測期間")]
    leg += [Line2D([], [], marker="o", ls="", markersize=9, markerfacecolor=c, markeredgecolor="white", label=g)
            for g, c in GRADE_COLOR.items()]
    leg += [Line2D([], [], marker="o", ls="", markersize=9, markerfacecolor="white", markeredgecolor="#7F7F7F", label="D"),
            Line2D([], [], color="#002B8A", lw=7, label="連續機動段")]
    ax.legend(handles=leg, loc="lower left", bbox_to_anchor=(0.0, 1.0), ncol=6, frameon=False, fontsize=10,
              handletextpad=0.4, columnspacing=1.4)
    ax.text(0.0, -0.075, "圓點顏色＝證據等級、大小∝|淨 Δa|", transform=ax.transAxes, ha="left", va="top",
            fontsize=9.5, color="#595959")
    fig.subplots_adjust(left=0.225, right=0.985, top=0.93, bottom=0.095)
    fig.savefig(FIG, dpi=200)
    plt.close(fig)


# ── PPTX 共用元件 ─────────────────────────────────────────────────────────────
def _font(run, size, bold=False, color=BLACK, latin=LAT, cjk=CJK):
    f = run.font
    f.size, f.bold, f.color.rgb, f.name = Pt(size), bold, color, latin
    rPr = run._r.get_or_add_rPr()
    ea = rPr.find(qn("a:ea"))
    if ea is None:
        ea = rPr.makeelement(qn("a:ea"), {})
        rPr.append(ea)
    ea.set("typeface", cjk)


def text(slide, x, y, w, h, runs_or_str, size=18, bold=False, color=BLACK, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, latin=LAT):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = runs_or_str if isinstance(runs_or_str, list) else [runs_or_str]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        segs = para if isinstance(para, list) else [(para, {})]
        for seg in segs:
            s, o = (seg, {}) if isinstance(seg, str) else seg
            r = p.add_run()
            r.text = s
            _font(r, o.get("size", size), o.get("bold", bold), o.get("color", color), o.get("latin", latin))
        p.space_after = Pt(o.get("after", 0)) if segs else Pt(0)
    return tb


def bullets(slide, x, y, w, h, items, size=20, after=6):
    """♦ 條列（Wingdings u+F074，深藍），仿參考檔。items: str 或 [(文字, opts), ...]。"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    for i, it in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        pPr = p._p.get_or_add_pPr()
        pPr.set("marL", str(Emu(Inches(0.28)))); pPr.set("indent", str(-Emu(Inches(0.28))))
        for tag, attrs in (("a:buClr", None), ("a:buSzPct", {"val": "100000"}),
                           ("a:buFont", {"typeface": "Wingdings", "pitchFamily": "2", "charset": "2"}),
                           ("a:buChar", {"char": ""})):
            el = pPr.makeelement(qn(tag), attrs or {})
            if tag == "a:buClr":
                c = el.makeelement(qn("a:srgbClr"), {"val": "002B8A"}); el.append(c)
            pPr.append(el)
        p.space_after = Pt(after)
        segs = it if isinstance(it, list) else [(it, {})]
        for s, o in segs:
            r = p.add_run(); r.text = s
            _font(r, o.get("size", size), o.get("bold", False), o.get("color", BLACK))
    return tb


def frame(prs, title: str, page: int):
    """內頁框架：上緣深藍細線、左上標題、右上 TASA logo、右下頁碼。"""
    s = prs.slides.add_slide(prs.slide_layouts[6])
    ln = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(0.764), Inches(0.444), Inches(12.57), Inches(0.444))
    ln.line.color.rgb, ln.line.width = NAVY, Pt(1)
    text(s, 0.764, 0.56, 10.5, 0.5, title, size=24, bold=True, color=NAVY)
    s.shapes.add_picture(str(TPL / "logo_header.png"), Inches(11.70), Inches(0.60), width=Inches(0.87))
    page = len(prs.slides._sldIdLst)
    text(s, 12.30, 7.10, 0.3, 0.2, str(page), size=10, color=NAVY, align=PP_ALIGN.RIGHT)
    return s


def table(slide, x, y, w, col_w, rows, header, size=14, row_h=0.42, head_h=0.46, align=None, bold_cols=()):
    t = slide.shapes.add_table(len(rows) + 1, len(header), Inches(x), Inches(y), Inches(w),
                               Inches(head_h + row_h * len(rows))).table
    tblPr = t._tbl.tblPr
    for k in ("bandRow", "firstRow"):
        tblPr.set(k, "0")
    style = tblPr.find(qn("a:tableStyleId"))
    if style is not None:
        style.text = "{5940675A-B579-460E-94D1-54222C63F5DA}"  # No Style, Table Grid → 自行上色
    for j, cw in enumerate(col_w):
        t.columns[j].width = Inches(cw)
    t.rows[0].height = Inches(head_h)
    for i in range(1, len(rows) + 1):
        t.rows[i].height = Inches(row_h)
    align = align or [PP_ALIGN.CENTER] * len(header)

    def fill(cell, txt, bg, fg, b, al, sz):
        cell.fill.solid(); cell.fill.fore_color.rgb = bg
        cell.margin_left = cell.margin_right = Inches(0.06)
        cell.margin_top = cell.margin_bottom = Inches(0.03)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cell.text_frame; tf.word_wrap = True
        lines = txt if isinstance(txt, list) else [txt]
        for k, line in enumerate(lines):
            p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
            p.alignment = al
            segs = line if isinstance(line, list) else [(line, {})]
            for s_, o in segs:
                r = p.add_run(); r.text = s_
                _font(r, o.get("size", sz), o.get("bold", b), o.get("color", fg))
                if o.get("link"):
                    r.hyperlink.address = o["link"]
                    r.font.color.rgb = o.get("color", BLUE); r.font.underline = True
        # 白色細格線（OOXML 規定 lnL/lnR/lnT/lnB 須排在儲存格填色之前）
        tcPr = cell._tc.get_or_add_tcPr()
        for k, edge in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):
            lnx = tcPr.makeelement(qn(edge), {"w": "12700"})
            sf = lnx.makeelement(qn("a:solidFill"), {}); c = sf.makeelement(qn("a:srgbClr"), {"val": "FFFFFF"})
            sf.append(c); lnx.append(sf); tcPr.insert(k, lnx)

    for j, h in enumerate(header):
        fill(t.cell(0, j), h, NAVY, WHITE, True, PP_ALIGN.CENTER, size)
    for i, row in enumerate(rows, start=1):
        bg = GRAY_ROW if i % 2 == 1 else GRAY_ROW2
        for j, v in enumerate(row):
            fill(t.cell(i, j), v, bg, BLACK, j in bold_cols, align[j], size)
    return t


def flow(slide, x, y, w, h, steps, gap=0.42):
    """橫向流程方塊：steps＝[(標題, 內文, 是否 AI)]；AI 步驟用藍框標示。"""
    bw = (w - gap * (len(steps) - 1)) / len(steps)
    for i, (head, body, ai) in enumerate(steps):
        bx = x + i * (bw + gap)
        b = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(bx), Inches(y), Inches(bw), Inches(h))
        b.fill.solid(); b.fill.fore_color.rgb = GRAY_ROW2
        b.line.color.rgb = BLUE if ai else RGBColor(0xD5, 0xDA, 0xE3); b.line.width = Pt(2 if ai else 0.75)
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(bx), Inches(y), Inches(bw), Inches(0.5))
        bar.fill.solid(); bar.fill.fore_color.rgb = NAVY; bar.line.fill.background()
        text(slide, bx + 0.1, y, bw - 0.2, 0.5, head, size=15, bold=True, color=WHITE,
             align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        text(slide, bx + 0.15, y + 0.62, bw - 0.3, h - 0.7, body, size=13, color=BLACK)
        if i < len(steps) - 1:
            a = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(bx + bw + 0.07), Inches(y + h / 2 - 0.16),
                                       Inches(gap - 0.14), Inches(0.32))
            a.fill.solid(); a.fill.fore_color.rgb = BLUE; a.line.fill.background()


def build_qa(prs, R: dict[int, dict], l1: int, g: dict) -> None:
    """第 8–13 頁：TASA 2026-11 提問說明（對應 docs/TASA回覆_15星報告與10月案例QA_20261113.md）。"""
    H = {"bold": True, "color": NAVY}
    star = lambda r: r["name"].upper().startswith("STARLINK")
    n_lc = sum(len(r.get("low_conf") or []) for r in R.values())
    n_case = sum(len({x.get("case") for x in r.get("low_conf") or []}) for r in R.values())
    n_ml = sum("ml" in e["evidence"] for r in R.values() for e in r["events"])
    n_cap = sum(bool(e.get("ml_capped")) for r in R.values() for e in r["events"])
    n_ev = sum(len(r["events"]) for r in R.values())
    n_none = sum(1 for r in R.values() if not r["events"])

    # 8 名詞說明（Q1–Q3）
    s = frame(prs, "TASA 提問說明 ① 候選點、候選事件與證據等級", 8)
    flow(s, 0.78, 1.12, 11.8, 1.55, [
        (f"規則候選點　{l1} 個", "L1 規則（P1–P6）逐筆檢查相鄰兩筆 TLE 的半長軸變化，超過門檻即標一點", False),
        (f"候選事件　{n_ev} 件", "相隔 48 小時內的候選點連鎖合併；一次機動常留下多個點，合併後才是一件事件", False),
        ("證據等級", f"依顯著性與輔助通道數排定複核優先序：E3 {g['E3']}／E2 {g['E2']}（ML 輔助 {n_cap}）／E1 {g['E1']}／D {g['D']}", False),
    ])
    bullets(s, 0.86, 2.92, 4.3, 3.6, [
        [("候選事件＝值得人工複核的軌道變化，", H), ("不等於已確認的機動；與「候選機動事件」同義。", {})],
        [("為何不直接稱「機動」：", H), ("公開 TLE 無推進紀錄，同樣的變化也可能來自定軌更新或編目交叉標記。", {})],
        [("等級是複核優先序，", H), ("不是機動發生機率。", {})],
    ], size=15, after=10)
    table(s, 5.45, 2.92, 7.15, [0.62, 1.25, 3.68, 1.6], [
        ["E3", "高優先複核", "顯著性高，且：屬連續機動段、或 |淨 Δa| ≥ 10 km、或 ≥3 類輔助通道一致並含 AI 通道（AI 條件限 Starlink）", "立即複核；確認後再評估碰撞風險"],
        ["E2", "人工複核", "顯著性中以上，且 ≥2 類輔助通道一致，未達 E3；非 Starlink 僅因 AI 通道達 E3 條件者列「E2（ML 輔助）」", "排程人工複核；ML 輔助者優先"],
        ["E1", "待觀察", "顯著性低、量級近 TLE 雜訊，或輔助通道不足", "持續觀察"],
        ["D", "資料品質待查", "「升了又降回」回跳型態，可能為 TLE 擬合異常或編目交叉", "先核對原始 TLE"],
    ], ["等級", "名稱", "判定條件", "處置"], size=12, row_h=0.78,
        align=[PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.LEFT], bold_cols=(0,))
    text(s, 0.62, 6.65, 12.0, 0.4, "顯著性：事件變化量 ÷ 該星平常 TLE 雜訊（SNR）；≥20 高、5–20 中、<5 低。"
         "輔助通道：大氣阻力殘差、ML 窗口模型、L3 融合評分器、L2 統計變點。", size=11, color=MUTED)

    # 9 各星事件數（Q4）
    s = frame(prs, "TASA 提問說明 ② 15 顆衛星各自偵測到的事件數", 9)
    tcode = {n: code for code, _, ids in TYPES for n in ids}
    order = sorted(R, key=lambda n: (-len(R[n]["events"]), "ABCD".index(tcode[n]), n))
    rows = []
    for n in order:
        r = R[n]; c = r["counts"]["grades"]; ev = r["events"]
        rows.append([str(n), disp(n, r), tcode[n], str(r["counts"]["l1_points"]), str(len(ev)),
                     str(c["E3"]), str(c["E2"]), str(c["E1"]), str(c["D"]),
                     str(sum(bool(e.get("ml_capped")) for e in ev)) if ev else "—"])
    rows.append(["合計", "", "", str(l1), str(n_ev), str(g["E3"]), str(g["E2"]), str(g["E1"]), str(g["D"]), str(n_cap)])
    cw = [0.95, 2.3, 0.7, 1.25, 1.1, 0.62, 0.62, 0.62, 0.62, 1.2]
    table(s, 0.62, 1.1, sum(cw), cw, rows,
          ["NORAD", "Name", "類型", "規則候選點", "候選事件", "E3", "E2", "E1", "D", "E2 中 ML 輔助"],
          size=12, row_h=0.318, head_h=0.4, bold_cols=(0,),
          align=[PP_ALIGN.CENTER, PP_ALIGN.LEFT] + [PP_ALIGN.CENTER] * 8)
    box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(10.85), Inches(1.1), Inches(1.78), Inches(5.47))
    box.fill.solid(); box.fill.fore_color.rgb = GRAY_ROW2; box.line.color.rgb = RGBColor(0xD5, 0xDA, 0xE3)
    text(s, 10.98, 1.25, 1.55, 5.2, [
        [("E3（依規則）", H)], [(f"{g['E3']} 件", {"size": 30, "bold": True, "color": NAVY, "after": 4})],
        [(f"E2 {g['E2']} 件，其中 ML 輔助 {n_cap} 件", {"size": 12})], [("", {"after": 8})],
        [("無超過下限事件", H)], [(f"{n_none} 顆", {"size": 30, "bold": True, "color": NAVY, "after": 4})],
        [("期間內無超過該星 5σ 下限之候選事件；不排除低於下限之機動", {"size": 12})],
    ], size=14)

    # 10 方法：10 月案例 vs R6（Q5、Q6）
    s = frame(prs, "TASA 提問說明 ③ Starlink 判斷與 Model 1／Model 2", 10)
    bullets(s, 0.86, 1.1, 11.7, 1.3, [
        [("Q：判斷是否為 Starlink 是用 AI 嗎？　", H),
         ("否。以固定規則判斷：Space-Track 編目名稱以「STARLINK」開頭即為 Starlink。"
          "分流原因是 Model 1 只用 Starlink 真值訓練，只有 Starlink 在其適用範圍內。", {})],
        [("Q：「Model 1 有 AI、Model 2 沒有」？架構有改變嗎？　", H),
         ("架構未改變。非 Starlink 之主判為 NRLMSIS 阻力殘差（物理模型，非 AI）；"
          "Model 2 為非監督式機器學習，只作佐證、不決定結果。先前「兩者皆為 AI」之說明未交代此點，在此更正。", {})],
    ], size=15, after=8)
    table(s, 0.62, 2.55, 12.1, [2.2, 4.95, 4.95], [
        ["方法", "LightGBM 梯度提升樹", "Isolation Forest 孤立森林"],
        ["學習方式", "監督式：以 Starlink 已知機動真值（MEME）訓練", "非監督式：不需機動標籤，找出「與平常不同」的異常點"],
        ["輸入", "TLE 軌道變化特徵", "以 NRLMSIS 大氣模型扣除阻力後的物理殘差"],
        ["適用", "Starlink（訓練族群 283 顆、324–588 km）", "不限星系，含 LEO／GEO"],
        ["是否 AI", "是", "是（非監督式）"],
        ["App 中的角色", "Starlink 主判（與融合評分器）", "非 Starlink 之佐證；主判為 NRLMSIS 阻力殘差（非 AI）"],
    ], ["", "Model 1", "Model 2"], size=13, row_h=0.46,
        align=[PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.LEFT], bold_cols=(0,))
    text(s, 0.62, 6.3, 12.0, 0.6, "10 月簡報的「融合評分器」也是機器學習模型（梯度提升分類器），同樣以 Starlink 真值訓練。"
         "本次 15 星報告（R7）不依 Starlink 分流，也不使用 Model 2，見下頁。", size=13, color=MUTED)

    # 11 R6 流程與 AI 角色（Q7）
    s = frame(prs, "TASA 提問說明 ④ 本次 15 顆衛星的辨識方法與 AI 角色", 11)
    text(s, 0.78, 1.0, 11.8, 0.5, [[("15 顆走同一套流程（R7），不分流到 Model 1／Model 2；", {"bold": True, "color": NAVY}),
                                   ("事件由非 AI 的規則式產生，AI 只影響等級。", {"bold": True})]], size=17)
    flow(s, 0.78, 1.62, 11.8, 1.72, [
        ("① L1 規則標點", "P1–P6：高度自適應門檻、太陽活動調整、族群倍率；阻力衰減抑制。非 AI", False),
        ("② 合併成事件", "相隔 ≤48 小時連鎖合併。非 AI", False),
        ("③ 比對輔助通道", "事件前後 24 小時內有哪些通道也觸發。含 AI（藍框）", True),
        ("④ 給證據等級", "依 SNR、通道數、型態，套固定規則；非 Starlink 之 AI 通道不決定 E3。非 AI", False),
    ], gap=0.35)
    table(s, 0.62, 3.55, 7.0, [2.05, 0.75, 4.2], [
        ["ML 窗口模型（LightGBM）", "是", "機率 ≥ 0.478，且軌道變化超過物理門檻"],
        ["L3 融合評分器", "是", "分數 ≥ 0.659（綜合統計分數與阻力殘差）"],
        ["大氣阻力殘差（NRLMSIS）", "否", "扣除阻力預期後 |殘差| > 0.3 km"],
        ["L2 統計變點", "否", "CUSUM／BOCPD／SSA／MAD 3σ，≥2 種同時觸發"],
    ], ["輔助通道", "AI", "計入條件"], size=12, row_h=0.5,
        align=[PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.LEFT], bold_cols=(0,))
    text(s, 0.62, 6.15, 7.0, 0.5, "輔助通道不增刪事件；各通道並非完全獨立，多通道一致代表值得優先複核，不是機動確認。",
         size=11, color=MUTED)
    box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(7.85), Inches(3.55), Inches(4.77), Inches(3.05))
    box.fill.solid(); box.fill.fore_color.rgb = GRAY_ROW2; box.line.color.rgb = RGBColor(0xD5, 0xDA, 0xE3)
    text(s, 8.05, 3.65, 4.4, 0.4, "AI 對本次結果的實際影響", size=16, bold=True, color=NAVY)
    bullets(s, 8.05, 4.12, 4.4, 2.45, [
        "沒有產生或刪除任何事件",
        f"{g['E3']} 件 E3 皆因連續機動段或 |淨 Δa| ≥ 10 km 成立，與 AI 無關",
        f"{n_cap} 件非 Starlink 事件符合「≥3 類通道含 AI」之 E3 條件，依 R7 規則列 E2（ML 輔助）",
        f"低置信複核項 {n_lc} 項、{n_case} 個案件，不計入事件；非 Starlink 之融合評分器項依真值驗證不列入",
    ], size=13, after=5)

    # 12 偵測能力圖（Q8）
    s = frame(prs, "TASA 提問說明 ⑤ 軌道高度 vs 可偵測機動大小", 12)
    s.shapes.add_picture(str(FIG_DET), Inches(0.55), Inches(1.0), height=Inches(5.95))
    bullets(s, 10.35, 1.25, 2.4, 5.4, [
        [("高度愈高，可偵測愈小：", H), ("400 km 附近需數百 m；800 km 以上可達公尺級。", {})],
        [("同高度仍差 5 倍以上：", H), (f"HAWK-7B（{R[56193]['alt_km_avg']:.0f} km）{R[56193]['detect_cap']['min_detect_m']:.0f} m，"
                                       f"PELICAN-8 300F（{R[69018]['alt_km_avg']:.0f} km）{R[69018]['detect_cap']['min_detect_m']:.0f} m。", {})],
        [("差異來源：", H), ("面積質量比、姿態、TLE 更新頻率。", {})],
    ], size=13, after=10)

    # 13 上下限（Q9）
    s = frame(prs, "TASA 提問說明 ⑥ 各星可偵測的上下限", 13)
    import math
    rows = []
    for n in sorted(R, key=lambda n: R[n]["detect_cap"]["sigma_med_m"]):
        r = R[n]; sg = r["detect_cap"]["sigma_med_m"]; a = 6378.137 + r["alt_km_avg"]
        dv = math.sqrt(398600.4418 / a) / (2 * a) * 20 * sg * 100
        rows.append([str(n), disp(n, r), f"{r['alt_km_avg']:.0f}", f"{5 * sg:,.0f} m", f"{20 * sg:,.0f} m", f"{dv:.1f}"])
    cw = [0.85, 2.1, 0.75, 0.95, 1.0, 1.05]
    table(s, 0.62, 1.05, sum(cw), cw, rows, ["NORAD", "Name", "高度 km", "5σ 下限", "20σ 下限", "Δv cm/s"],
          size=11, row_h=0.335, head_h=0.38, bold_cols=(0,),
          align=[PP_ALIGN.CENTER, PP_ALIGN.LEFT] + [PP_ALIGN.CENTER] * 4)
    text(s, 7.65, 1.05, 5.0, 0.4, "下限（依各星實際 TLE 雜訊 σ）", size=16, bold=True, color=NAVY)
    bullets(s, 7.65, 1.5, 5.0, 1.5, [
        [("5σ 候選下限：", H), ("超過即可能成為候選事件（最高 E2）", {})],
        [("20σ 高顯著下限：", H), ("超過即具高顯著性，可列 E3", {})],
        [("Δv：", H), ("20σ 換算之切向速度增量（1 km Δa ≈ 0.55 m/s）", {})],
    ], size=13, after=5)
    text(s, 7.65, 3.15, 5.0, 0.4, "上限：量級本身沒有偵測上限", size=16, bold=True, color=NAVY)
    bullets(s, 7.65, 3.6, 5.0, 2.6, [
        "本期最大：STARLINK-4314 連續降軌累計 −83.8 km；單一事件最大 SHIYAN 24C 02 +39.8 km",
        [("單筆 ≥ 50 km：", H), ("仍偵測，但先提示核對 TLE 與編目", {})],
        [("TLE 空窗 ≥ 7 天：", H), ("可測淨變化，但無法定位時間，最高 E2", {})],
        [("長時間微小推力：", H), ("逐筆低於下限，需靠連續機動段或阻力殘差累積發現", {})],
    ], size=13, after=5)
    text(s, 7.65, 6.3, 5.0, 0.4, f"下限以資料至 {DATA_END} 估算，隨太陽活動、阻力與 TLE 品質變動。", size=11, color=MUTED)


# ── 投影片 ────────────────────────────────────────────────────────────────────
def build(R: dict[int, dict]) -> None:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    allev = [(n, e) for n, r in R.items() for e in (r.get("events") or [])]
    g = {k: sum(1 for _, e in allev if e["grade"] == k) for k in ("E3", "E2", "E1", "D")}
    n_with = sum(1 for r in R.values() if r.get("events"))
    n_ev = len(allev)
    l1 = sum(r["counts"]["l1_points"] for r in R.values())
    red = f"−{(1 - n_ev / max(l1, 1)) * 100:.0f}%"
    floors = sorted(r["detect_cap"]["min_detect_m"] for r in R.values())

    # 1 封面
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_picture(str(TPL / "cover_bg.png"), 0, 0, prs.slide_width, prs.slide_height)
    text(s, 1.76, 1.10, 8.6, 1.0, "TASA 指定 15 顆衛星機動偵測結果", size=40, bold=True, color=WHITE)
    text(s, 1.76, 2.05, 8.0, 1.4, ["Maneuver Detection Results for", "15 TASA-Specified Satellites"],
         size=30, bold=True, color=WHITE, latin="Times New Roman")
    text(s, 0.39, 5.80, 5.0, 0.5, ["期末報告交付項目（R7 更新版）", "15-Nov-2026"], size=13, bold=True, color=WHITE, latin="Arial")

    # 2 測試標的
    s = frame(prs, "測試標的（TASA 指定 15 顆衛星）", 2)
    bullets(s, 0.86, 1.12, 11.6, 0.9, [
        "TASA 於 2026-10-30 提供 15 顆衛星，本系統以公開 TLE 進行機動偵測；"
        f"分析期間為各星可取得之完整 TLE 期間，資料截至 {DATA_END}。"], size=18)
    order = [n for _, _, ids in TYPES for n in ids]
    left, right = order[:8], order[8:]
    hdr = ["NORAD", "Name", "國別", "軌道／高度", "TLE 期間"]
    cw = [0.78, 2.02, 0.62, 1.48, 1.22]

    def row(n):
        r = R[n]
        return [str(n), disp(n, r), country(r), f"{ORBIT.get(r['inc_family'], r['inc_family'])} {r['alt_km_avg']:.0f} km",
                f"{r['start_date'][2:7].replace('-', '/')}–{r['end_date'][2:7].replace('-', '/')}"]
    table(s, 0.62, 2.02, sum(cw), cw, [row(n) for n in left], hdr, size=14, row_h=0.47)
    table(s, 6.88, 2.02, sum(cw), cw, [row(n) for n in right], hdr, size=14, row_h=0.47)
    text(s, 0.62, 6.55, 12.0, 0.55, [
        "資料來源：Space-Track.org 公開 TLE；國別依 N2YO 公開資料；SSO＝太陽同步軌道。",
        "* 69018 於 Space-Track 現行名稱為 PELICAN-8 300F，線上資料庫 catalog 名稱為 EDDA-1 300F。"],
        size=11, color=MUTED)

    # 3 檢測結果總覽
    s = frame(prs, "檢測結果總覽", 3)
    stats = [("15", "顆衛星全數完成分析"), (str(n_with), "顆偵測到候選事件"), (str(n_ev), "件候選機動事件"),
             (f"{l1}→{n_ev}", f"規則候選點自動合併（{red}）")]
    for i, (big, small) in enumerate(stats):
        x = 0.78 + i * 3.03
        b = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(1.15), Inches(2.83), Inches(1.45))
        b.fill.solid(); b.fill.fore_color.rgb = GRAY_ROW; b.line.fill.background()
        text(s, x, 1.25, 2.83, 0.8, big, size=36, bold=True, color=NAVY, align=PP_ALIGN.CENTER)
        text(s, x, 2.08, 2.83, 0.4, small, size=14, color=BLACK, align=PP_ALIGN.CENTER)
    table(s, 0.78, 2.95, 7.4, [1.55, 0.9, 4.95], [
        ["E3 高優先", str(g["E3"]), "顯著性高，且屬連續機動段或量級 ≥ 10 km（本次皆依規則成立）"],
        ["E2 人工複核", f"{g['E2']}（ML 輔助 {sum(bool(e.get('ml_capped')) for _, e in allev)}）", "顯著性中以上，至少 2 類輔助通道一致；ML 輔助＝非 Starlink 僅因 AI 通道達 E3 條件"],
        ["E1 待觀察", str(g["E1"]), "顯著性低或量級接近 TLE 雜訊"],
        ["D 資料品質待查", str(g["D"]), "回跳型態，可能為 TLE 擬合異常而非機動"],
    ], ["證據等級", "件數", "判定條件（摘要）"], size=15, row_h=0.72,
        align=[PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.LEFT], bold_cols=(0,))
    box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(8.45), Inches(2.95), Inches(4.17), Inches(3.34))
    box.fill.solid(); box.fill.fore_color.rgb = GRAY_ROW2; box.line.color.rgb = RGBColor(0xD5, 0xDA, 0xE3)
    text(s, 8.7, 3.12, 3.8, 0.4, "10/30 交付任務，測試15衛星", size=17, bold=True, color=NAVY)
    bullets(s, 8.7, 3.65, 3.75, 2.6, [
        [("交付後：", {"bold": True, "color": NAVY}), ("SJ-26 於 2026-11-09 升軌 ", {}), ("+9.8 km", {"bold": True}), ("（E2）", {})],
        [("交付前：", {"bold": True, "color": NAVY}), ("PELICAN-8 300F 於 2026-10-19 降軌 −1.6 km（E2，ML 輔助）", {})],
        [("其餘 13 顆於 10/20 後無候選事件", {})],
    ], size=15, after=10)

    # 4 事件時間軸
    s = frame(prs, "檢測結果 — 15 顆衛星事件時間軸（依行為類型分組）", 4)
    s.shapes.add_picture(str(FIG), Inches(0.50), Inches(1.10), width=Inches(12.33))

    # 5 類型歸類
    s = frame(prs, "類型歸類（依偵測到的軌道行為）", 5)
    def tcell(code, name):  # 類型欄：代號（深藍粗體）＋類型名
        return [[(code, {"bold": True, "color": NAVY, "size": 18})], [(name, {"bold": True})]]
    table(s, 0.62, 1.12, 12.1, [1.5, 2.45, 3.9, 4.25], [
        [tcell("A", "軌道轉移型"),
         ["SJ-26、HAISHAO 1、", "SHIYAN 24C 02"],
         "數 km～數十 km 級升／降軌，多伴隨傾角（平面外）變化；集中於入軌初期，之後仍有間歇性大幅調整",
         ["最大單一事件 +39.8 km（SHIYAN 24C 02）", "SJ-26 兩次約 +9.8～9.9 km 抬升（26/01、26/11）"]],
        [tcell("B", "星系營運型"),
         ["STARLINK-4314、", "STARLINK-11082"],
         "依營運模式長期控制：多日連續同向降軌，或以低於偵測下限的小推力持續補償大氣阻力（推定）",
         ["STARLINK-4314：26 天連續降軌 −83.8 km", f"STARLINK-11082：360 km 高度 7 個月首末差僅 {R[59711]['first_last_da']:+.2f} km"]],
        [tcell("C", "小幅調整型"),
         ["PELICAN-8 300F、", "ICEYE-X33"],
         "偶發單次、公里級以下為主的軌道調整，型態單純",
         "事件 |淨 Δa| 1.3～3.3 km，均為 E2（ML 輔助）"],
        [tcell("D", "無超過下限事件"),
         ["TANAGER-1、HAWK-7B、", "PELICAN-4 300B、", "SKYSAT C12、OBJECT C、", "YAOGAN-30 G、SJ 16-02、", "HJS-9A"],
         "期間僅見自然阻力衰減，無超過該星 5σ 偵測下限之候選事件；不排除低於下限之機動",
         ["首末差 −1.2～−40.5 km 為阻力衰減", "HJS-9A 僅 1 件 D 級（資料品質，不列機動）"]],
    ], ["類型", "衛星", "行為特徵", "代表數據"], size=14, row_h=1.18,
        align=[PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.LEFT])
    text(s, 0.62, 6.60, 12.0, 0.4, "分類依本系統偵測到之軌道行為歸納，不代表衛星任務性質；所有事件皆為候選，非已確認推進機動。",
         size=11, color=MUTED)

    # 6 重點事件比較
    s = frame(prs, "重點事件比較", 6)
    ev_rows = [
        ["A", "SJ-26", "2026-11-09～11-10", "+9.76", "E2", "交付後唯一新事件；跨 5.3 天 TLE 空窗，時間無法細分"],
        ["A", "SJ-26", "2025-05-29～05-31", "−38.66", "E3", "入軌初期大幅降軌，伴隨傾角變化"],
        ["A", "SHIYAN 24C 02", "2024-03-15～03-20", "+39.79", "E3", "15 顆中最大單一事件"],
        ["A", "HAISHAO 1", "2025-04-11～04-22", "+25.1", "E3/E2", "三件逐步抬升（合併呈現；2 件 E2 皆為 ML 輔助）"],
        ["B", "STARLINK-4314", "2026-08-15～09-09", "−83.8", "E3", "連續機動段：26 天、約 −3.2 km/天"],
        ["C", "PELICAN-8 300F", "2026-10-19", "−1.60", "E2＊", "交付前 11 天之單次調整"],
        ["C", "ICEYE-X33", "2026-04-17～04-18", "+1.33", "E2＊", "單次小幅抬升"],
        ["D", "HJS-9A", "2026-06-15～06-17", "+0.12", "D", "回跳型態，判為資料品質而非機動"],
    ]
    table(s, 0.62, 1.12, 12.1, [0.72, 2.0, 2.35, 1.1, 0.95, 4.98], ev_rows,
          ["類型", "衛星", "時間 (UTC)", "淨 Δa (km)", "等級", "判讀"], size=14, row_h=0.535,
          align=[PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.LEFT])
    text(s, 0.62, 6.60, 12.0, 0.4, "淨 Δa：事件前後半長軸淨變化；HAISHAO 1 與 STARLINK-4314 為多筆事件合併之累計值。＊E2（ML 輔助）：非 Starlink 僅因 AI 通道達 E3 條件。",
         size=11, color=MUTED)

    # 7 系統優點
    s = frame(prs, "系統優點", 7)
    cards = [
        ("一套流程涵蓋多種任務", "通訊、光學、SAR、RF、高光譜、實驗與遙感衛星；太陽同步、中傾角、53° 軌道皆同一流程自動分析，每顆約 10 秒內完成"),
        ("自動降噪、事件化", f"{l1} 個規則候選點自動合併為 {n_ev} 個事件（{red}）；連續多日機動整段呈現（STARLINK-4314 26 天降軌）"),
        ("證據分級＋複核優先序", "E3／E2／E1／D 對應明確行動建議；D 級辨識 TLE 資料異常（HJS-9A），不誤報為機動"),
        ("「未偵測」可量化", f"每顆衛星給出偵測下限（{floors[0]:.0f}–{floors[-1]:.0f} m），可具體陳述「期間無超過 X m 之候選事件」"),
        ("主動標示限制", "TLE 空窗（SJ-26 5.3 天、SHIYAN 24C 02 93 天）時間無法定位即明示；傾角（平面外）同步變化自動標註"),
        ("即時、可交付", "TLE 公開後即可偵測（SJ-26 11/09 升軌，資料至 11/12 即檢出）；每顆一鍵產出摘要版／技術完整版 PDF 報告"),
    ]
    for i, (h, body) in enumerate(cards):
        cx, cy = 0.78 + (i % 3) * 4.03, 1.25 + (i // 3) * 2.62
        b = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(cx), Inches(cy), Inches(3.83), Inches(2.32))
        b.fill.solid(); b.fill.fore_color.rgb = GRAY_ROW2; b.line.color.rgb = RGBColor(0xD5, 0xDA, 0xE3); b.line.width = Pt(0.75)
        c = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(cx + 0.22), Inches(cy + 0.22), Inches(0.5), Inches(0.5))
        c.fill.solid(); c.fill.fore_color.rgb = NAVY; c.line.fill.background()
        tf = c.text_frame; tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER; r = p.add_run(); r.text = str(i + 1)
        _font(r, 16, True, WHITE); tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        text(s, cx + 0.85, cy + 0.25, 2.85, 0.5, h, size=17, bold=True, color=NAVY, anchor=MSO_ANCHOR.MIDDLE)
        text(s, cx + 0.22, cy + 0.92, 3.42, 1.3, body, size=15, color=BLACK)

    # ── 系統架構說明（委員建議：釐清 Model 1／2、App 與 R6／R7）────────────────
    H = {"bold": True, "color": NAVY}
    s = frame(prs, "系統執行架構：App 即時查詢與 R7 單星報表", 0)
    s.shapes.add_picture(str(DOCS / "fig_sys_app_vs_r7.png"), Inches(0.97), Inches(1.0), width=Inches(11.4))
    table(s, 0.62, 5.95, 12.1, [2.2, 9.9], [
        ["R6、R7", "報表程式之版本號（Revision），不是模型或規則名稱；本次 15 顆衛星以 R7 產生"],
        ["Model 1、Model 2", "App 即時查詢依衛星類型選用之機器學習模型；R7 報表不分流、不使用 Model 2"],
    ], ["名詞", "意義"], size=11, row_h=0.32, head_h=0.3, align=[PP_ALIGN.LEFT, PP_ALIGN.LEFT], bold_cols=(0,))

    s = frame(prs, "R7 單星報表判定流程（TASA 15 顆衛星採用）", 0)
    s.shapes.add_picture(str(DOCS / "fig_sys_r7_flow.png"), Inches(0.45), Inches(1.0), height=Inches(5.95))
    box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(9.9), Inches(1.15), Inches(2.75), Inches(5.6))
    box.fill.solid(); box.fill.fore_color.rgb = GRAY_ROW2; box.line.color.rgb = GRAY_ROW
    text(s, 10.05, 1.25, 2.5, 0.4, "三個重點", size=16, bold=True, color=NAVY)
    bullets(s, 10.05, 1.75, 2.5, 4.9, [
        [("事件由規則產生：", H), ("候選事件只由步驟 1、2 之 L1 規則決定，非 AI。", {})],
        [("AI 只影響等級：", H), ("輔助通道不新增、不刪除事件；非 Starlink 衛星之 AI 通道不決定 E3。", {})],
        [("L1 漏看者另列：", H), ("L1 未標記、其他方法有反應之時段，列為低置信複核項（下頁）。", {})],
    ], size=12, after=10)

    s = frame(prs, "L1 未標記、L2 才發現的變化：R7 如何處理", 0)
    text(s, 0.78, 1.0, 11.8, 0.5, [[("L1 看不到的變化不會被丟棄：", H),
                                   ("列為「低置信複核項」，不計入候選事件、不給證據等級，由分析人員判讀。", {"bold": True})]], size=16)
    flow(s, 0.62, 1.6, 3.86, 1.55, [("阻力殘差", "L1 未標記，但扣除 NRLMSIS 阻力預期後之殘差超過 0.3 km（R6 起）", False)])
    flow(s, 4.69, 1.6, 3.86, 1.55, [("融合評分器", "L1 未標記，但融合評分器超過門檻（R6 起；R7 起限 Starlink）", True)])
    flow(s, 8.76, 1.6, 3.86, 1.55, [("L2 統計變點", "≥ 2 種 L2 方法於 3 天內同時觸發，且扣除背景衰減後之淨變化超過 L1 單步門檻（R7 新增）", False)])
    table(s, 0.62, 3.4, 7.3, [1.9, 5.4], [
        ["Starlink（MEME 真值）", "L1 未涵蓋之 54 件中 33 件（61%）出現在複核項；主要來自融合評分器（29 件）與阻力殘差（13 件）"],
        ["非 Starlink（IDS 點火紀錄）", "阻力殘差項補回 L1 未偵測之點火 9 次、L2 項 1 次；融合評分器項全落在安靜期（誤報），R7 已不列入"],
        ["L2 項單獨", "誤報少，但補回之 L1 漏偵不到 3%；每一步都很小、分散多筆之變化仍為已知限制"],
    ], ["真值驗證", "結果"], size=11.5, row_h=0.78, align=[PP_ALIGN.LEFT, PP_ALIGN.LEFT], bold_cols=(0,))
    box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(8.15), Inches(3.4), Inches(4.47), Inches(2.85))
    box.fill.solid(); box.fill.fore_color.rgb = GRAY_ROW2; box.line.color.rgb = GRAY_ROW
    text(s, 8.3, 3.5, 4.2, 0.4, "本次 15 顆之實例", size=15, bold=True, color=NAVY)
    bullets(s, 8.3, 3.95, 4.2, 2.3, [
        [("HAISHAO 1　2025-04-04：", H), ("各單步未達 L1 門檻，三種 L2 方法同時觸發；扣除背景衰減後淨上升 +3.5 km", {})],
        [("SHIYAN 24C 02　2024-05-08：", H), ("單步 +0.55 km、離心率同步上升，L1 未標記，由 L2 列出", {})],
    ], size=12, after=8)
    text(s, 0.62, 6.45, 12.0, 0.4, f"15 顆合計低置信複核項 {sum(len(r.get('low_conf') or []) for r in R.values())} 項"
         f"（阻力殘差、融合評分器、L2），合併為 {sum(len({x.get('case') for x in r.get('low_conf') or []}) for r in R.values())} 個複核案件，逐星列於 F2 報表。",
         size=12, color=MUTED)

    s = frame(prs, "證據等級是複核優先順序，不是機動判定", 0)
    text(s, 0.78, 1.05, 11.8, 0.9, [[("系統自動為候選事件標上優先順序標籤，提示分析人員應先處理哪些事件；", H),
                                    ("機動是否存在，由分析人員複核後確認。", {"bold": True})]], size=19)
    table(s, 0.62, 2.1, 7.4, [1.1, 1.6, 4.7], [
        ["E3", "高優先複核", "證據最強，建議立即複核；確認後再評估碰撞風險"],
        ["E2", "人工複核", "證據中等，排程複核；「ML 輔助」者優先"],
        ["E1", "待觀察", "證據不足，持續觀察"],
        ["D", "資料品質待查", "回跳型態，先核對原始 TLE 與編目"],
        ["複核項", "低置信", "L1 未標記之可疑時段，不計入候選事件"],
    ], ["標籤", "名稱", "對分析人員的意義"], size=13, row_h=0.6, align=[PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.LEFT], bold_cols=(0,))
    box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(8.3), Inches(2.1), Inches(4.32), Inches(3.62))
    box.fill.solid(); box.fill.fore_color.rgb = GRAY_ROW2; box.line.color.rgb = GRAY_ROW
    text(s, 8.45, 2.2, 4.0, 0.4, "類比：碰撞預警", size=16, bold=True, color=NAVY)
    bullets(s, 8.45, 2.7, 4.05, 3.0, [
        [("碰撞機率高，", H), ("代表應優先評估與處置，不代表必然碰撞。", {})],
        [("E3 也一樣：", H), ("代表證據較強、應先複核，不代表已確認機動。", {})],
        [("E1、D 不等於沒有機動：", H), ("只代表目前證據不足或資料需先查核。", {})],
    ], size=13, after=10)
    text(s, 0.62, 6.0, 12.0, 0.8, "公開 TLE 不含推進紀錄，同樣的軌道變化也可能來自定軌更新、TLE 擬合異常或編目交叉標記；"
         "因此報表一律稱「候選事件」，等級只排定複核順序。", size=13, color=MUTED)

    build_qa(prs, R, l1, g)

    # 14 與 2026-11-13 版（R6）之差異
    s = frame(prs, "與 2026-11-13 版（R6）之差異", 14)
    text(s, 0.78, 1.0, 11.8, 0.5, [[("E3 5 件不變；候選事件 25 → 23 件，", {"bold": True, "color": NAVY}),
                                   ("差異來自 L1 門檻修正與證據等級規則調整，衛星與分析期間相同。", {"bold": True})]], size=17)
    table(s, 0.62, 1.62, 7.35, [1.55, 2.6, 3.2], [
        ["候選事件", "25 件：E3 5／E2 14／E1 5／D 1", f"{n_ev} 件：E3 {g['E3']}／E2 {g['E2']}（ML 輔助 {sum(bool(e.get('ml_capped')) for _, e in allev)}）／E1 {g['E1']}／D {g['D']}"],
        ["規則候選點", "145 個", f"{l1} 個"],
        ["L1 門檻", "P2、P5、P6 取聯集（P5、P6 實際無作用）", "P2 × P5 × P6 有效門檻；移除 ΔΩ 標記與 P3 抑制（驗證無作用或只增誤報）"],
        ["阻力殘差通道", "未計入", "計入（NRLMSIS 大氣模型）"],
        ["非 Starlink 之 AI 通道", "可使事件達 E3", "不決定 E3，改列「E2（ML 輔助）」"],
        ["低置信複核項", "2 項（融合評分器）", f"{sum(len(r.get('low_conf') or []) for r in R.values())} 項；新增 L2 來源；非 Starlink 之融合評分器項不列入"],
        ["Model 2 說明", "「兩者皆為 AI」，未交代角色", "更正：非 Starlink 只作佐證，主判為物理模型（第 14 頁）"],
    ], ["項目", "11/13 版（R6）", "本版（R7）"], size=12, row_h=0.6,
        align=[PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.LEFT], bold_cols=(0,))
    box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(8.2), Inches(1.62), Inches(4.42), Inches(4.85))
    box.fill.solid(); box.fill.fore_color.rgb = GRAY_ROW2; box.line.color.rgb = GRAY_ROW
    text(s, 8.4, 1.75, 4.0, 0.4, "事件層級之變動", size=16, bold=True, color=NAVY)
    bullets(s, 8.4, 2.25, 4.05, 4.1, [
        [("SJ 16-02　", {"bold": True}), ("2026-01-03 −0.37 km 不再超過門檻；類型 C 改列 D", {})],
        [("HAISHAO 1　", {"bold": True}), ("2025-04-04 +1.6 km 改列 L2 低置信複核項（扣除背景衰減後 +3.5 km）", {})],
        [("HAISHAO 1　", {"bold": True}), ("2025-04-14 事件起點順延為 04-15（+9.5 → +5.2 km）", {})],
        [("STARLINK-4314　", {"bold": True}), ("2026-06-04 由 E1 改為 D（回跳型態）", {})],
        [("其餘 21 件　", {"bold": True}), ("起始時間相同，淨 Δa 小幅修正（最大 1.0 km）；等級依 R7 規則重給", {})],
    ], size=13, after=8)
    text(s, 0.62, 6.6, 12.0, 0.4, "L1 門檻修正與規則移除，依 Starlink（MEME 283 顆）、IDS 營運方點火紀錄、火箭箭體負對照與福衛七號精密定軌真值驗證；"
         "11/13 版檔案保留未覆蓋。", size=11, color=MUTED)

    # 15 NRLMSIS 大氣模型：辨識被動（自然）軌道變化
    s = frame(prs, "NRLMSIS 大氣模型：辨識被動的軌道變化", 15)
    text(s, 0.78, 1.0, 11.8, 0.5, [[("不點火，半長軸也會因阻力下降；", {"bold": True, "color": NAVY}),
                                   ("以物理模型估算應下降多少，與實測相減，剩下的才可能是主動變化。", {"bold": True})]], size=16)
    flow(s, 0.62, 1.62, 12.0, 1.62, [
        ("① 實測 Δa", "相鄰兩筆公開 TLE 之半長軸差，包含阻力衰減與可能之機動", False),
        ("② 預期阻力衰減", "NRLMSIS 2.1 依 F10.7 與每 3 小時 Ap 算大氣密度，沿軌道平均並逐時積分；彈道係數逐星以中位數自我校準", False),
        ("③ 阻力殘差", "殘差＝實測 Δa − 預期衰減。純阻力衰減時殘差接近 0；有機動時殘差約等於機動量", False),
        ("④ 判讀", "|殘差| ≤ 0.3 km：變化可由大氣解釋，傾向被動；> 0.3 km：計為輔助通道，支持主動變化", False),
    ])
    table(s, 0.62, 3.5, 12.0, [2.55, 5.2, 4.25], [
        ["事件之輔助證據", "L1 候選事件前後 24 小時內，阻力殘差未超過 0.3 km 者，不計入阻力通道，證據等級隨之降低", "15 星 23 件事件中 21 件有阻力殘差佐證"],
        ["長空窗之下降", "跨 7 天以上 TLE 空窗之下降，若實測量與阻力預期相當（殘差 < 實測之 50%），列 E1", "SHIYAN 24C 02 2026-09-18：跨 93 天 −1.28 km，阻力預期 −1.5～−1.8 km，列 E1"],
        ["預期累積", "殘差超門檻但實測 Δa 很小，殘差主要來自預期值隨空窗累積，註明不代表離散變化", f"STARLINK-4314：{'、'.join(R[53056]['counts'].get('drag_accum') or [])} 兩次"],
        ["自然再入", "近地點 < 150 km，或 < 350 km 且每日下降 > 2 km，判為自然再入，機動數輸出 0", "Van Allen 探測器（近地點 109 km）不誤判為連續機動"],
    ], ["用途", "判定方式", "實例"], size=12, row_h=0.6,
        align=[PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.LEFT], bold_cols=(0,))
    text(s, 0.62, 6.45, 12.0, 0.55, "ML 窗口模型也須阻力殘差超過 0.3 km 才計入，避免把阻力衰減誤判為機動。限制：彈道係數固定，姿態改變或磁暴期間"
         "密度誤差會使殘差偏大；0.3 km 門檻未依各星雜訊調整，低軌衛星（如 HAISHAO 1）複核項偏多。P1 衰減抑制只依 TLE 本身之單調衰減與 B*，不使用 NRLMSIS。",
         size=11, color=MUTED)

    # 16 NRLMSIS 預期自然衰減率（高度 × 時間）
    s = frame(prs, "NRLMSIS 預期之自然軌道衰減率（300–1000 km）", 16)
    s.shapes.add_picture(str(DOCS / "fig_nrlmsis_decay_expect.png"), Inches(0.45), Inches(1.0), height=Inches(5.95))
    box = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(9.35), Inches(1.15), Inches(3.3), Inches(5.6))
    box.fill.solid(); box.fill.fore_color.rgb = GRAY_ROW2; box.line.color.rgb = GRAY_ROW
    text(s, 9.5, 1.25, 3.0, 0.4, "判讀重點", size=16, bold=True, color=NAVY)
    bullets(s, 9.5, 1.75, 3.05, 4.9, [
        [("高度主導：", H := {"bold": True, "color": NAVY}), ("300 km 每日約 1–5 km，1000 km 不到 1 m，相差約 4 個數量級", {})],
        [("太陽活動：", H), ("2024 年太陽活動高峰期之衰減率約為 2026 年的 2–4 倍；磁暴期間短時再升高。", {})],
        [("實測比對：", H), ("福衛七號（576 km）預期約 12 m／日，TLE 實測 2026-10 中旬後約 11.5–12.3 m／日。", {})],
        [("系統用途：", H), ("此預期值即阻力殘差中被扣除之「被動變化」；扣除後超過 0.3 km 才視為可能之主動變化。", {})],
    ], size=12, after=8)

    # 17 Appendix
    s = frame(prs, "Appendix — 名詞與資料說明", 17)
    bullets(s, 0.86, 1.15, 11.7, 5.6, [
        [("候選事件：", {"bold": True, "color": NAVY}),
         ("由 L1 規則（P1–P6）候選點依時間相鄰合併而成，L2 統計通道與 L3 融合／ML 模型作為輔助證據；所有事件皆為候選，非已確認推進機動。", {})],
        [("證據等級：", {"bold": True, "color": NAVY}),
         ("反映複核優先順序，不是機動發生機率。E3 高優先、E2 人工複核、E1 待觀察、D 資料品質待查（回跳型態）。", {})],
        [("偵測下限：", {"bold": True, "color": NAVY}),
         ("依各星 TLE 相鄰轉換之雜訊水準估計之最小可偵測 |Δa|；低於下限之小推力（如持續補償阻力）無法逐次辨識。", {})],
        [("淨 Δa：", {"bold": True, "color": NAVY}), ("事件前後半長軸（a）淨變化；正值為抬升、負值為降低。", {})],
        [("資料與版本：", {"bold": True, "color": NAVY}),
         (f"Space-Track.org 公開 TLE（至 {DATA_END}）；報表版本 R7（2026-11-15），含 NRLMSIS 阻力殘差通道；R6 版簡報（2026-11-13）已由本版取代，差異見第 18 頁。", {})],
        [("附件：", {"bold": True, "color": NAVY}),
         ("15 顆衛星逐星 PDF 報告（摘要版 F1、技術完整版 F2，共 30 份），含半長軸時序、候選事件清單與複核建議；"
          "各星線上 F2 報告連結見下頁。", {})],
    ], size=17, after=12)

    # 9 附件：線上 F2 報告連結
    s = frame(prs, "附件 — 15 顆衛星線上 F2 報告連結", 18)
    bullets(s, 0.86, 1.12, 11.6, 0.9, [
        "點選連結即開啟線上機動偵測儀表板，自動產出該星 F2 技術完整版 PDF（期間與本簡報分析相同）；"
        "首次開啟需載入資料，約需數十秒。"], size=16)
    tcode = {n: code for code, _, ids in TYPES for n in ids}

    def lrow(n):
        r = R[n]
        return [str(n), disp(n, r), tcode[n], [[("F2 報告 ↗", {"link": f2_url(n, r), "bold": True})]]]
    hdr = ["NORAD", "Name", "類型", "線上報告"]
    cw = [0.95, 2.45, 0.85, 1.85]
    table(s, 0.62, 2.0, sum(cw), cw, [lrow(n) for n in left], hdr, size=14, row_h=0.47)
    table(s, 6.88, 2.0, sum(cw), cw, [lrow(n) for n in right], hdr, size=14, row_h=0.47)
    text(s, 0.62, 6.55, 12.0, 0.5, [
        f"連結格式：{APP_URL}/?mode=tool&norad=<NORAD>&d0=<起日>&d1=<迄日>&report=F2",
        "線上儀表板已更新為 R7（2026-11-15）；線上資料庫持續更新（含晚發布之 TLE），日後開啟之結果可能與本簡報略有差異。"],
        size=11, color=MUTED)

    # 9 結尾
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_picture(str(TPL / "end_bg.png"), 0, 0, prs.slide_width, prs.slide_height)
    text(s, 0.42, 2.80, 5.0, 0.8, "謝謝聆聽", size=36, bold=True, color=WHITE)

    prs.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    data = load(sys.argv[1])
    build_timeline(data)
    build(data)
