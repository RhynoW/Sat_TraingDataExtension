"""自 Python 版（scenario-advanced01）同步前端資產到 Rust 版 web/ 與 config/。

用法：python scripts/sync_web.py
- 以 Jinja 渲染模板（url_for → /static/…；include 展開；Rust 端執行期替換的值用 __佔位符__）
- 複製靜態 JS / CSS / 資料檔 / vendor
- 匯出 RPO 案例預設（_PRESETS / _PRESET_VARIANTS）與台北過頂類別（overpass_cats.yaml）
Python 前端更新後重跑本腳本，再重新建置 exe 即可。
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]                 # RUST_SatDashboard/
SRC = ROOT.parent / "scenario-advanced01"
PKG = SRC / "scenario04"
WEB = ROOT / "web"
WMTS = ROOT.parent.parent / "Rust_WMTS_Server"            # 網路圖磚圖資目錄來源（static/layers.js）
NET_TILE_PAGES = ("globe.html", "taipei.html", "cable.html")
NET_TILE_TAGS = ('<script src="/static/js/map_layers.js?v=__BUILD__"></script>'
                 '<script src="/ext/net_tiles.js?v=__BUILD__"></script>')

sys.path.insert(0, str(SRC))

from jinja2 import Environment, FileSystemLoader  # noqa: E402


def url_for(endpoint: str, filename: str = "", **_kw) -> str:
    assert endpoint == "static", endpoint
    return f"/static/{filename}?v=__BUILD__"


def render_templates() -> None:
    env = Environment(loader=FileSystemLoader(str(PKG / "web" / "templates")), autoescape=True)
    env.globals["url_for"] = url_for
    out = WEB / "templates"
    out.mkdir(parents=True, exist_ok=True)

    from scenario04.physics.rpo import _PRESETS  # 只讀資料，不觸發 DB
    cases = [{"primary": p, "secondary": s, **info} for (p, s), info in _PRESETS.items()]
    featured = next((c for c in cases if (c["primary"], c["secondary"]) == (69673, 67689)), None)
    rest = [c for c in cases if c is not featured]

    jobs = {
        "globe.html": {"has_logo": True},                  # Rust 版：/api/logo 讀 exe 旁 logo.png／jpg，沒有就 404 隱藏
        "taipei.html": {"cesium_token": ""},
        "cable.html": {"cesium_token": ""},
        "rpo3d.html": {"default_primary": "__PRIMARY__", "default_secondary": "__SECONDARY__",
                       "default_variant": "__VARIANT__"},
        "rpo_cases.html": {"featured": featured, "cases": rest},
        "orbit.html": {},                                   # 軌道要素歷史／雙星比較（src/orbit_history.rs）
        "track.html": {},                                   # 單顆衛星 2D 地面軌跡（/api/sat_tle）
        "orbit_tuner.html": {},                             # 軌道六參數調整器介紹頁（CTA 連回 /?open=orbit6）
        "starlink.html": {},                                # Starlink 可見性／普查／離軌（src/starlink.rs）
        "story.html": {"story_id": "__STORY_ID__"},         # 故事頁（src/story.rs 執行期替換 __STORY_ID__）
    }
    for name, ctx in jobs.items():
        html = env.get_template(name).render(cesium_cdn="", **ctx)
        if name == "globe.html":
            html = html.replace("進階版 04-adv01（向量化 SGP4 + 近距離掃描 + 搜尋）", "Rust 單機版")
        assert "{{" not in html and "{%" not in html, name
        if name in NET_TILE_PAGES:                         # 網路圖磚面板（web/ext/net_tiles.js）
            html = html.replace("</head>", NET_TILE_TAGS + "\n</head>", 1)
        if name in ("globe.html", "taipei.html", "cable.html", "rpo3d.html"):
            # 預設底圖（地形+海底地形 5.4K）、啟動視角、任務規劃按鈕、版本列與線上更新（web/ext/standalone_ext.js）
            html = html.replace("</head>", '<script src="/ext/standalone_ext.js?v=__BUILD__"></script>\n</head>', 1)
        if name == "globe.html":                           # 頂端工具列：任務規劃頁（web/ext/mission.html）
            html = html.replace(
                '<div id="lang-switcher">',
                '<button type="button" id="mission-link" class="tbtn" onclick="window.open(\'/mission\',\'_blank\')" '
                'title="地面站下行接收過頂預報（中大太遙中心 × Vantor，仰角 15°）">&#128752; 任務規劃</button>\n'
                '  <div id="lang-switcher">', 1)
        (out / name).write_text(html, encoding="utf-8", newline="\n")
        print("render", name)


def copy_static() -> None:
    src = PKG / "web" / "static"
    dst = WEB / "static"
    for sub in ("js", "css", "data", "vendor", "docs"):   # docs：故事頁引用的 PDF、QR 圖、DIA 簡報
        if (dst / sub).exists():
            shutil.rmtree(dst / sub)
        shutil.copytree(src / sub, dst / sub)
        print("copy static/" + sub)


def copy_tile_catalog() -> None:
    src = WMTS / "static" / "layers.js"
    dst = WEB / "static" / "js" / "map_layers.js"
    if src.exists():
        shutil.copy2(src, dst)
        print("copy", src, "→ static/js/map_layers.js")
    elif not dst.exists():
        raise SystemExit(f"找不到網路圖磚圖資目錄：{src}")


def export_config() -> None:
    from scenario04.physics.rpo import _PRESET_VARIANTS, _PRESETS

    def key(p, s):
        return f"{p}_{s}"

    data = {
        "presets": {key(p, s): info for (p, s), info in _PRESETS.items()},
        "variants": {key(p, s): {v: {**info, "exclude_epochs": {str(k): [list(w) for w in ws]
                                                                 for k, ws in info.get("exclude_epochs", {}).items()}}
                                    for v, info in vs.items()}
                     for (p, s), vs in _PRESET_VARIANTS.items()},
    }
    (ROOT / "config" / "rpo_presets.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    shutil.copy2(SRC / "overpass_cats.yaml", ROOT / "config" / "overpass_cats.yaml")
    print("export config/rpo_presets.json, config/overpass_cats.yaml")


def copy_embedded_data() -> None:
    """內嵌到 exe 的資料檔（客戶端資料夾沒有時使用）：衛星名稱與分類、向量圖層。"""
    shutil.copy2(PKG / "DB" / "sat_metadata.csv", ROOT / "config" / "sat_metadata.csv")
    dst = WEB / "assets" / "geojson"
    dst.mkdir(parents=True, exist_ok=True)
    for f in ("Taiwan-admin-ploygon.geojson", "openflights-airports.geojson", "submarine-cables.geojson"):
        shutil.copy2(PKG / "geojson" / f, dst / f)
    print("copy config/sat_metadata.csv, web/assets/geojson/*")


if __name__ == "__main__":
    copy_embedded_data()
    render_templates()
    copy_static()
    copy_tile_catalog()
    export_config()
