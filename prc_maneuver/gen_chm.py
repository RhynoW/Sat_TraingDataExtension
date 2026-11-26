"""
gen_chm.py
將 sat_profiles/ 的 Markdown 資料轉換為 CHM (Compiled HTML Help)
兩層 TOC：系列 → 衛星，含全文搜尋與 NORAD 索引

用法：
  python gen_chm.py          ← 生成 chm_build/ 並編譯
  python gen_chm.py --build  ← 只重新編譯（不重新生成 HTML）
  python gen_chm.py --html   ← 只生成 HTML（不編譯）
"""
import sys, re, os, subprocess, shutil, time, argparse, urllib.request
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict
from html import escape as he

try:
    import markdown as md_lib
except ImportError:
    print('請先: pip install markdown')
    sys.exit(1)

from make_docsify import GROUP_MAP, get_group

# ── 路徑設定 ─────────────────────────────────────────────────
PROFILES  = Path('sat_profiles')
CHM_DIR   = Path('chm_build')
CHM_OUT   = CHM_DIR / 'prc_satellites.chm'

HHC_PATHS = [
    r'C:\Program Files (x86)\HTML Help Workshop\hhc.exe',
    r'C:\Program Files\HTML Help Workshop\hhc.exe',
]

HHW_URL      = ('https://web.archive.org/web/20200918004813if_/'
                'https://download.microsoft.com/download/0/A/9/'
                '0A939EF6-E31C-430F-A3DF-DFAE7960D564/htmlhelp.exe')
HHW_FILENAME = 'htmlhelp_installer.exe'

# ── CSS ──────────────────────────────────────────────────────
CSS = """\
body {
  font-family: "Segoe UI", "Microsoft JhengHei", Arial, sans-serif;
  font-size: 15px;
  margin: 0;
  padding: 0 16px 20px;
  background: #fff;
  color: #1a1a2e;
}
h1 {
  background: #16213e;
  color: #e8f4f8;
  margin: 0 -16px 16px;
  padding: 10px 16px;
  font-size: 17px;
  letter-spacing: 0.5px;
}
h2 {
  color: #16213e;
  border-bottom: 2px solid #0f3460;
  padding-bottom: 4px;
  font-size: 15px;
  margin: 16px 0 6px;
}
h3 { color: #0f3460; font-size: 14px; margin: 10px 0 4px; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 6px 0;
  font-size: 14px;
}
th, td {
  border: 1px solid #c8d8e8;
  padding: 6px 12px;
  text-align: left;
  vertical-align: top;
}
th { background: #e8f0fe; color: #16213e; font-weight: 600; }
tr:nth-child(even) td { background: #f5f8ff; }
a { color: #0f3460; text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  background: #f0f4f8;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 13px;
  font-family: Consolas, monospace;
}
blockquote {
  border-left: 3px solid #0f3460;
  margin: 6px 0;
  padding: 5px 12px;
  background: #f0f4ff;
  color: #444;
  font-style: italic;
}
ul li, ol li { margin: 2px 0; }
.nav { font-size: 13px; color: #666; margin-bottom: 10px; }
.nav a { color: #0f3460; }
.badge {
  display: inline-block;
  background: #0f3460;
  color: white;
  font-size: 12px;
  padding: 1px 6px;
  border-radius: 8px;
  margin-left: 6px;
  vertical-align: middle;
}
"""

# ── HTML 框架 ─────────────────────────────────────────────────
def html_page(title: str, body_html: str, css_rel: str = 'style.css') -> str:
    return (
        '<!DOCTYPE html>\n<html lang="zh-Hant">\n<head>\n'
        '<meta charset="UTF-8">\n'
        f'<title>{he(title)}</title>\n'
        f'<link rel="stylesheet" href="{css_rel}">\n'
        '</head>\n<body>\n'
        + body_html +
        '\n</body>\n</html>\n'
    )


# ── Markdown → HTML ───────────────────────────────────────────
_MD = md_lib.Markdown(extensions=['tables', 'fenced_code', 'nl2br'])


