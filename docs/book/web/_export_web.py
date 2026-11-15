"""把 v1.0 送審版全書匯出為線上閱讀用內容（data/book/），供 book_reader.py 讀取。

用法：python docs/book/web/_export_web.py
- 來源：docs/book/v1.0_送審版/全書_送審版_v1.2.md（已合併、已驗收的全書）
- 輸出：data/book/book.json、data/book/chapters/NN.md、data/book/img/…（圖片縮至寬 1,600 像素以內）
- 中央氣象署圖檔（img/cwa/）網站載明「非經授權禁止轉載」，線上版不轉載，改為連到原產品頁的說明。
"""
import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
BOOK = ROOT / "docs" / "book" / "v1.0_送審版"
SRC = BOOK / "全書_送審版_v1.2.md"
OUT = ROOT / "data" / "book"
MAXW = 1600

TITLE = "從衛星軌道論國家安全"
SUBTITLE = "太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測"
META = {"author": "Sat_Dashboard", "version": "v1.2", "date": "2026.11.15", "copyright": "©Sat_Dashboard", "license": "請來信洽詢"}


def web_image(rel: str) -> str:
    """複製並縮小圖片到 data/book/img/，回傳相對 data/book/ 的路徑。"""
    src = BOOK / rel
    dst = OUT / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    if im.width > MAXW:
        im = im.resize((MAXW, round(im.height * MAXW / im.width)), Image.LANCZOS)
    if dst.suffix.lower() in (".jpg", ".jpeg"):
        im.convert("RGB").save(dst, quality=85, optimize=True)
    else:
        im.save(dst, optimize=True)
    return rel


def convert(md: str) -> str:
    md = re.sub(r"B\*(?!\*)", r"B\\*", md)                       # B* 不被當成斜體
    for _ in range(2):                                             # 證據方框各欄位分段
        md = re.sub(r"^(> \*\*[^\n]*)\n(?=> \*\*)", r"\1\n>\n", md, flags=re.M)
    md = re.sub(r"\\\[(.*?)\\\]", lambda m: "\n$$\n" + m.group(1).strip() + "\n$$\n", md, flags=re.S)
    md = re.sub(r"\\\((.*?)\\\)", lambda m: "$" + m.group(1).strip() + "$", md, flags=re.S)
    lines = md.split("\n")
    out, i = [], 0
    while i < len(lines):
        l = lines[i]
        m = re.match(r"^!\[([^\]]*)\]\((img/[^)]+)\)\s*$", l)
        if m and m.group(2).startswith("img/cwa/"):
            # 跳過圖片行與緊接的圖說（兩行），改為連結說明
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            cap = lines[j] if j < len(lines) else ""
            meta = lines[j + 1] if j + 1 < len(lines) else ""
            label = m.group(1)
            page = re.search(r"產品頁 (https?://\S+)", meta)
            first = cap.split("。")[0].replace(label + "　", "")
            out += [f"> **{label}（線上版未轉載）**　{first}。中央氣象署網站載明圖檔「非經授權禁止轉載」，請至原產品頁查看：{page.group(1) if page else 'https://swoo.cwa.gov.tw/'}", ""]
            i = j + 2
            continue
        if m:
            web_image(m.group(2))
        out.append(l)
        i += 1
    return "\n".join(out)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "chapters").mkdir(parents=True)
    text = SRC.read_text(encoding="utf-8")
    k = re.search(r"^# 附錄", text, re.M).start()
    body, appx = text[:k], text[k:]
    parts = [p for p in re.split(r"^(?=# 第 \d+ 章)", body, flags=re.M) if p.strip()]
    assert len(parts) == 21, len(parts)
    toc = []
    for n, p in enumerate(parts, 1):
        title = p.split("\n", 1)[0][2:].strip()
        (OUT / "chapters" / f"{n:02d}.md").write_text(convert(p), encoding="utf-8")
        toc.append({"id": f"{n:02d}", "title": title})
    for k, a in enumerate([x for x in re.split(r"^(?=# 附錄)", appx, flags=re.M) if x.strip()], 1):
        title = a.split("\n", 1)[0][2:].strip()
        (OUT / "chapters" / f"A{k}.md").write_text(convert(a), encoding="utf-8")
        toc.append({"id": f"A{k}", "title": title})
    # 封面照片（NASA iss036e024096）
    cov = ROOT / "docs" / "book" / "design" / "img" / "cover_mid.jpg"
    im = Image.open(cov)
    im = im.resize((MAXW, round(im.height * MAXW / im.width)), Image.LANCZOS)
    (OUT / "img").mkdir(exist_ok=True)
    im.convert("RGB").save(OUT / "img" / "cover.jpg", quality=85, optimize=True)
    json.dump({"title": TITLE, "subtitle": SUBTITLE, **META, "chapters": toc,
               "cover_credit": "封面照片：NASA（iss036e024096），國際太空站 Expedition 36 組員 Karen Nyberg 攝，2013-07-22 16:44:23 UTC，台灣夜間"},
              open(OUT / "book.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_img = sum(1 for _ in (OUT / "img").rglob("*.*"))
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"chapters {len(toc)}；images {n_img}；total {size / 1e6:.1f} MB → {OUT}")


if __name__ == "__main__":
    sys.exit(main())
