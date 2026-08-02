# ssa_rag_client — 外部專案整合說明

`ssa_rag_client.py` 是 SSA-RAG 的獨立 HTTP client，只依賴 `requests` + Python 標準庫，
**不需要**安裝 SSA-RAG 的任何套件（LangChain、chromadb、sentence-transformers 等）。
設計上就是讓你把這**一個檔案**複製到別的專案裡直接用。

---

## 前置條件

呼叫端不需要跑任何模型，但 **SSA-RAG 服務本身必須另外啟動並保持執行**：

```bash
# 在 SSA-RAG 專案目錄下（F:\GitHub\SSA-RAG）
ollama serve                      # 如果 Ollama 還沒啟動
uvicorn app.main:app --reload     # 啟動 SSA-RAG API，預設監聽 http://127.0.0.1:8000
```

確認服務正常：

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

---

## 安裝到你的專案

1. 把 `client/ssa_rag_client.py` 複製到你的專案裡（例如 `F:\GitHub\Sat_TraingDataExtension\ssa_rag_client.py`）。
2. 確認你的環境有 `requests`：

```bash
pip install requests
```

（如果你的專案已經有 `import requests`，例如 `maneuver_app.py`，這步可以跳過。）

---

## 快速開始

```python
from ssa_rag_client import SSARAGClient, SUGGESTED_PROMPTS, TOPICS

client = SSARAGClient()  # 預設連到 http://127.0.0.1:8000

# 健康檢查（服務沒啟動或連不到時回傳 False，不會丟例外）
if not client.health():
    print("SSA-RAG 服務未啟動")

# 提問（topic 可省略，省略時搜尋整個知識庫）
result = client.ask("CDM 的碰撞機率門檻是多少？", topic="cdm")
print(result.answer)
print(result.confidence)        # "high" | "medium" | "low"
print(result.sources)           # list[dict]，每筆含 source/file_name/chunk_index/score
print(result.insufficient)      # True 代表「資料不足，無法根據現有文件確認」
```

若服務不在同一台機器 / 不同 port，指定 `base_url`：

```python
client = SSARAGClient(base_url="http://192.168.1.50:8000", timeout=90)
```

---

## API 參考

### `SSARAGClient(base_url="http://127.0.0.1:8000", timeout=60.0)`

| 方法 | 說明 |
|---|---|
| `.health() -> bool` | 服務是否可連線且正常，連線失敗回傳 `False`，不拋例外 |
| `.ask(question: str, topic: str \| None = None, client_id: str \| None = None) -> AskResult` | 送出問題；`topic` 見下方 `TOPICS`；`client_id` 是任意字串標籤（例如 `"maneuver_app"`），用來在伺服器端的 QA log 裡辨識是哪個程式送出的請求 |

`.ask()` 在服務端出錯（HTTP 4xx/5xx）或連線逾時/失敗時，會拋出
`requests.exceptions.HTTPError` / `requests.exceptions.RequestException`，
呼叫端請自行 `try/except` 處理（常見情境：服務還沒啟動、模型還在載入中逾時）。

### `AskResult`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `answer` | `str` | 回答內容，**一律繁體中文** |
| `confidence` | `str` | `high` / `medium` / `low` |
| `sources` | `list[dict]` | 每筆含 `source`、`file_name`、`chunk_index`、`score` |
| `insufficient` | `bool`（唯讀） | `True` 代表證據不足，此時 `sources` 必為空 |

### `TOPICS`

```python
["sda", "cdm", "cola", "tle", "orbit", "od",
 "debris", "space_weather", "maneuver", "constellation", "general"]
```

對應 SSA-RAG 文件庫裡各文件的主題分類（依檔名推斷，見 SSA-RAG 專案的
`app/core/metadata.py`）。傳入 `topic` 可以把檢索範圍限縮到單一主題；不傳則搜尋全部。

### `SUGGESTED_PROMPTS`

```python
SUGGESTED_PROMPTS: dict[str, list[str]]
# 例如 SUGGESTED_PROMPTS["cdm"] → ["CDM 中哪個欄位代表碰撞機率（Pc）？", ...]
```

