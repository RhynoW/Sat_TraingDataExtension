"""逐章比對譯文與中文原稿：圖片行、URL、數學式、上標、標題數、Case 編號、多位數數字。
用法：python docs/book/web/i18n/_verify_i18n.py en 01 02 …（不帶章號則檢查該語言全部已存在的檔案）"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "data" / "book" / "chapters"
lang = sys.argv[1]
OUT = Path(__file__).resolve().parent / lang
ids = sys.argv[2:] or sorted(p.stem for p in OUT.glob("*.md"))
URL = re.compile(r"https?://[^\s<>\"'　-〿一-鿿＀-￯]+")
PREFIX = {"en": "**Sidebar: ", "ja": "**コラム："}[lang]


def nums(s):
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)
    toks = re.findall(r"\d[\d,]*(?:\.\d+)?", s)
    return {t.replace(",", "") for t in toks if len(t.replace(",", "").split(".")[0]) >= 2 and not (t.isdigit() and int(t) <= 31)}


bad = 0
for cid in ids:
    a = (SRC / f"{cid}.md").read_text(encoding="utf-8")
    p = OUT / f"{cid}.md"
    if not p.exists():
        print(f"MISSING {lang}/{cid}.md")
        bad += 1
        continue
    b = p.read_text(encoding="utf-8")
    issues = []
    ia = re.findall(r"^!\[.*$", a, re.M); ib = re.findall(r"^!\[.*$", b, re.M)
    if ia != ib:
        issues.append(f"圖片行不同 {len(ia)}→{len(ib)}")
    ua = sorted(u.rstrip(".,;:") for u in URL.findall(a)); ub = sorted(u.rstrip(".,;:") for u in URL.findall(b))
    if ua != ub:
        issues.append(f"URL 不同：缺 {sorted(set(ua) - set(ub))[:3]} 多 {sorted(set(ub) - set(ua))[:3]}")
    if a.count("$$") != b.count("$$") or a.count("$") != b.count("$"):
        issues.append(f"數學符號 $ 數不同 {a.count('$')}→{b.count('$')}")
    sa = len(re.findall(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]", a)); sb = len(re.findall(r"[¹²³⁴⁵⁶⁷⁸⁹⁰]", b))
    if sa != sb:
        issues.append(f"上標數不同 {sa}→{sb}")
    ha = [len(m) for m in re.findall(r"^(#+) ", a, re.M)]; hb = [len(m) for m in re.findall(r"^(#+) ", b, re.M)]
    if ha != hb:
        issues.append(f"標題結構不同 {len(ha)}→{len(hb)}")
    ca = sorted(set(re.findall(r"Case \d+", a))); cb = sorted(set(re.findall(r"Case \d+", b)))
    if ca != cb:
        issues.append(f"Case 編號不同：缺 {sorted(set(ca) - set(cb))} 多 {sorted(set(cb) - set(ca))}")
    asides = a.count("**插敘：")
    if b.count(PREFIX) != asides:
        issues.append(f"插敘前綴 {PREFIX!r} 數 {asides}→{b.count(PREFIX)}")
    miss = sorted(nums(a) - nums(b))
    if miss:
        issues.append(f"數字缺漏 {len(miss)}：{miss[:12]}")
    if re.search(r"[一-鿿]{6,}", b) and lang == "en":
        n = len(re.findall(r"[一-鿿]{6,}", b))
        issues.append(f"英文版殘留中文片段 {n} 處（參考文獻原標題可接受，請確認）")
    bad += bool([i for i in issues if not i.startswith("英文版殘留")])
    print(("OK  " if not issues else "CHK ") + f"{lang}/{cid}", "；".join(issues))
print("ALL OK" if not bad else f"{bad} 檔需處理")
