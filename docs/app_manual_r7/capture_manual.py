"""App 操作手冊（期末 R7 版）截圖：沿用影片版 capture.py 的場景與橘框標示，另加 StoryMap 與專書線上版畫面。

用法：python docs/app_manual_r7/capture_manual.py（擷取線上正式站，約 5–8 分鐘）
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://rhynowu-maneuver-detection-i18n.hf.space/"
OUT = Path(__file__).parent / "shots"
OUT.mkdir(exist_ok=True)

JS_HELPERS = r"""
window._find = (txt, sel) => {
  const all = [...document.querySelectorAll(sel || 'h1,h2,h3,p,summary,label,div,span')];
  let best = null;
  for (const e of all) {
    if (!e.offsetParent && e.tagName !== 'BODY') continue;
    if ((e.innerText || '').replace(/keyboard_arrow_(right|down)/g,'').trim().startsWith(txt)) { if (!best || best.contains(e)) best = e; }
  }
  return best;
};
window._up = (e, testid) => { while (e && !(e.dataset && e.dataset.testid === testid)) e = e.parentElement; return e; };
window._scroller = () => {
  let e = document.querySelector('[data-testid=stMain]');
  while (e) { const s = getComputedStyle(e); if (/(auto|scroll)/.test(s.overflowY) && e.scrollHeight > e.clientHeight) return e; e = e.parentElement; }
  return document.scrollingElement;
};
window._scrollTo = (e, off) => { const sc = _scroller(); const r = e.getBoundingClientRect(); sc.scrollTop += r.top - off; };
window._clearHl = () => document.querySelectorAll('.vidhl').forEach(x => x.remove());
window._hl = (rects) => {
  _clearHl();
  for (const r of rects) {
    const d = document.createElement('div'); d.className = 'vidhl';
    Object.assign(d.style, {position: 'fixed', left: (r.left - 8) + 'px', top: (r.top - 6) + 'px',
      width: (r.width + 16) + 'px', height: (r.height + 12) + 'px', border: '4px solid #FF8C00',
      borderRadius: '10px', boxShadow: '0 0 0 9999px rgba(0,0,0,0.18)', zIndex: 999999, pointerEvents: 'none'});
    document.body.appendChild(d);
  }
};
"""


def rect_of(pg, js_expr):
    return pg.evaluate(f"(() => {{ const e = {js_expr}; if (!e) return null; const r = e.getBoundingClientRect(); "
                       "return {left: r.left, top: r.top, width: r.width, height: r.height}; })()")


def union(rs):
    rs = [r for r in rs if r]
    l = min(r["left"] for r in rs); t = min(r["top"] for r in rs)
    rr = max(r["left"] + r["width"] for r in rs); b = max(r["top"] + r["height"] for r in rs)
    return {"left": l, "top": t, "width": rr - l, "height": min(b, 802) - t}


def shot(pg, name, scroll_js=None, off=70, hl=None, wait=1.5):
    pg.evaluate("_clearHl()")
    if scroll_js:
        pg.evaluate(f"_scrollTo({scroll_js}, {off})")
    time.sleep(wait)
    if hl:
        groups = [union([rect_of(pg, j) for j in g]) if isinstance(g, list) else rect_of(pg, g) for g in hl]
        pg.evaluate("(o) => { window._hl(o.r); }", {"r": [g for g in groups if g]})
    time.sleep(0.4)
    pg.screenshot(path=str(OUT / f"{name}.png"))
    print("shot", name)


def main():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 810}, device_scale_factor=4/3)
        pg.goto(URL, timeout=120000)
        pg.wait_for_selector("text=半長軸時序與候選事件", state="attached", timeout=300000)
        time.sleep(12)
        pg.add_style_tag(content="[data-testid=stStatusWidget],[data-testid=stToolbar],[data-testid=stDecoration]{visibility:hidden!important}")
        pg.evaluate("() => {" + JS_HELPERS + "}")
        F = lambda t, sel=None: f"_find({t!r}{', ' + repr(sel) if sel else ''})"
        PLOT_AFTER = lambda t: (f"(() => {{ const h = _find({t!r}); let e = h; "
                                "while (e && !e.querySelector('.js-plotly-plot')) e = e.nextElementSibling || (e.parentElement && e.parentElement.nextElementSibling); "
                                "return e ? e.querySelector('.js-plotly-plot') : null; })()")

        U = lambda js, tid: f"_up({js}, {tid!r})"
        top = F("🛰️ 機動偵測儀表板")
        shot(pg, "s02_kpi", top, 20, [U(F("近 30 天機動事件數"), "stHorizontalBlock")])
        shot(pg, "s03_lang", top, 20, [F("Language / 語言", "[data-testid=stSidebar] *"),
                                      [F("🛠️ 分析工具", "[data-testid=stSidebar] *"), F("📚 太空態勢感知", "[data-testid=stSidebar] *")]])
        shot(pg, "s04_query", top, 20, [[F("查詢", "[data-testid=stSidebar] p"), U(F("NORAD ID / 名稱", "[data-testid=stSidebar] *"), "stElementContainer")],
                                       [F("P2 高度自適應閾值", "[data-testid=stSidebar] *"), F("P5 @200sfu 倍率", "[data-testid=stSidebar] *")]])
        shot(pg, "s05_date", top, 20, [U(F("起始", "label,p"), "stHorizontalBlock"), U(F("NORAD", "label,p,div"), "stHorizontalBlock")])
        summ = F("結果摘要", "h2")
        shot(pg, "s06_summary", summ, 60, [U(F("全期間首末差", "p,div,label"), "stHorizontalBlock")])
        shot(pg, "s07_cand", summ, 60, [F("所有事件均為候選"), F("立即複核（P1）")])
        sma = F("半長軸時序與候選事件")
        shot(pg, "s08_sma", sma, 90, [sma])
        apo = F("遠地點／近地點高度歷史")
        shot(pg, "s09_apo", apo, 60, None)
        # 展開重點複核項目
        pg.evaluate("(() => { const e = _find('重點複核項目'); const ex = _up(e, 'stExpander'); const s = (ex || e).querySelector('summary') || e; s.click(); })()")
        time.sleep(2.5)
        rv = F("重點複核項目")
        shot(pg, "s10_review", rv, 70, [rv])
        shot(pg, "s11_A", F("A　候選事件", "h3"), 60, None)
        shot(pg, "s12_B", F("B　阻力模型殘差", "h3"), 60, None)
        shot(pg, "s13_C", F("C　計數口徑", "h3"), 60, [F("【各項計數的意義")])
        pg.evaluate("(() => { const s = _find('🧭 系統偵測邏輯說明', 'summary'); s.click(); })()")
        time.sleep(2.5)
        shot(pg, "s14_logic", F("最終結果怎麼來"), 330, [F("最終結果怎麼來"), F("P3 — B* 輔助抑制")])
        shot(pg, "s15_D", F("D　各層偵測器原始輸出", "h3"), 60, None)
        shot(pg, "s16_E", F("E　軌道根數連續變化", "h3"), 60, None)
        shot(pg, "s17_F", F("F　分析註記", "h3"), 60, [F("【可直接觀察】"), F("【建議複核】")])
        # PDF
        pg.evaluate("(() => { const s = _find('📄 產出 PDF 報告', 'summary'); s.click(); })()")
        time.sleep(2.5)
        pdf = F("📄 產出 PDF 報告", "summary")
        shot(pg, "s18_pdf", pdf, 160, [U(pdf, "stExpander")])
        shot(pg, "s19_quality", F("資料品質稽核", "h3"), 60, None)
        shot(pg, "s20_tools", F("星系級異常分析", "h3"), 300, [F("星系級異常分析", "h3"), F("合成 TLE 批次生成", "h3"), F("SSA-RAG 知識問答", "h3")])
        # 手冊另加：StoryMap 與專書線上版
        for name, q, key in [("m01_storymap", "?mode=storymap", "StoryMap"),
                             ("m02_storymap_case", "?mode=storymap&case=case3", "Case 3"),
                             ("m03_book", "?mode=book&ch=01", "第 1 章")]:
            pg.goto(URL + q, timeout=120000)
            pg.wait_for_selector("h1", timeout=300000)
            time.sleep(10)
            pg.add_style_tag(content="[data-testid=stStatusWidget],[data-testid=stToolbar],[data-testid=stDecoration]{visibility:hidden!important}")
            pg.screenshot(path=str(OUT / f"{name}.png"))
            print("shot", name)
        b.close()


if __name__ == "__main__":
    main()
