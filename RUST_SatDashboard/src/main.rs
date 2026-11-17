//! ATRDC SatDashboard — Rust 單機版（Windows x86_64 / ARM64）
//!
//! 單一執行檔：內嵌前端（CesiumJS 3D 地球）+ axum 後端 + DuckDB 讀取 + 平行 SGP4。
//! 啟動後自動開啟瀏覽器；關閉主控台視窗或按 Ctrl+C 結束。

mod about;
mod api;
mod api_phase2;
mod assets;
mod classify;
mod config;
mod coverage;
mod index;
mod lunar;
mod mission;
mod orbit_history;
mod physics;
mod rpo;
mod state;
mod tiles;
mod update;
mod userdata;

use std::net::SocketAddr;

use tower_http::cors::{Any, CorsLayer};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_env("LOG_LEVEL").unwrap_or_else(|_| EnvFilter::new("info")))
        .with_target(false)
        .with_ansi(std::io::IsTerminal::is_terminal(&std::io::stdout()))
        .init();

    let cfg = config::Config::from_args()?;
    println!("══════════════════════════════════════════════════════");
    println!(
        " ATRDC SatDashboard — Rust 單機版 v{}（版本日期 {}，{}）",
        about::VERSION,
        about::BUILD_DATE,
        std::env::consts::ARCH
    );
    println!(" 聯絡：{}（LinkedIn）{}", about::CONTACT_NAME, about::CONTACT_URL);
    println!("══════════════════════════════════════════════════════");
    tracing::info!("資料目錄：{}", cfg.home.display());
    match cfg.resolve_db() {
        Some(db) => tracing::info!("資料庫：{}", db.display()),
        None => {
            tracing::warn!("找不到資料庫：請以 --db 指定，或將 space_db_slim.duckdb 放到 <資料目錄>\\DB\\")
        }
    }

    update::cleanup_old_exe();
    let state = state::AppState::new(cfg.clone());
    {
        let st = state.clone();
        tokio::task::spawn_blocking(move || st.rebuild_index_now()).await?;
    }

    update::spawn_auto_check(state.clone());
    let app = api::router(state).layer(CorsLayer::new().allow_origin(Any));

    // 埠被占用時往後找
    let host: std::net::IpAddr = cfg.host.parse()?;
    let mut listener = None;
    if let Some(pid) = cfg.restart_wait {
        // 線上更新後的重新啟動：等舊程式結束、釋出原埠（最多 15 秒）
        tracing::info!("等待舊版程式（PID {pid}）結束…");
        for _ in 0..60 {
            if let Ok(l) = tokio::net::TcpListener::bind(SocketAddr::new(host, cfg.port)).await {
                listener = Some(l);
                break;
            }
            tokio::time::sleep(std::time::Duration::from_millis(250)).await;
        }
    }
    for p in cfg.port..cfg.port.saturating_add(20) {
        if listener.is_some() {
            break;
        }
        if let Ok(l) = tokio::net::TcpListener::bind(SocketAddr::new(host, p)).await {
            listener = Some(l);
            break;
        }
    }
    let listener = listener.ok_or_else(|| anyhow::anyhow!("埠 {}–{} 皆被占用", cfg.port, cfg.port + 19))?;
    let addr = listener.local_addr()?;
    let shown = if host.is_unspecified() {
        "127.0.0.1".to_string()
    } else {
        addr.ip().to_string()
    };
    let url = format!("http://{shown}:{}/", addr.port());
    println!("\n  ▶ 儀表板網址：{url}");
    println!("  （關閉此視窗或按 Ctrl+C 結束）\n");
    if cfg.open_browser {
        if let Err(e) = open::that_detached(&url) {
            tracing::warn!("無法自動開啟瀏覽器：{e}");
        }
    }

    axum::serve(listener, app.into_make_service_with_connect_info::<SocketAddr>())
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
            tracing::info!("收到結束訊號，關閉中…");
        })
        .await?;
    Ok(())
}
