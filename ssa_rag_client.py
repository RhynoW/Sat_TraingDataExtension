"""Standalone HTTP client for the SSA-RAG /ask API.

Self-contained on purpose (only stdlib + requests) so it can be copied into
another project — e.g. F:\\GitHub\\Sat_TraingDataExtension\\maneuver_app.py —
without pulling in the rest of the SSA-RAG package or its ML dependencies.

Usage:
    from ssa_rag_client import SSARAGClient, SUGGESTED_PROMPTS

    client = SSARAGClient()  # defaults to http://127.0.0.1:8000
    result = client.ask("CDM 的碰撞機率門檻是多少？", topic="cdm")
    print(result.answer, result.confidence)

Streamlit integration sketch:
    import streamlit as st
    from ssa_rag_client import SSARAGClient, SUGGESTED_PROMPTS, TOPICS

    client = SSARAGClient()
    topic = st.selectbox("主題", ["(全部)"] + TOPICS)
    prompt = st.selectbox("範例問題", SUGGESTED_PROMPTS.get(topic, ["(自訂輸入)"]))
    question = st.text_input("問題", value="" if prompt == "(自訂輸入)" else prompt)
    if st.button("送出") and question:
        result = client.ask(question, topic=None if topic == "(全部)" else topic)
        st.write(result.answer)
        st.caption(f"信心度：{result.confidence}")
        for s in result.sources:
            st.caption(f"來源：{s['file_name']} (chunk {s['chunk_index']})")
"""
from dataclasses import dataclass, field
from typing import Optional

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TIMEOUT = 60.0

# Must match app/core/metadata.py's topic rules.
TOPICS = [
    "sda", "cdm", "cola", "tle", "orbit", "od",
    "debris", "space_weather", "maneuver", "constellation", "general",
]

# Curated example questions per topic, for building a quick-select UI in a
# calling app (dropdown, chips, suggestion buttons, ...).
SUGGESTED_PROMPTS: dict[str, list[str]] = {
    "sda": [
        "什麼是 Space Object Catalog（太空物件目錄），常由哪些機構維護？",
        "SSA 和 SDA 有什麼差別？SDA 比 SSA 多涵蓋哪些維度？",
        "為什麼大型 LEO 星座對 SSA 系統構成挑戰？",
    ],
    "cdm": [
        "CDM 中哪個欄位代表碰撞機率（Pc）？",
        "Foster-1992 方法如何計算 Pc？",
        "COVARIANCE_METHOD = DEFAULT 為什麼需要特別小心？",
    ],
    "cola": [
        "COLA 機動的最晚截止時間（Hard Deadline）通常是 TCA 前多少小時？",
        "為什麼 along-track 方向的避碰機動比 radial 或 out-of-plane 更常用？",
        "主星若不可機動，COLA 流程應該如何處理？",
    ],
    "tle": [
        "BSTAR 代表什麼物理意義？它對 LEO 衛星有何重要性？",
        "SGP4 和 SDP4 的分界條件是什麼？",
        "TLE 資料齡對接近事件分析有什麼影響？",
    ],
    "orbit": [
        "Walker Delta 和 Walker Star 有什麼差別？分別適合哪種任務？",
        "什麼是墓地軌道？GEO 衛星為什麼需要它？",
        "太陽同步軌道（SSO）是如何利用地球扁率效應的？",
    ],
    "od": [
        "批次最小平方法和卡曼濾波在 OD 應用上各有什麼優缺點？",
        "追蹤弧段長度對軌道決定品質有什麼影響？",
        "為什麼碎片物件的 OD 品質通常比主衛星差？",
    ],
    "debris": [
        "Kessler Syndrome 的觸發條件是什麼？哪個高度帶最危險？",
        "IADC 的 25 年規則是如何推導出來的？",
        "鈍化（Passivation）包含哪些具體操作？為什麼它很重要？",
    ],
    "space_weather": [
        "F10.7 指數代表什麼？它如何影響 LEO 衛星的大氣阻力？",
        "地磁暴期間為什麼 CDM 的可信度可能下降？",
        "為什麼 SGP4 在強地磁暴後精度特別差？",
    ],
    "maneuver": [
        "TLE Jump 是什麼？如何從連續兩版 TLE 判斷是否發生機動？",
        "如何從 TLE 跳變估算 Δv 的大小？",
        "為什麼衛星機動後 TLE 會失效？這對 conjunction screening 有什麼影響？",
    ],
    "constellation": [
        "Walker 星座的 T/P/F 記法各代表什麼？",
        "大型 LEO 星座為什麼對 SSA 的 conjunction screening 能力構成挑戰？",
        "為什麼 500–600 km 是 LEO 通訊星座的常見甜蜜點？",
    ],
    "general": [
        "什麼是 conjunction screening？它的輸出是什麼？",
        "衛星機動對 TLE 和接近事件分析有什麼影響？",
    ],
}


@dataclass
class AskResult:
    answer: str
    confidence: str
    sources: list[dict] = field(default_factory=list)

    @property
    def insufficient(self) -> bool:
        """True if the answer signals insufficient evidence (sources will be empty)."""
        return not self.sources and "資料不足" in self.answer


class SSARAGClient:
    """Thin wrapper around the SSA-RAG FastAPI service.

    Requires the service to be running separately (``uvicorn app.main:app``).
    This client does not load any models itself.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: float = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> bool:
        """Return True if the SSA-RAG service is reachable and healthy."""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=5)
            return resp.ok and resp.json().get("status") == "ok"
        except requests.RequestException:
            return False

    def ask(
        self, question: str, topic: Optional[str] = None, client_id: Optional[str] = None
    ) -> AskResult:
        """Ask a question against the indexed SSA/aerospace documents.

        Args:
            question: The question text (any language the underlying LLM
                supports; the knowledge base and answers are Traditional
                Chinese).
            topic: Optional topic filter — one of TOPICS — to scope
                retrieval to a subset of the collection.
            client_id: Optional free-form tag identifying the calling
                program (e.g. "maneuver_app") so its requests are easy to
                pick out in the server-side QA log (logs/qa_log.jsonl on
                the SSA-RAG service).

        Raises:
            requests.HTTPError: on a non-2xx response from the service.
            requests.RequestException: on a connection/timeout failure.
        """
        payload = {"question": question}
        if topic:
            payload["topic"] = topic
        if client_id:
            payload["client_id"] = client_id
        resp = requests.post(f"{self.base_url}/ask", json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        return AskResult(
            answer=data["answer"],
            confidence=data["confidence"],
            sources=data.get("sources", []),
        )
