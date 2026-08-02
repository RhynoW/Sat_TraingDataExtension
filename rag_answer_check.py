"""SSA-RAG 回答的方向一致性檢查（Client 端後處理）。

背景：RAG 對負 Δa（半長軸下降）事件偶發「軌道抬升」誤判。Client 端需要一個
低誤報的自動旗標，供批次測試與 maneuver_app 自動解說時提示使用者。

規則演進：
  v1   全文掃描「軌道抬升」＋否定詞排除 —— 會誤觸「討論中提及但結論非抬升」的正確答案。
  v2   只檢查「結論句」：含結論性提示詞的句子與最後兩句。
  v3/  以否定「片語表」排除（不屬於／並未／不支援…）。三次實測各補一批詞
  v3.1 （47800「不屬於」、65424「並未」、26464「不支援」），仍持續漏接新變體。

  v4  （本版，結構化重寫）放棄「否定片語表」，改以句構判定：
      核心觀察 —— 中文否定「助詞」是封閉集合（不／未／非／無／沒／勿），
      而否定「片語」無限（不屬於、並未進行、不支援…）。故錨定
      「判定動詞前是否帶否定助詞」，一條規則即涵蓋所有片語變體。

      判定流程：對每個結論句，找出所有機動型別詞，逐一判斷該次提及是
        (a) 被否定   —— 前方近距離出現否定助詞      → 不算主張
        (b) 被主張   —— 前方近距離出現判定動詞      → 納入 verdict
        (c) 純敘述   —— 兩者皆無                    → 不計
      並區分兩種訊號（v3 以前混為一談）：
        sign_conflict     Δa<0 而「判定」就是軌道抬升        → 真實方向錯誤
        phrasing_warning  Δa<0，判定另有其詞，但結論句仍以
                          未否定方式（如括號註記）提及軌道抬升 → 措辭自相矛盾

用法：
    sign_conflict(answer, da_km) -> bool        # 方向矛盾（真錯）
    phrasing_warning(answer, da_km) -> bool     # 措辭矛盾（非真錯，較輕）
    verdict_types(answer) -> set[str]           # 結論主張的機動型別
"""
import re

# 句中出現這些詞才視為「結論句」
_CONCLUSION_CUES = (
    "最可能", "最有可能", "最合理", "因此", "所以", "綜合", "結論",
    "判定", "判斷為", "判為", "推測", "表明這是", "應為", "應該是",
)

# 機動型別詞彙（判定的「對象」）
_TYPES = (
    "軌道抬升", "軌道維持", "軌道降低", "離軌", "平面變換", "避碰",
    "資料異常", "大氣阻力", "站位保持", "軌道衰減",
)
TARGET = "軌道抬升"

# 判定動詞：其後接的型別詞即為主張
_VERDICT_VERBS = (
    "對應", "屬於", "判定為", "判斷為", "視為", "認定", "推測", "研判",
    "支援", "支持", "指向", "代表", "意味", "顯示", "表明", "符合", "反映",
    "執行", "進行", "是", "為",
)

# 否定助詞：封閉集合（相對於無限的否定片語）。作用域＝所在子句。
_NEG_PARTICLES = ("不", "未", "非", "無", "沒", "勿", "排除", "難以")

# 後綴反轉標記：型別詞「之後」才出現的否定/反轉語（前向掃描才抓得到）
#   52908「軌道抬升（OrbitRaising）的反向操作」、65261「軌道抬升之外的一種機動」
# 註：此為本模組唯一殘留的「片語表」。反轉語空間遠小於否定片語，但仍非封閉集合，
#     新變體需靠實測補（已知：反向／逆向／逆操作／之外／以外／相反）。
_POSTFIX_INVERT = ("之外", "以外", "反向", "逆向", "逆操作", "逆", "相反",
                   "相對", "而非", "反過來", "反面")

_SENT_SPLIT = re.compile(r"[。！？\n]+")
_PAREN = re.compile(r"[（(][^（）()]*[）)]")
_NORM = re.compile(r"[*_`\s]+")
# 子句邊界：不含「、」——它是並列項分隔（如「軌道維持、軌道抬升」），非子句邊界
_CLAUSE_SEP = "，,；;：:"
_POSTFIX_WINDOW = 10


