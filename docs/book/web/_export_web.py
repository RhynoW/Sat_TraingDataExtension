"""把 v1.0 送審版全書匯出為線上閱讀用內容（data/book/），供 book_reader.py 讀取。

用法：python docs/book/web/_export_web.py
- 來源：docs/book/v1.0_送審版/全書_送審版_v1.3.md（已合併、已驗收的全書）
- 輸出：data/book/book.json、data/book/chapters/NN.md、data/book/img/…（圖片縮至寬 1,600 像素以內）
- 中央氣象署圖檔（img/cwa/）網站載明「非經授權禁止轉載」，線上版不轉載，改為連到原產品頁的說明。
- 延伸模擬篇 S1–S3（docs/book/sim_chapters/S*_初稿.md）排在第 21 章之後、附錄之前（與 _build_book.py --with-ext 相同），
  章號 S1–S3，圖片放在 data/book/img/ext/。
"""
import json
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
BOOK = ROOT / "docs" / "book" / "v1.0_送審版"
SRC = BOOK / "全書_送審版_v1.3.md"
OUT = ROOT / "data" / "book"
MAXW = 1600
EXT_DIR = ROOT / "docs" / "book" / "sim_chapters"
EXT_IDS = ["S1", "S2", "S3"]

TITLE = "從衛星軌道論國家安全"
SUBTITLE = "太空態勢感知的基礎：智慧化低軌通訊衛星軌道異常與太空事件偵測"
I18N_META = {
    "en": ("National Security from Satellite Orbits",
           "Foundations of Space Situational Awareness: Intelligent Detection of Orbital Anomalies and Space Events for LEO Communication Satellites",
           "Cover photo: NASA (iss036e024096), taken by Expedition 36 crew member Karen Nyberg aboard the International Space Station, 2013-07-22 16:44:23 UTC, Taiwan at night"),
    "ja": ("衛星軌道から考える国家安全保障",
           "宇宙状況把握の基礎：低軌道通信衛星の軌道異常と宇宙事象のインテリジェント検出",
           "表紙写真：NASA（iss036e024096）、国際宇宙ステーション第36次長期滞在クルー Karen Nyberg 撮影、2013-07-22 16:44:23 UTC、夜の台湾"),
}
META = {"author": "Sat_Dashboard", "version": "v1.3", "date": "2026.11.19", "copyright": "©Sat_Dashboard", "license": "請來信洽詢"}


def web_image(rel: str) -> str:
    """複製並縮小圖片到 data/book/img/，回傳相對 data/book/ 的路徑。"""
    src = EXT_DIR / "img" / rel[len("img/ext/"):] if rel.startswith("img/ext/") else BOOK / rel
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
    # 不整個刪除 OUT：翻譯時會有程式同時讀取 chapters/，Windows 下 rmtree 會中途失敗而留下殘缺目錄。
    # 改為直接覆寫；章節與圖片檔名固定，不會留下過期檔。
    (OUT / "chapters").mkdir(parents=True, exist_ok=True)
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
    for cid in EXT_IDS:                                            # 延伸模擬篇
        f = next(EXT_DIR.glob(f"{cid}_*_初稿.md"))
        p = f.read_text(encoding="utf-8").replace("](img/", "](img/ext/")
        title = p.split("\n", 1)[0][2:].strip()
        assert title.startswith(f"延伸篇 {cid}"), title
        (OUT / "chapters" / f"{cid}.md").write_text(convert(p), encoding="utf-8")
        toc.append({"id": cid, "title": title})
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
    # 譯文（docs/book/web/i18n/{en,ja}/NN.md，AI 輔助翻譯，中文原稿為準）
    i18n = {}
    for lang, (t, sub, cred) in I18N_META.items():
        src_dir = Path(__file__).resolve().parent / "i18n" / lang
        titles = {}
        for c in toc:
            f = src_dir / f"{c['id']}.md"
            if f.exists():
                (OUT / lang / "chapters").mkdir(parents=True, exist_ok=True)
                body = f.read_text(encoding="utf-8")
                (OUT / lang / "chapters" / f.name).write_text(body, encoding="utf-8")
                titles[c["id"]] = body.split("\n", 1)[0].lstrip("# ").strip()
        i18n[lang] = {"title": t, "subtitle": sub, "cover_credit": cred, "chapters": titles}
        print(f"{lang}: {len(titles)}/{len(toc)} chapters translated")
    json.dump({"title": TITLE, "subtitle": SUBTITLE, **META, "chapters": toc,
               "cover_credit": "封面照片：NASA（iss036e024096），國際太空站 Expedition 36 組員 Karen Nyberg 攝，2013-07-22 16:44:23 UTC，台灣夜間",
               "i18n": i18n},
              open(OUT / "book.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    n_img = sum(1 for _ in (OUT / "img").rglob("*.*"))
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"chapters {len(toc)}；images {n_img}；total {size / 1e6:.1f} MB → {OUT}")


if __name__ == "__main__":
    sys.exit(main())
