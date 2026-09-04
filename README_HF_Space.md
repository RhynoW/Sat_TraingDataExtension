# 發布至 HuggingFace — 部署指南

`maneuver_app_2026September.py`(HF 相容版)+ `export_to_hf_parquet.py`(資料匯出)的完整流程。

## 結論(先看這段)

- **不要上傳 14GB 的 `space_db.duckdb`**。改成:資料放 **HF Dataset(Parquet)**、App 放 **HF Space(Streamlit)**,App 以 DuckDB `httpfs` **遠端直查**、不落地整庫。
- 核心表 `raw_tle_archive` 壓縮後約 **1.6GB**(原庫 13.8GB),`catalog.parquet` 約 **0.5MB**。
- 已實測:`WHERE norad_id=?` 靠全域排序 + row-group 統計裁剪,單筆點查 **~0.02s**。

---

## 一、匯出資料(本機執行一次)

```bash
# 只匯 App 需要的核心表(建議;最省)
python export_to_hf_parquet.py --out hf_export --core-only

# 或匯出整庫所有非空表(dataset 較完整,含 tle_table 60M 列,較久較大)
python export_to_hf_parquet.py --out hf_export
```

產出 `hf_export/`:

```
hf_export/
├─ raw_tle_archive/ … .parquet   # 全域排序(norad_id, epoch)、zstd;大表依 year 分割
├─ catalog.parquet               # 每顆衛星彙整(App 免全表 GROUP BY)
├─ sat_n2yo_metadata/ …          # (core-only 亦含)
├─ …其餘表
└─ README.md                     # dataset card
```

## 二、上傳 Dataset repo

```bash
pip install -U "huggingface_hub[hf_transfer]"
hf auth login
# PowerShell:  $env:HF_HUB_ENABLE_HF_TRANSFER = 1
export HF_HUB_ENABLE_HF_TRANSFER=1
hf upload-large-folder <帳號>/starlink-maneuver-db hf_export --repo-type=dataset --private
```

> `upload-large-folder` 支援斷點續傳、自動分批 commit,適合 GB 級多檔。

## 三、建立 Space(Streamlit)

Space repo 需包含:

- `maneuver_app_2026September.py`(設為 app 進入點,或建 `app.py` 匯入它)
- `requirements_hf.txt` → 更名/複製為 `requirements.txt`
- App 依賴的本機模組:`maneuver_strategies_july.py`、`statistical_detectors.py`、
  `data_quality_audit.py`、`constellation_anomaly.py`、`orbit_anomaly_detector.py`、
  `build_training_dataset.py`、`atmospheric_drag.py`、`ssa_rag_client.py`(選)等
- 模型目錄:`Orbital_Maneuver_V2/models_meme/`、`models_meme_anomaly/`、`models_fusion/`(選,缺則對應功能自動略過)
- 輔助資料:`data/`(url_registry、meme_truth、statistical_layer 等)、`f107_cache.csv`(選)

Space 的環境變數(Settings → Variables and secrets):

| 變數 | 值 | 說明 |
|---|---|---|
| `HF_DATASET_REPO` | `<帳號>/starlink-maneuver-db` | **設了即切遠端模式** |
| `HF_TOKEN` | (private repo 才需要) | 建持久化 DuckDB secret 讀 private dataset |
| `SSA_RAG_URL` | (選) | 外部 SSA-RAG 服務;不設則停用該功能 |

## 四、本機測試遠端模式

```bash
# PowerShell
$env:HF_DATASET_REPO = '<帳號>/starlink-maneuver-db'
streamlit run maneuver_app_2026September.py
```

未設 `HF_DATASET_REPO` 且本機有 `space_db.duckdb` → 行為與 August 版**完全相同**(直接讀本機全庫)。

---

## 運作原理

App 啟動時 `_bootstrap_db()`:

1. 若有 `HF_DATASET_REPO` → `INSTALL httpfs`、建立輕量 **stub DuckDB**(`space_hf.duckdb`),
   內含指向 `hf://datasets/<repo>/...parquet` 的 **VIEW**(僅存定義、不落地)。
2. `DB_PATH` 指向該 stub;App 與 `constellation_anomaly` / `orbit_anomaly_detector`
   都以 `read_only` 連線查同一顆 stub → **幾乎零改動沿用**。
3. 查詢時 httpfs 依 row-group 統計,只抓需要的 byte range。

## 注意事項

- **來源條款**:原始 TLE(Space-Track / CelesTrak 等)再散布可能有限制;公開前先確認,不確定就設 `--private`。
- **模型版本對齊**:`.pkl` 由特定 `scikit-learn` / `lightgbm` 版本序列化,`requirements` 已釘版,勿隨意升級。
- **冷啟動**:遠端首查需抓 parquet footer,略有延遲;結果經 `@st.cache_data` 快取,同衛星再查即命中。