def _normalize(text: str) -> str:
    """去除 markdown 強調與空白（如「這最可能是 **軌道抬升** 的結果」）。"""
    return _NORM.sub("", text)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]


def _conclusion_sentences(text: str) -> list[str]:
    sents = _sentences(text)
    if not sents:
        return []
    picked = [s for s in sents if any(c in s for c in _CONCLUSION_CUES)]
    for s in sents[-2:]:            # 最後兩句通常承載結論
        if s not in picked:
            picked.append(s)
    return picked


def _in_paren(sentence: str, pos: int) -> bool:
    """該次提及是否落在括號內（括號註記屬附帶說明，非判定本身）。"""
    return any(m.start() < pos < m.end() for m in _PAREN.finditer(sentence))


def _clause_span(s: str, pos: int) -> tuple[int, int]:
    """型別詞所在子句的 [起, 訖)。否定助詞的作用域以子句為界，
    避免固定字數回看搆不到（63523「沒有其他指標表明這是…軌道抬升」）。"""
    start = max((s.rfind(c, 0, pos) for c in _CLAUSE_SEP), default=-1)
    end_candidates = [i for i in (s.find(c, pos) for c in _CLAUSE_SEP) if i != -1]
    return start + 1, (min(end_candidates) if end_candidates else len(s))


def _classify_mentions(sentence: str) -> tuple[set, set]:
    """回傳 (被主張的型別, 被主張但僅出現於括號註記的型別)。

    同一句內每個型別「只看最後一次提及」——中文結論句常見
    「最可能是Ａ或Ｂ，但由於…，因此更有可能是Ａ而非Ｂ」的先並列後定案型態
    （53452），句尾立場才是該句對此型別的最終主張。
    """
    s = _normalize(sentence)
    asserted, gloss = set(), set()
    for t in _TYPES:
        hits = list(re.finditer(re.escape(t), s))
        if not hits:
            continue
        m = hits[-1]                                       # 最後一次提及定案
        c0, c1 = _clause_span(s, m.start())
        back = s[c0:m.start()]
        # 前向掃描先去括號：52908「軌道抬升（OrbitRaising）的反向操作」
        fwd = _PAREN.sub("", s[m.end():c1])[:_POSTFIX_WINDOW]
        if any(n in back for n in _NEG_PARTICLES):
            continue                                       # (a) 子句內被否定
        if any(p in fwd for p in _POSTFIX_INVERT):
            continue                                       # (a') 後綴反轉
        if not any(v in back for v in _VERDICT_VERBS):
            continue                                       # (c) 純敘述
        (gloss if _in_paren(s, m.start()) else asserted).add(t)        # (b) 被主張
    return asserted, gloss - asserted


def verdict_types(answer: str) -> set:
    """結論句中「被主張」的機動型別（不含括號註記、不含被否定者）。"""
    out = set()
    for s in _conclusion_sentences(answer):
        out |= _classify_mentions(s)[0]
    return out


def gloss_types(answer: str) -> set:
    """結論句中僅以括號註記方式提及、未被否定的型別。"""
    out = set()
    for s in _conclusion_sentences(answer):
        out |= _classify_mentions(s)[1]
    return out


def claims_raising_in_conclusion(answer: str) -> bool:
    """結論「判定」是否為軌道抬升。"""
    return TARGET in verdict_types(answer)


def sign_conflict(answer: str, da_km: float) -> bool:
    """Δa 為負但結論判定為軌道抬升 → 方向矛盾（真實錯誤）。"""
    return da_km < 0 and claims_raising_in_conclusion(answer)


def phrasing_warning(answer: str, da_km: float) -> bool:
    """Δa 為負、判定並非抬升，但結論句仍以未否定方式（多為括號註記）提及
    軌道抬升 —— 措辭自相矛盾，非方向判斷錯誤。"""
    if da_km >= 0 or claims_raising_in_conclusion(answer):
        return False
    return TARGET in gloss_types(answer)
