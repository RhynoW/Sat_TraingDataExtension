//! Conjunction & Maneuver Lab（第二階段 Sprint 1）：頁面與 API，路徑與 JSON 形狀同 Python api/lab.py。
//!
//! GET  /lab                 頁面
//! GET  /api/lab/demo        示範場景清單（含完整場景 JSON）
//! POST /api/lab/scenario    場景 JSON → 端到端報告
//! POST /api/lab/batch       主星＋次星清單（CSV 文字或陣列）→ 批次會合結果
//! POST /api/lab/batch.csv   {"events": [...]} → 結果 CSV（下載）
//! POST /api/lab/csv/parse   CSV 文字 → 解析結果與錯誤（前端預覽）
//!
//! EOP：資料目錄 DB\EOP-All.csv（或資料庫同目錄）存在時優先使用，否則用內嵌的凍結快照。

use std::path::{Path, PathBuf};
use std::sync::Arc;

use axum::body::{Body, Bytes};
use axum::extract::State;
use axum::http::{header, HeaderValue, Response, StatusCode};
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use once_cell::sync::OnceCell;
use serde_json::{json, Value};

use crate::phase2::{batch, csvio, e2e, eop::Eop};
use crate::state::AppState;

type St = State<Arc<AppState>>;
type Resp = Response<Body>;

const EOP_SNAPSHOT_NAME: &str = "eop_snapshot_20261118.csv";
const EOP_SNAPSHOT: &[u8] = include_bytes!("../config/phase2/testdata/eop_snapshot_20261118.csv");
const DEMOS: [&str; 3] = [
    include_str!("../config/phase2/testdata/e2e_leo_synthetic.json"),
    include_str!("../config/phase2/testdata/e2e_leo_propagated.json"),
    include_str!("../config/phase2/testdata/e2e_tle_iss_css.json"),
];

static EOP: OnceCell<Arc<Eop>> = OnceCell::new();

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/lab", get(|| async { crate::orbit_history::page("templates/lab.html") }))
        .route("/api/lab/demo", get(demo))
        .route("/api/lab/scenario", post(scenario))
        .route("/api/lab/batch", post(batch_api))
        .route("/api/lab/batch.csv", post(batch_csv))
        .route("/api/lab/csv/parse", post(csv_parse))
}

/// 執行期 EOP（與 Python default_eop 相同：程序內只載入一次）
fn default_eop(st: &AppState) -> Arc<Eop> {
    EOP.get_or_init(|| {
        let mut cands: Vec<PathBuf> = vec![st.cfg.home.join("DB").join("EOP-All.csv")];
        if let Some(dir) = st.cfg.resolve_db().and_then(|p| p.parent().map(Path::to_path_buf)) {
            cands.push(dir.join("EOP-All.csv"));
        }
        for p in cands.iter().filter(|p| p.is_file()) {
            match Eop::load(p) {
                Ok(e) => {
                    tracing::info!("Lab EOP：{}", p.display());
                    return Arc::new(e);
                }
                Err(e) => tracing::warn!("EOP 檔無法讀取（{}）：{e:#}，改用內嵌快照", p.display()),
            }
        }
        Arc::new(Eop::from_bytes(Path::new(EOP_SNAPSHOT_NAME), EOP_SNAPSHOT.to_vec()).expect("內嵌 EOP 快照"))
    })
    .clone()
}

fn json_status(v: Value, code: StatusCode) -> Resp {
    (code, Json(v)).into_response()
}

/// Flask get_json(silent=True)：無法解析時為 None
fn body_json(b: &Bytes) -> Option<Value> {
    serde_json::from_slice(b).ok()
}