def _ensure_blank_after_table(text: str) -> str:
    """python-markdown requires a blank line after a table before non-table content."""
    lines = text.split('\n')
    result = []
    for i, line in enumerate(lines):
        result.append(line)
        if (line.strip().startswith('|') and
                i + 1 < len(lines) and
                lines[i + 1].strip() and
                not lines[i + 1].strip().startswith('|')):
            result.append('')
    return '\n'.join(result)


def md2html(text: str, link_prefix: str = '') -> str:
    """
    將 Markdown 轉 HTML，同時修正連結：
      /NORAD_NAME  →  {link_prefix}NORAD_NAME.html
      _groups/slug →  {link_prefix}_groups/slug.html
      stem         →  {link_prefix}stem.html     （無副檔名的相對連結）
    """
    text = _ensure_blank_after_table(text)
    _MD.reset()
    raw = _MD.convert(text)

    def fix_link(m):
        href = m.group(1)
        # 跳過 http:// https:// # 開頭
        if re.match(r'^https?://|^#', href):
            return m.group(0)
        # 跳過已有 .html
        if href.endswith('.html'):
            return m.group(0)
        # Docsify 絕對路徑 /STEM → 相對 html
        if href.startswith('/'):
            stem = href[1:]
            return f'href="{link_prefix}{stem}.html"'
        # _groups/slug 相對路徑
        if href.startswith('_groups/'):
            return f'href="{link_prefix}{href}.html"'
        # 一般相對 stem
        return f'href="{link_prefix}{href}.html"'

    raw = re.sub(r'href="([^"]*)"', fix_link, raw)
    return raw


# ── 工具：NORAD + name ───────────────────────────────────────
def parse_stem(stem: str):
    """'26599_BEIDOU_1' → (26599, 'BEIDOU 1')"""
    parts = stem.split('_', 1)
    norad = int(parts[0]) if parts[0].isdigit() else 0
    name  = parts[1].replace('_', ' ') if len(parts) > 1 else stem
    return norad, name


# ── 安裝 HTML Help Workshop ───────────────────────────────────
def find_hhc():
    for p in HHC_PATHS:
        if Path(p).exists():
            return p
    return None


