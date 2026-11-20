//! 太空小遊戲（僅單機版）：/games 頁面。
//!
//! 第一個遊戲「月球模擬」全部在瀏覽器端計算（astronomy-engine JS 版：月球星曆、月相、天平動、
//! 月出月沒、月食；射月球的地—月—日三體積分也在前端），後端只提供頁面。
//! 之後的碎片連鎖、星座壅擠等需要大量計算的遊戲，API 再加在這裡。

use std::sync::Arc;

use axum::{response::Html, routing::get, Router};

use crate::{assets, state::AppState};

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/games", get(page))
}

async fn page() -> Html<String> {
    let raw = assets::get("ext/games.html").unwrap_or_default();
    Html(String::from_utf8_lossy(&raw).replace("__BUILD__", env!("CARGO_PKG_VERSION")))
}