/// 在阻塞執行緒執行；panic（例如星曆超出範圍）轉成 400 錯誤
async fn blocking<F>(f: F) -> Result<Value, String>
where
    F: FnOnce() -> anyhow::Result<Value> + Send + 'static,
{
    match tokio::task::spawn_blocking(f).await {
        Ok(Ok(v)) => Ok(v),
        Ok(Err(e)) => Err(format!("{e:#}")),
        Err(e) => Err(if e.is_panic() {
            let p = e.into_panic();
            p.downcast_ref::<String>().cloned().or_else(|| p.downcast_ref::<&str>().map(|s| s.to_string()))
                .unwrap_or_else(|| "計算失敗".into())
        } else {
            "計算中斷".into()
        }),
    }
}

async fn demo() -> Resp {
    let out: Vec<Value> = DEMOS.iter().map(|s| {
        let sc: Value = serde_json::from_str(s).expect("內嵌示範場景");
        json!({"id": sc["id"], "description": sc.get("description").cloned().unwrap_or(json!("")), "scenario": sc})
    }).collect();
    let mut r = Json(json!({"scenarios": out})).into_response();
    r.headers_mut().insert(header::CACHE_CONTROL, HeaderValue::from_static("public, max-age=3600"));
    r
}

async fn scenario(State(st): St, body: Bytes) -> Resp {
    let Some(sc) = body_json(&body).filter(Value::is_object) else {
        return json_status(json!({"status": "invalid_scenario",
            "validation": {"ok": false, "codes": ["E_SCHEMA"], "messages": ["需要 JSON 物件"]}}), StatusCode::BAD_REQUEST);
    };
    let eop = default_eop(&st);
    match blocking(move || e2e::run(&sc, &eop)).await {
        Ok(rep) => json_status(rep, StatusCode::OK),
        Err(e) => json_status(json!({"status": "error", "error": e}), StatusCode::BAD_REQUEST),
    }
}

async fn csv_parse(body: Bytes) -> Resp {
    let b = body_json(&body).unwrap_or(Value::Null);
    let text = match b.get("text") {
        None | Some(Value::Null) => String::new(),
        Some(Value::String(s)) => s.clone(),
        Some(other) => other.to_string(),
    };
    json_status(csvio::parse_secondaries(&text), StatusCode::OK)
}

async fn batch_api(State(st): St, body: Bytes) -> Resp {
    let b = body_json(&body).filter(Value::is_object).unwrap_or_else(|| json!({}));
    let (req, parsed) = match batch::prepare_request(&b) {
        Ok(x) => x,
        Err(e) => return json_status(e, StatusCode::BAD_REQUEST),
    };
    let eop = default_eop(&st);
    let idx = st.index();
    let res = blocking(move || {
        let lookup = |n: i64| {
            u32::try_from(n).ok().and_then(|k| idx.sats.get(&k)).map(|s| (s.name.clone(), s.line1.clone(), s.line2.clone()))
        };
        batch::run_batch(&req, &eop, &lookup)
    })
    .await;
    match res {
        Ok(mut rep) => {
            if let Some(p) = parsed {
                rep["csv"] = json!({"errors": p["errors"], "n_rows": p["rows"].as_array().map(Vec::len).unwrap_or(0)});
            }
            let code = if rep["status"] == "ok" { StatusCode::OK } else { StatusCode::BAD_REQUEST };
            json_status(rep, code)
        }
        Err(e) => json_status(json!({"status": "error", "error": e}), StatusCode::BAD_REQUEST),
    }
}

async fn batch_csv(body: Bytes) -> Resp {
    let b = body_json(&body).unwrap_or(Value::Null);
    let events = b.get("events").and_then(Value::as_array).cloned().unwrap_or_default();
    let text = format!("\u{feff}{}", csvio::events_to_csv(&events));
    let mut r = Response::new(Body::from(text));
    let h = r.headers_mut();
    h.insert(header::CONTENT_TYPE, HeaderValue::from_static("text/csv; charset=utf-8"));
    h.insert(header::CONTENT_DISPOSITION, HeaderValue::from_static("attachment; filename=conjunction_events.csv"));
    r
}