每個 topic 附 2–3 題精選範例問題，可直接拿來做下拉選單、快捷按鈕等 UI 元件，
不用自己想問題。

---

## 常見錯誤處理

```python
import requests

try:
    result = client.ask("什麼是 Kessler Syndrome？")
except requests.exceptions.ConnectionError:
    print("連不到 SSA-RAG 服務，請確認 uvicorn 有沒有啟動")
except requests.exceptions.Timeout:
    print("逾時——第一次呼叫要載入模型較久，可拉長 timeout 或稍後重試")
except requests.exceptions.HTTPError as e:
    print("服務端錯誤：", e)
```

**首次呼叫特別慢是正常的**：SSA-RAG 服務會在第一次 `/ask` 請求時才載入
embedding、reranker、LLM 三個模型（可能要 10–20 秒甚至更久），之後同一個
uvicorn process 內的請求就會快很多。建議 `timeout` 至少設 60 秒以上，
第一次呼叫甚至可以拉到 120 秒。

---

## Streamlit 整合完整範例

```python
import streamlit as st
from ssa_rag_client import SSARAGClient, SUGGESTED_PROMPTS, TOPICS

client = SSARAGClient()

st.subheader("SSA 知識庫問答")

if not client.health():
    st.error("SSA-RAG 服務未啟動，請先在 SSA-RAG 專案執行 `uvicorn app.main:app`")
else:
    topic = st.selectbox("主題篩選", ["(全部)"] + TOPICS)
    prompts = SUGGESTED_PROMPTS.get(topic, [])
    prompt = st.selectbox("範例問題（可略過，直接自訂輸入）", ["(自訂輸入)"] + prompts)
    question = st.text_input("問題", value="" if prompt == "(自訂輸入)" else prompt)

    if st.button("送出") and question:
        with st.spinner("查詢中…"):
            try:
                result = client.ask(question, topic=None if topic == "(全部)" else topic)
            except Exception as e:
                st.error(f"查詢失敗：{e}")
            else:
                st.write(result.answer)
                st.caption(f"信心度：{result.confidence}")
                if result.sources:
                    with st.expander(f"來源（{len(result.sources)}）"):
                        for s in result.sources:
                            st.caption(f"{s['file_name']}（chunk {s['chunk_index']}，score {s['score']:.3f}）")
```

---

## 已知限制

- 沒有身分驗證，服務預設對本機/區網開放。
- `/ask` 每次都跑完整檢索 + LLM 生成，沒有快取；同一問題重問會重新算一次。
- 回答語言固定為繁體中文（SSA-RAG 的 system prompt 已強制），問題本身可以用任何語言問。

---

## 除錯：QA 互動記錄

SSA-RAG 服務端會把每一次 `/ask` 的請求與回應記錄成一行 JSON，寫到服務端的
`logs/qa_log.jsonl`（`F:\GitHub\SSA-RAG\logs\qa_log.jsonl`），不需要呼叫端做
任何額外設定。每筆記錄包含：

```json
{
  "timestamp": "2026-07-02T08:15:30.123456+00:00",
  "client_id": "maneuver_app",
  "topic": "maneuver",
  "question": "...（呼叫端送出的完整問題字串）",
  "answer": "...（RAG 回傳的完整回答字串）",
  "confidence": "medium",
  "sources": [{"source": "...", "file_name": "...", "chunk_index": 3, "score": 0.123}],
  "insufficient": false,
  "latency_ms": 842.1
}
```

這在串接 `maneuver_app.py`（把機動偵測結果轉成自然語言問題、自動送進
`ssa_rag_client.py`）時特別有用：呼叫時帶上 `client_id="maneuver_app"`，
之後就可以直接翻 `qa_log.jsonl` 檢查自動產生的問題字串是否合理、
RAG 回答是否對題，藉此調整問題產生的措辭以提升正確性。此記錄檔為暫時性除錯
工具，非正式功能，之後可視需要移除或改造成正式的觀測機制。