def install_hhw():
    """下載並以 UAC 靜默安裝 HTML Help Workshop"""
    dest = Path(HHW_FILENAME)
    print(f'正在下載 HTML Help Workshop ({HHW_URL})...')
    try:
        req = urllib.request.Request(
            HHW_URL, headers={'User-Agent': 'Mozilla/5.0'}
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
        print(f'  下載完成：{dest.stat().st_size/1024:.0f} KB')
    except Exception as e:
        print(f'  ❌ 下載失敗：{e}')
        print('  請手動下載：https://go.microsoft.com/fwlink/?linkid=14188')
        return False

    installer_path = dest.resolve()
    print(f'  安裝程式已儲存至：{installer_path}')
    print('  嘗試自動安裝（需要管理員權限）...')
    installed = False
    try:
        # 嘗試提權安裝（UAC 對話框）
        subprocess.run(
            ['powershell', '-Command',
             f'Start-Process -FilePath "{installer_path}" '
             f'-ArgumentList "/Q" -Verb RunAs -Wait'],
            timeout=180   # 等待使用者點「是」
        )
        time.sleep(3)
        installed = find_hhc() is not None
    except subprocess.TimeoutExpired:
        print('  ⚠️  等待 UAC 確認逾時（180 秒）')
    except Exception as e:
        print(f'  ⚠️  自動安裝失敗：{e}')

    hhc = find_hhc()
    if hhc:
        print(f'  ✅ 安裝成功：{hhc}')
        dest.unlink(missing_ok=True)
        return True
    else:
        print(f"""
  ─────────────────────────────────────────────────────
  ⚠️  請手動完成安裝：

  1. 雙擊執行此安裝程式（需要管理員權限）：
     {installer_path}

  2. 安裝完成後，重新執行：
     python gen_chm.py --build

  （HTML 檔案已生成在 chm_build/，--build 只執行編譯步驟）
  ─────────────────────────────────────────────────────
""")
        return False


# ── 生成 HTML 檔案 ────────────────────────────────────────────
def gen_html_files():
    """將所有 .md 轉為 HTML，儲存至 chm_build/"""
    skip = {'README.md', '_sidebar.md', 'index.html', 'index_cdn.html', '.nojekyll'}

    # ── 準備輸出目錄 ──
    CHM_DIR.mkdir(exist_ok=True)
    (CHM_DIR / '_groups').mkdir(exist_ok=True)
    css_path = CHM_DIR / 'style.css'
    css_path.write_text(CSS, encoding='utf-8')

    # ── 衛星 profiles ──
    profile_files = [
        f for f in sorted(PROFILES.glob('*.md'))
        if f.name not in skip
    ]
    print(f'轉換 {len(profile_files)} 個衛星 profile...')
    for f in profile_files:
        norad, name = parse_stem(f.stem)
        md_text = f.read_text(encoding='utf-8')
        body = md2html(md_text, link_prefix='')
        # 加導覽列
        nav = f'<p class="nav"><a href="home.html">🏠 首頁</a></p>\n'
        out = CHM_DIR / f'{f.stem}.html'
        out.write_text(html_page(f'{name} ({norad})', nav + body), encoding='utf-8')

    # ── _groups/ 系列索引頁 ──
    group_md_files = list((PROFILES / '_groups').glob('*.md'))
    print(f'轉換 {len(group_md_files)} 個系列索引頁...')
    for f in group_md_files:
        md_text = f.read_text(encoding='utf-8')
        # 系列頁中的連結用 ../ 前綴（因在 _groups/ 子目錄下）
        body = md2html(md_text, link_prefix='../')
        nav  = '<p class="nav"><a href="../home.html">🏠 首頁</a></p>\n'
        # 系列頁的 h1 標題
        title_m = re.search(r'^#\s+(.+)', md_text, re.MULTILINE)
        title   = title_m.group(1) if title_m else f.stem
        out = CHM_DIR / '_groups' / f'{f.stem}.html'
        out.write_text(
            html_page(title, nav + body, css_rel='../style.css'),
            encoding='utf-8'
        )

    # ── 首頁 ──
    gen_home()
    print(f'✅ HTML 生成完成 → {CHM_DIR.resolve()}')


def gen_home():
    """生成首頁 home.html（系列統計表）"""
    readme = PROFILES / 'README.md'
    if readme.exists():
        md_text = readme.read_text(encoding='utf-8')
        # 替換 _groups/ 連結 → _groups/xxx.html
        md_text = re.sub(
            r'\]\(_groups/([^)]+)\)',
            r'](_groups/\1.html)',
            md_text
        )
        body = md_lib.Markdown(extensions=['tables']).convert(md_text)
    else:
        body = '<h1>PRC 衛星資料庫</h1>'

    out = CHM_DIR / 'home.html'
    out.write_text(html_page('🛰 PRC 衛星資料庫', body), encoding='utf-8')


# ── 生成 HHC (Table of Contents) ─────────────────────────────
def gen_toc(groups: dict[str, list]) -> str:
    """
    生成 toc.hhc 內容。
    groups: {group_name: [(norad, name, stem), ...]}
    """
    lines = [
        '<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML//EN">',
        '<HTML><HEAD></HEAD><BODY>',
        '<OBJECT type="text/site properties">',
        '  <param name="Auto Generated" value="No">',
        '  <param name="ImageType" value="Folder">',
        '</OBJECT>',
        '<UL>',
        '  <LI><OBJECT type="text/sitemap">',
        '    <param name="Name" value="PRC 衛星資料庫（首頁）">',
        '    <param name="Local" value="home.html">',
        '  </OBJECT>',
    ]

    # 按系列分組
    for gname in sorted(groups.keys()):
        items = sorted(groups[gname], key=lambda x: x[0])
        # 取系列索引頁 slug（與 gen_group_pages.py 邏輯一致）
        # 直接找 _groups/ 對應 html（用 get_group 推斷）
        slug = _find_group_slug(gname)
        group_href = f'_groups/{slug}.html' if slug else 'home.html'

        lines += [
            '  <LI><OBJECT type="text/sitemap">',
            f'    <param name="Name" value="{he(gname)}">',
            f'    <param name="Local" value="{group_href}">',
            '  </OBJECT>',
            '  <UL>',
        ]
        for norad, name, stem in items:
            lines += [
                '    <LI><OBJECT type="text/sitemap">',
                f'      <param name="Name" value="{he(name)} ({norad})">',
                f'      <param name="Local" value="{stem}.html">',
                '    </OBJECT>',
            ]
        lines.append('  </UL>')

    lines += ['</UL>', '</BODY></HTML>']
    return '\n'.join(lines)


_SLUG_CACHE: dict[str, str] | None = None


def _find_group_slug(gname: str) -> str | None:
    """從 _groups/ 目錄找到與 gname 對應的 slug（用 md 檔第一行 # 匹配）"""
    global _SLUG_CACHE
    if _SLUG_CACHE is None:
        _SLUG_CACHE = {}
        groups_dir = PROFILES / '_groups'
        for f in groups_dir.glob('*.md'):
            first = f.read_text(encoding='utf-8').split('\n', 1)[0]
            if first.startswith('# '):
                _SLUG_CACHE[first[2:].strip()] = f.stem
    return _SLUG_CACHE.get(gname)


# ── 生成 HHK (Keyword Index) ──────────────────────────────────
def gen_index(groups: dict[str, list]) -> str:
    """生成 index.hhk：NORAD ID 和衛星名稱都可搜尋"""
    lines = [
        '<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML//EN">',
        '<HTML><HEAD></HEAD><BODY>',
        '<UL>',
    ]
    all_items = []
    for items in groups.values():
        all_items.extend(items)
    all_items.sort(key=lambda x: x[1])   # 按名稱排序

    for norad, name, stem in all_items:
        href = f'{stem}.html'
        # 名稱索引
        lines += [
            '  <LI><OBJECT type="text/sitemap">',
            f'    <param name="Name" value="{he(name)}">',
            f'    <param name="Local" value="{href}">',
            '  </OBJECT>',
        ]
        # NORAD ID 索引
        lines += [
            '  <LI><OBJECT type="text/sitemap">',
            f'    <param name="Name" value="{norad}">',
            f'    <param name="Local" value="{href}">',
            '  </OBJECT>',
        ]

    lines += ['</UL>', '</BODY></HTML>']
    return '\n'.join(lines)


# ── 生成 HHP (Project File) ───────────────────────────────────
def gen_project(all_html_files: list[str]) -> str:
    """生成 prc_satellites.hhp"""
    files_section = '\n'.join(all_html_files)
    return f"""\
[OPTIONS]
Compiled file=prc_satellites.chm
Contents file=toc.hhc
Default Window=main
Default topic=home.html
Display compile progress=Yes
Full-text search=Yes
Index file=index.hhk
Language=0x0404 Chinese (Traditional)
Title=PRC Satellite Database

[WINDOWS]
main="PRC Satellite Database","toc.hhc","index.hhk","home.html","home.html",,,,,0x63520,,0x2520,,,,,,,,0

[FILES]
style.css
home.html
{files_section}
"""


# ── 編譯 CHM ──────────────────────────────────────────────────
def compile_chm(hhc: str):
    hhp = CHM_DIR / 'prc_satellites.hhp'
    out_file = CHM_DIR / 'prc_satellites.chm'
    # 刪除舊檔，避免「存在即視為成功」的假陽性
    if out_file.exists():
        try:
            out_file.unlink()
        except PermissionError:
            print('  ⚠️  舊 CHM 仍被開啟，請先關閉 CHM 閱讀器後重試')
            return False

    print(f'\n編譯 CHM: {hhp.resolve()}')
    print(f'  使用: {hhc}')
    # hhc.exe returns 1 even on success (normal behaviour)
    result = subprocess.run(
        [hhc, str(hhp.resolve())],
        capture_output=True, text=True, encoding='mbcs', errors='replace',
        cwd=str(CHM_DIR.resolve()),
    )
    # 顯示 hhc.exe 輸出（無論成功失敗，便於診斷）
    if result.stdout.strip():
        print('  [hhc output]', result.stdout.strip()[:800])
    if result.stderr.strip():
        print('  [hhc stderr]', result.stderr.strip()[:400])

    if out_file.exists():
        size = out_file.stat().st_size / (1024 * 1024)
        print(f'  ✅ 編譯成功！{out_file.resolve()} ({size:.1f} MB)')
        return True
    else:
        print(f'  ❌ 編譯失敗（exit={result.returncode}）')
        return False


# ── 主流程 ────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--html',  action='store_true', help='只生成 HTML，不編譯')
    parser.add_argument('--build', action='store_true', help='只重新編譯 CHM')
    args = parser.parse_args()

    print('=' * 55)
    print(' gen_chm.py — PRC 衛星 CHM 製作工具')
    print('=' * 55)

    # ── Step 1: 掃描 profile 檔案 ────────────────────────────
    skip = {'README.md', '_sidebar.md', 'index.html', 'index_cdn.html', '.nojekyll'}
    profile_files = [
        f for f in sorted(PROFILES.glob('*.md'))
        if f.name not in skip
    ]
    print(f'共 {len(profile_files)} 個衛星 profile')

    # 分組
    groups: dict[str, list] = defaultdict(list)
    for f in profile_files:
        gname = get_group(f.stem)
        norad, name = parse_stem(f.stem)
        groups[gname].append((norad, name, f.stem))

    # ── Step 2: 生成 HTML ────────────────────────────────────
    if not args.build:
        gen_html_files()
    else:
        # --build 模式：仍更新 style.css（字型/樣式可能已修改）
        CHM_DIR.mkdir(exist_ok=True)
        (CHM_DIR / 'style.css').write_text(CSS, encoding='utf-8')
        print('  ✅ style.css 已更新')

    # ── Step 3: 生成控制檔 ───────────────────────────────────
    print('生成 TOC / Index / Project 檔案...')
    toc_html  = gen_toc(groups)
    idx_html  = gen_index(groups)

    # 收集所有 HTML 路徑（相對於 chm_build/）
    all_html = (
        [f.stem + '.html' for f in profile_files]
        + [f'_groups/{f.stem}.html' for f in (PROFILES / '_groups').glob('*.md')]
    )
    prj_text = gen_project(all_html)

    # hhc.exe 讀取 HHC/HHK 時使用系統 ANSI (cp950)，必須以 cp950 寫入
    # HTML 衛星檔仍用 UTF-8（瀏覽器尊重 <meta charset="UTF-8">）
    (CHM_DIR / 'toc.hhc').write_text(toc_html, encoding='cp950', errors='replace')
    (CHM_DIR / 'index.hhk').write_text(idx_html, encoding='cp950', errors='replace')
    # HHP 為 INI 格式，已使用 ASCII-only Title/WINDOW，utf-8 相容
    (CHM_DIR / 'prc_satellites.hhp').write_text(prj_text, encoding='utf-8')
    print('  ✅ toc.hhc / index.hhk / prc_satellites.hhp')

    if args.html:
        print('\n（--html 模式：跳過編譯）')
        return

    # ── Step 4: 找 / 安裝 HTML Help Workshop ─────────────────
    hhc = find_hhc()
    if not hhc:
        print('\n⚠️  找不到 HTML Help Workshop，嘗試自動安裝...')
        ok = install_hhw()
        if not ok:
            print('\n請手動安裝後重新執行，或用 --html 只生成 HTML 檔案。')
            return
        hhc = find_hhc()

    # ── Step 5: 編譯 ─────────────────────────────────────────
    ok = compile_chm(hhc)
    if ok:
        print(f"""
╔══════════════════════════════════════════════════════╗
║  CHM 製作完成！                                      ║
╠══════════════════════════════════════════════════════╣
║  位置：{str(CHM_DIR / 'prc_satellites.chm'):<47}║
║  直接雙擊 .chm 即可開啟（Windows 內建閱讀器）        ║
╚══════════════════════════════════════════════════════╝
""")


if __name__ == '__main__':
    import os
    os.chdir(Path(__file__).parent)
    main()
