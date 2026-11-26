"""
make_docsify.py
為 PRC sat_profiles/ 建立 Docsify 可搜尋靜態網站

用法：
  python make_docsify.py --test   小批量測試（每系列抽 1 顆，共 ~20 顆）
  python make_docsify.py --full   完整版（直接寫入 sat_profiles/）
"""
import sys, shutil, argparse, re
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path
from collections import defaultdict, Counter

PROFILES = Path('sat_profiles')
TEST_OUT  = Path('docsify_test')

# ─── 系列分組規則 ───────────────────────────────────────────
GROUP_MAP = {
    # GEO 商業通信 ─────────────────────────────────────
    'APSTAR':      'APSTAR 亞太通信',
    'CHINASAT':    'ChinaSat 中星',
    'STTW':        'STTW 東方紅二號',
    'DFH':         'DFH 東方紅',
    'TIANTONG':    'TianTong 天通（移動通信）',
    'SINOSAT':     'ChinaSat 中星',
    'HG':          'ChinaSat 中星',

    # 導航 ──────────────────────────────────────────────
    'BEIDOU':      'BeiDou 北斗（導航）',
    'CENTISPACE':  'CentiSpace 定位增強',
    'NINGXIA':     'NingXia 寧夏（LEO 導航增強）',

    # 對地觀測 ─────────────────────────────────────────
    'GAOFEN':      'GaoFen 高分（對地觀測）',
    'JILIN':       'JiLin 吉林（商業光學）',
    'SUPERVIEW':   'SuperView 超景（商業光學）',
    'ZHUHAI':      'ZhuHai 珠海（高光譜）',
    'HAIYANG':     'HaiYang 海洋（海洋觀測）',
    'HAIWANGXING': 'HaiYang 海洋（海洋觀測）',
    'HJ':          'HJ/HJS 環境減災',
    'HJS':         'HJ/HJS 環境減災',
    'FENGYUN':     'FengYun 風雲（氣象）',
    'YUNHAI':      'YunHai 雲海（氣象）',
    'TIANMU':      'TianMu 天目（商業氣象）',
    'CFOSAT':      'HaiYang 海洋（海洋觀測）',
    'BEIJING':     'JiLin 吉林（商業光學）',
    'DAQI':        'GaoFen 高分（對地觀測）',
    'LKW':         'LKW 陸地偵察',
    'ZY':          'ZY 資源（土地資源）',
    'LUOJIA':      'GaoFen 高分（對地觀測）',
    'LT':          'LT 陸探（L-SAR）',
    'TIANHUI':     'TianHui 天繪（測繪）',
    'HEAD':        'HEAD 商業衛星（AIS/光學）',
    'PIESAT':      'PieSat 派思（SAR）',
    'GEESAT':      'GEESAT 極星（IoT）',

    # 情報偵察 ─────────────────────────────────────────
    'YAOGAN':      'YaoGan 遙感（偵察）',
    'JB':          'JB 尖兵（偵察）',
    'GJZ':         'GJZ 系列',
    'XJS':         'XJS 系列',

    # 通信中繼 ─────────────────────────────────────────
    'TIANLIAN':    'TianLian 天鏈（中繼）',
    'TJS':         'TJS（高傾 GEO）',

    # 寬帶/IoT 星座 ────────────────────────────────────
    'HULIANWANG':  'HULIANWANG 互聯網低軌',
    'QIANFAN':     'QianFan 千帆（寬帶 LEO）',
    'TIANQI':      'TianQi 天啟（IoT）',
    'XINGYUN':     'XingYun 行雲（IoT）',
    'HONGYAN':     'HONG 星座試驗',
    'HONGYUN':     'HONG 星座試驗',
    'HONGHU':      '試驗雜項',
    'YUNYAO':      'YunYao 雲堯（IoT）',

    # 空間站 ───────────────────────────────────────────
    'CSS':         'CSS 中國空間站',
    'SZ':          'SZ 神舟（載人飛船）',
    'TIANZHOU':    'TianZhou 天舟（貨運）',

    # 實踐 / 試驗 ──────────────────────────────────────
    'SJ':          'SJ 實踐（技術試驗）',
    'SHIYAN':      'ShiYan 試驗',
    'SHIYUAN':     'ShiYan 試驗',
    'CHUANG':      'Chuang Xin 創新（試驗）',
    'CHUANGXIN':   'Chuang Xin 創新（試驗）',
    'RSW':         'ShiYan 試驗',
    'TIANZHI':     'ShiYan 試驗',
    'TIANYI':      'ShiYan 試驗',
    'TIANYAN':     'ShiYan 試驗',
    'TIANPING':    'ShiYan 試驗',
    'TIANXING':    'ShiYan 試驗',
    'TIANTUO':     'ShiYan 試驗',
    'PRC':         'ShiYan 試驗',
    'QIANKUN':     'ShiYan 試驗',
    'XPNAV':       'ShiYan 試驗',
    'KL':          'ShiYan 試驗',
    'YIJIAN':      'ShiYan 試驗',
    'XY':          'ShiYan 試驗',
    'TK':          'ShiYan 試驗',
    'TANSUO':      'ShiYan 試驗',

    # 科學衛星 ─────────────────────────────────────────
    'DOUBLESTAR':  '科學衛星',
    'DAMPE':       '科學衛星',
    'EINSTEIN':    '科學衛星',
    'GECAM':       '科學衛星',
    'ASO':         '科學衛星',
    'QSS':         '科學衛星',
    'TANSAT':      '科學衛星',
    'TANSAT2':     '科學衛星',
    'ASO':         '科學衛星',

    # 深空任務 ─────────────────────────────────────────
    'DRO':         '深空任務',
    'CHANGE':      '深空任務',
    'TIANWEN':     '深空任務',

    # 業餘無線電 / 大學 CubeSat ────────────────────────
    'XW':          '業餘無線電 / 大學 CubeSat',
    'CAS':         '業餘無線電 / 大學 CubeSat',
    'XIWANG':      '業餘無線電 / 大學 CubeSat',
    'BY70':        '業餘無線電 / 大學 CubeSat',
    'ZHEDA':       '業餘無線電 / 大學 CubeSat',
    'ZDPS':        '業餘無線電 / 大學 CubeSat',
    'BNU':         '業餘無線電 / 大學 CubeSat',
    'LILACSAT':    '業餘無線電 / 大學 CubeSat',
    'TSINGHUA':    '業餘無線電 / 大學 CubeSat',
    'NAXING':      '業餘無線電 / 大學 CubeSat',
    'ZHOU':        '業餘無線電 / 大學 CubeSat',
    'QUANTUTONG':  '業餘無線電 / 大學 CubeSat',

    # 外國客星（CZ 發射）──────────────────────────────
    'IRIDIUM':     '外國客星（CZ 發射）',
    'CBERS':       '外國客星（CZ 發射）',
    'VRSS':        '外國客星（CZ 發射）',
    'PAKSAT':      '外國客星（CZ 發射）',
    'PAKTES':      '外國客星（CZ 發射）',
    'PALAPA':      '外國客星（CZ 發射）',
    'PRSS':        '外國客星（CZ 發射）',
    'MISRSAT':     '外國客星（CZ 發射）',
    'SAUDISAT':    '外國客星（CZ 發射）',
    'NIGCOMSAT':   '外國客星（CZ 發射）',
    'BELINTERSAT': '外國客星（CZ 發射）',
    'ALCOMSAT':    '外國客星（CZ 發射）',
    'LAOSAT':      '外國客星（CZ 發射）',
    'VENESAT':     '外國客星（CZ 發射）',
    'TUPAC':       '外國客星（CZ 發射）',
    'GOKTURK':     '外國客星（CZ 發射）',
    'HORUS':       '外國客星（CZ 發射）',
    'ALSAT':       '外國客星（CZ 發射）',
    'OL':          '外國客星（CZ 發射）',
    'ION':         '外國客星（CZ 發射）',
    'FREJA':       '外國客星（CZ 發射）',
    'NUSAT':       '外國客星（CZ 發射）',
    'GOMX4':       '外國客星（CZ 發射）',
    'CUBEBUG':     '外國客星（CZ 發射）',
    'FLORIPASAT':  '外國客星（CZ 發射）',
    'SACI':        '外國客星（CZ 發射）',
    'NEE':         '外國客星（CZ 發射）',
    'TURKSAT':     '外國客星（CZ 發射）',
    'BRITE':       '外國客星（CZ 發射）',
    'KEPLER':      '外國客星（CZ 發射）',
    'SPARK':       '外國客星（CZ 發射）',
    'ECHOSTAR':    '外國客星（CZ 發射）',
    'EUTE':        '外國客星（CZ 發射）',
    'AMOS':        '外國客星（CZ 發射）',
    'ASIASAT':     '外國客星（CZ 發射）',
    'OPTUS':       '外國客星（CZ 發射）',
    'ABS':         '外國客星（CZ 發射）',
    'TELSTAR':     '外國客星（CZ 發射）',
    'STARLINK':    '外國客星（CZ 發射）',

    # 商業遙感雜項 ─────────────────────────────────────
    'WEINA':       '商業遙感 / 雜項',
    'XINGCHI':     '商業遙感 / 雜項',
    'XINGSHIDAI':  '商業遙感 / 雜項',
    'XIAOXIANG':   '商業遙感 / 雜項',
    'XAIOXIANG':   '商業遙感 / 雜項',
    'LINGQIAO':    '商業遙感 / 雜項',
    'LING':        '商業遙感 / 雜項',
    'LQSAT':       '商業遙感 / 雜項',
    'PUJIANG':     '商業遙感 / 雜項',
    'ZHIHUI':      '商業遙感 / 雜項',
    'JIAOTONG':    '商業遙感 / 雜項',
    'YINHE':       '商業遙感 / 雜項',
    'ENSHI':       '商業遙感 / 雜項',
    'TIANYI':      '商業遙感 / 雜項',

    # OBJECT 未命名 ────────────────────────────────────
    'OBJECT':      'OBJECT（未命名碎片/衛星）',

    # CZ 火箭殘骸 ──────────────────────────────────────
    'CZ':          'CZ 火箭殘骸（R/B）',
    'GRAVITY':     'CZ 火箭殘骸（R/B）',
    'ZK':          'CZ 火箭殘骸（R/B）',
    'FORMOSAT':    '外國客星（CZ 發射）',

    # 其餘雜項 ─────────────────────────────────────────
    'CUBEBEL':     '業餘無線電 / 大學 CubeSat',
    'CTDRS':       'ShiYan 試驗',
    'DEAR':        'ShiYan 試驗',
    'DALIAN':      'ShiYan 試驗',
    'FENGNIAO':    'ShiYan 試驗',
    'GJZ':         'GJZ 系列',
    'HAISI':       'ShiYan 試驗',
    'ICECUBE':     'ShiYan 試驗',
    'JINZIJING':   'ShiYan 試驗',
    'JB':          'JB 尖兵（偵察）',
    'KAIDUN':      'ShiYan 試驗',
    'KAITUO':      'ShiYan 試驗',
    'KX':          'ShiYan 試驗',
    'LUOJIA':      '科學衛星',
    'DUMMY':       'ShiYan 試驗',
    'DOUBLESTAR':  '科學衛星',
    'DRO':         '深空任務',
    'HAISI':       'ShiYan 試驗',
    'RSW':         'ShiYan 試驗',
    'PAYLOAD':     'ShiYan 試驗',
    'XINGSHIDAI':  '商業遙感 / 雜項',
    'XJY':         'ShiYan 試驗',
    'YUANGUANG':   'ShiYan 試驗',
    'TAURUS':      '業餘無線電 / 大學 CubeSat',
}

