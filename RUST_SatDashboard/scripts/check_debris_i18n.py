"""檢查碎片連鎖的英文／日文字典（web/ext/games_debris_i18n.js）是否涵蓋所有介面文字。

抽出的字串：games_debris.js、games_debris_game.js 的中文字串常值（T() 模板與資料表），以及 games.html 中
#tab-debris 面板的文字節點與 title／placeholder。字典缺少的字串會列出來，請補上英文與日文（線上版 /game 使用）。

用法（在 RUST_SatDashboard 目錄）：py -3.13 scripts/check_debris_i18n.py
"""

import io, json, re, sys
from html.parser import HTMLParser

EXT = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "web" / "ext")
CJK = re.compile(r'[一-鿿]')
keys = []


def add(k):
    k = k.strip() if not k.startswith(' ') else k
    if k and CJK.search(k) and k not in keys:
        keys.append(k)


def js_strings(src):
    """JS 字串常值，相鄰以 + 串接的合併成一個（KIND 這類）。"""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == '/' and src[i:i + 2] == '//':
            j = src.find('\n', i); i = n if j < 0 else j; continue
        if c == '/' and src[i:i + 2] == '/*':
            j = src.find('*/', i); i = n if j < 0 else j + 2; continue
        if c in '"\'':
            parts = []
            while True:
                q = src[i]; j = i + 1; buf = []
                while src[j] != q:
                    if src[j] == '\\':
                        buf.append(src[j:j + 2]); j += 2; continue
                    buf.append(src[j]); j += 1
                parts.append(''.join(buf))
                k = j + 1
                m = re.match(r'\s*\+\s*', src[k:])
                if m and k + m.end() < n and src[k + m.end()] in '"\'':
                    i = k + m.end(); continue
                i = k; break
            out.append(''.join(parts))
            continue
        i += 1
    return out


for f in ('games_debris.js', 'games_debris_game.js'):
    src = io.open(EXT + '/' + f, encoding='utf-8').read()
    for s in js_strings(src):
        s = s.replace('\\"', '"').replace("\\'", "'")
        if '{0}' in s or not re.search(r"<(td|tr|div|span|table|svg|text|rect|polyline|label|input|select|option)[ >]", s):
            add(s)

html = io.open(EXT + '/games.html', encoding='utf-8').read()
a = html.index('<div id="tab-debris"')
b = html.index('<div id="tab-asat"')
panel = html[a:b]


class P(HTMLParser):
    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ('title', 'placeholder') and v:
                add(v)

    def handle_data(self, d):
        if d.strip():
            add(d.strip())


P().feed(panel)
for k in ('有效載荷', '火箭體', '碎片', '其他'):
    add(k)
js = io.open(EXT + '/games_debris_i18n.js', encoding='utf-8').read()
missing = {}
for lang in ('en', 'ja'):
    blk = js[js.index('  ' + lang + ': {'):]
    blk = blk[:blk.index('\n  },')]
    have = set(json.loads(m) for m in re.findall(r'^    ("(?:[^"\\]|\\.)*"): ', blk, re.M))
    missing[lang] = [k for k in keys if k not in have]
for lang, ks in missing.items():
    print(f"{lang}：缺 {len(ks)} 個" + ("" if not ks else "\n  " + "\n  ".join(ks)))
sys.exit(1 if any(missing.values()) else 0)