def get_group(stem: str) -> str:
    parts = stem.split('_', 1)
    if len(parts) < 2:
        return '其他'
    first = parts[1].split('_')[0].upper()
    # Handle hyphenated names like QIANFAN-101 → stem is QIANFAN_101
    first = first.split('-')[0]
    return GROUP_MAP.get(first, f'{first}（其他）')

def sat_display(stem: str) -> str:
    """產生人類可讀的衛星短名稱（用於側欄）"""
    parts = stem.split('_', 1)
    norad = parts[0]
    name  = parts[1].replace('_', ' ') if len(parts) > 1 else stem
    # Trim very long names
    if len(name) > 36:
        name = name[:33] + '…'
    return f'{name}', norad

# ─── 模板檔案 ─────────────────────────────────────────────

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
  <meta charset="UTF-8">
  <title>PRC 衛星資料庫</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="//cdn.jsdelivr.net/npm/docsify@4/lib/themes/vue.css">
  <style>
    :root { --theme-color: #1a5276; }
    body  { font-family: "Noto Sans TC", "Microsoft JhengHei", sans-serif; }
    .sidebar       { background: #f0f4f8; border-right: 1px solid #dde; }
    .sidebar-nav   { padding-bottom: 2rem; }
    .sidebar-nav li{ font-size: 0.84em; line-height: 1.7; }
    .sidebar-nav > ul > li > strong { color: #1a5276; font-size: 0.95em; }
    .app-name      { font-size: 1.1em; font-weight: 700; }
    .markdown-section h1 { color: #1a5276; border-bottom: 2px solid #1a5276; padding-bottom: 6px; }
    .markdown-section h2 { color: #2471a3; border-bottom: 1px solid #aac; padding-bottom: 4px; }
    .markdown-section table { width: 100%; border-collapse: collapse; }
    .markdown-section table td, .markdown-section table th {
      padding: 5px 10px; border: 1px solid #dde; }
    .markdown-section table tr:nth-child(even) { background: #f5f8fb; }
    code { background: #eaf0f8; padding: 1px 5px; border-radius: 3px; font-size: 0.88em; }
    .search .clear-button { cursor: pointer; }
    /* 搜尋高亮 */
    .search mark { background: #fff176; border-radius: 2px; }
  </style>
</head>
<body>
  <div id="app">⏳ 載入中...</div>
  <script>
    window.$docsify = {
      name: '🛰 PRC 衛星資料庫',
      nameLink: '/',
      repo: false,
      homepage: 'README.md',
      loadSidebar: '_sidebar.md',
      subMaxLevel: 1,
      auto2top: true,
      noEmoji: false,
      search: {
        maxAge: 86400000,       // 本地搜尋索引快取 24 h
        paths: 'auto',          // 自動爬取 _sidebar.md 所有連結
        placeholder: '🔍 搜尋衛星名稱、NORAD ID、任務…',
        noData:      '😕 找不到相關衛星',
        depth: 6,
        hideOtherSidebarContent: false,
        namespace: 'prc-sat-db-v2',
      },
    }
  </script>
  <!-- Docsify core (CDN，首次需連線；之後瀏覽器快取) -->
  <script src="//cdn.jsdelivr.net/npm/docsify@4/lib/docsify.min.js"></script>
  <!-- 搜尋插件 -->
  <script src="//cdn.jsdelivr.net/npm/docsify@4/lib/plugins/search.min.js"></script>
  <!-- 複製程式碼按鈕（選用） -->
  <script src="//cdn.jsdelivr.net/npm/docsify-copy-code@2/dist/docsify-copy-code.min.js"></script>
</body>
</html>
"""

def make_readme(all_files: list, is_test: bool) -> str:
    total  = len(all_files)
    note   = '（**測試模式**，僅含樣本）' if is_test else ''
    groups = Counter(get_group(f.stem) for f in all_files)

    # Score 有值的衛星（從 prc_maneuver CSV 中有評分的，透過 profile 中的文字偵測）
    # 簡化：只用 group count table
    table_rows = '\n'.join(
        f'| {g} | {c} |'
        for g, c in sorted(groups.items(), key=lambda x: -x[1])
    )

    return f"""\
# 🛰 PRC 衛星資料庫 {note}

> 收錄 **{total}** 顆 PRC（中國）衛星的軌道資料、任務背景與機動行為分析。
> 資料來源：N2YO、COSPAR、PRC 機動偵測 CSV（maneuver score）。

## 使用說明

| 方式 | 操作 |
|------|------|
| **搜尋** | 上方搜尋框輸入衛星名稱、NORAD ID、任務類型關鍵字 |
| **瀏覽系列** | 左側側欄按衛星系列展開 |
| **直接連結** | URL hash 格式：`#/NORAD_SATNAME` |

## 系列統計

| 系列 | 衛星數 |
|------|--------|
{table_rows}
"""

def make_sidebar(all_files: list) -> str:
    groups: dict[str, list] = defaultdict(list)
    for f in sorted(all_files, key=lambda x: x.stem):
        groups[get_group(f.stem)].append(f)

    lines = ['* [🏠 首頁](/)', '']
    for group in sorted(groups.keys()):
        lines.append(f'* **{group}**')
        for f in groups[group]:
            name, norad = sat_display(f.stem)
            lines.append(f'  * [{name}]({f.stem})')
        lines.append('')
    return '\n'.join(lines)


def setup(out_dir: Path, files: list, is_test: bool):
    out_dir.mkdir(parents=True, exist_ok=True)

    copied = skipped = 0
    for f in files:
        dest = out_dir / f.name
        if not dest.exists():
            shutil.copy2(f, dest)
            copied += 1
        else:
            skipped += 1

    (out_dir / 'index.html').write_text(INDEX_HTML, encoding='utf-8')
    (out_dir / 'README.md').write_text(make_readme(files, is_test), encoding='utf-8')
    (out_dir / '_sidebar.md').write_text(make_sidebar(files), encoding='utf-8')
    (out_dir / '.nojekyll').write_text('', encoding='utf-8')

    print(f'✅ 完成：{len(files)} 個 profile（複製 {copied}，已存在跳過 {skipped}）')
    print(f'📁 目錄：{out_dir.resolve()}')
    print()
    print('▶  啟動本地伺服器（在新終端機執行）：')
    print(f'     cd "{out_dir.resolve()}"')
    print(f'     python -m http.server 3000')
    print()
    print('🌐  瀏覽器開啟：http://localhost:3000')
    print()
    print('💡  提示：首次開啟會建立搜尋索引（稍慢），之後快取在 localStorage。')


# ─── 主程式 ───────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='小批量測試（每系列抽 1 顆）')
    parser.add_argument('--full', action='store_true', help='完整版（寫入 sat_profiles/）')
    args = parser.parse_args()

    all_md = sorted(PROFILES.glob('*.md'))
    if not all_md:
        print('錯誤：sat_profiles/ 目錄下沒有 .md 檔案')
        sys.exit(1)

    print(f'找到 {len(all_md)} 個 profile')

    if args.test:
        # 每個系列最多抽 1 顆，但排除 OBJECT 群組
        groups: dict[str, list] = defaultdict(list)
        for f in all_md:
            g = get_group(f.stem)
            if 'OBJECT' not in g:
                groups[g].append(f)
        # 排序後每組取第一顆，最多 25 組
        sample = []
        for g in sorted(groups.keys())[:25]:
            if groups[g]:
                sample.append(groups[g][0])

        print(f'\n測試樣本（{len(sample)} 顆）：')
        for f in sample:
            print(f'  {f.name}')
        print()
        setup(TEST_OUT, sample, is_test=True)

    elif args.full:
        print('寫入完整版到 sat_profiles/ ...')
        # 在 sat_profiles/ 裡直接寫入 Docsify 基礎設施（不需複製 .md 檔案）
        (PROFILES / 'index.html').write_text(INDEX_HTML, encoding='utf-8')
        (PROFILES / 'README.md').write_text(make_readme(all_md, is_test=False), encoding='utf-8')
        (PROFILES / '_sidebar.md').write_text(make_sidebar(all_md), encoding='utf-8')
        (PROFILES / '.nojekyll').write_text('', encoding='utf-8')
        print(f'✅ 完整版完成：{len(all_md)} 個衛星 profile')
        print(f'📁 目錄：{PROFILES.resolve()}')
        print()
        print('▶  啟動：')
        print(f'     cd "{PROFILES.resolve()}"')
        print(f'     python -m http.server 3000')
        print('🌐  http://localhost:3000')

    else:
        parser.print_help()
        print('\n提示：先用 --test 測試，確認後再 --full')


if __name__ == '__main__':
    main()
