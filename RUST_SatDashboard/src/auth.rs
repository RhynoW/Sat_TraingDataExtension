//! 帳號與權限（客戶回饋第 5 項）：本機帳號檔＋固定角色＋登入 session。
//!
//! - 帳號存在 <資料目錄>\user_private\accounts.json（密碼以 Argon2id 雜湊），不上傳、不對外。
//! - 尚未建立任何帳號 → 維持舊行為（不需登入）：本機（127.0.0.1）視為管理者，區網連線只能查詢。
//!   在「衛星管理」頁可由本機建立第一個管理者帳號；建立後所有頁面與 API 都須登入。
//! - 角色：viewer 檢視者（查詢）／editor 編輯者（查詢＋輸入、新增、修改）／admin 管理者（再加帳號管理、
//!   重抓星歷、重載設定、程式更新）。
//! - 忘記管理者密碼：關閉程式後刪除 accounts.json 即回到未設帳號狀態（群組與更名資料不受影響）。

use std::collections::HashMap;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

use argon2::password_hash::rand_core::{OsRng, RngCore};
use argon2::password_hash::{PasswordHash, PasswordHasher, PasswordVerifier, SaltString};
use argon2::Argon2;
use axum::extract::{ConnectInfo, Path, Request, State};
use axum::http::{header, HeaderValue, Method, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post, put};
use axum::{Extension, Json, Router};
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::state::AppState;

pub const COOKIE: &str = "sd_sid";
const SESSION_TTL: Duration = Duration::from_secs(12 * 3600);
const MAX_FAILS: u32 = 5;
const LOCK_SECS: u64 = 60;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Role {
    Viewer,
    Editor,
    Admin,
}

impl Role {
    pub fn parse(s: &str) -> Option<Role> {
        match s.trim().to_lowercase().as_str() {
            "viewer" | "檢視者" => Some(Role::Viewer),
            "editor" | "編輯者" => Some(Role::Editor),
            "admin" | "管理者" => Some(Role::Admin),
            _ => None,
        }
    }
    pub fn label(self) -> &'static str {
        match self {
            Role::Viewer => "檢視者",
            Role::Editor => "編輯者",
            Role::Admin => "管理者",
        }
    }
    /// 角色對應的權限（查詢／輸入／新增／修改／管理）
    pub fn perms(self) -> Vec<&'static str> {
        match self {
            Role::Viewer => vec!["query"],
            Role::Editor => vec!["query", "input", "create", "modify"],
            Role::Admin => vec!["query", "input", "create", "modify", "admin"],
        }
    }
}

/// 目前請求者（由 guard 放進 request extensions）
#[derive(Debug, Clone)]
pub struct Caller {
    pub user: Option<String>,
    pub role: Role,
}

impl Caller {
    pub fn name(&self) -> String {
        self.user.clone().unwrap_or_else(|| "本機".into())
    }
    pub fn can_edit(&self) -> bool {
        self.role >= Role::Editor
    }
    pub fn is_admin(&self) -> bool {
        self.role == Role::Admin
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub username: String,
    pub role: Role,
    pub hash: String,
    #[serde(default)]
    pub display: String,
    #[serde(default)]
    pub disabled: bool,
    #[serde(default)]
    pub created: String,
    #[serde(default)]
    pub last_login: String,
}

#[derive(Debug, Default, Serialize, Deserialize)]
struct UserFile {
    #[serde(default)]
    users: Vec<User>,
}

struct Session {
    user: String,
    exp: Instant,
}

pub struct Auth {
    path: PathBuf,
    users: Mutex<Vec<User>>,
    sessions: Mutex<HashMap<String, Session>>,
    fails: Mutex<HashMap<String, (u32, Instant)>>,
}

fn now_iso() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

pub fn hash_password(pw: &str) -> anyhow::Result<String> {
    let salt = SaltString::generate(&mut OsRng);
    Argon2::default()
        .hash_password(pw.as_bytes(), &salt)
        .map(|h| h.to_string())
        .map_err(|e| anyhow::anyhow!("密碼雜湊失敗：{e}"))
}

pub fn verify_password(pw: &str, hash: &str) -> bool {
    PasswordHash::new(hash)
        .map(|h| Argon2::default().verify_password(pw.as_bytes(), &h).is_ok())
        .unwrap_or(false)
}

fn new_token() -> String {
    let mut b = [0u8; 32];
    OsRng.fill_bytes(&mut b);
    b.iter().map(|x| format!("{x:02x}")).collect()
}

fn valid_username(u: &str) -> bool {
    let n = u.chars().count();
    (1..=32).contains(&n) && u.chars().all(|c| !c.is_whitespace() && !c.is_control() && !"/\\\"'<>&".contains(c))
}

/// 原子寫檔：先寫 .tmp 再改名；保留上一版為 .bak
pub fn atomic_write(path: &std::path::Path, data: &[u8]) -> anyhow::Result<()> {
    if let Some(d) = path.parent() {
        std::fs::create_dir_all(d)?;
    }
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, data)?;
    if path.exists() {
        let _ = std::fs::copy(path, path.with_extension("bak"));
    }
    std::fs::rename(&tmp, path)?;
    Ok(())
}

impl Auth {
    pub fn load(path: PathBuf) -> Self {
        let users = std::fs::read(&path)
            .ok()
            .and_then(|b| match serde_json::from_slice::<UserFile>(&b) {
                Ok(f) => Some(f.users),
                Err(e) => {
                    tracing::error!("帳號檔格式錯誤（{}）：{e}；為安全起見停用所有登入", path.display());
                    // 讀不到帳號但檔案存在：放一個無法登入的佔位帳號，避免退回「免登入」
                    Some(vec![User {
                        username: "\u{0}locked".into(),
                        role: Role::Viewer,
                        hash: String::new(),
                        display: String::new(),
                        disabled: true,
                        created: String::new(),
                        last_login: String::new(),
                    }])
                }
            })
            .unwrap_or_default();
        if !users.is_empty() {
            tracing::info!("已啟用帳號登入（{} 個帳號）", users.len());
        }
        Self {
            path,
            users: Mutex::new(users),
            sessions: Mutex::new(HashMap::new()),
            fails: Mutex::new(HashMap::new()),
        }
    }

    pub fn enabled(&self) -> bool {
        !self.users.lock().is_empty()
    }

    fn save(&self, users: &[User]) -> anyhow::Result<()> {
        let data = serde_json::to_vec_pretty(&json!({ "users": users }))?;
        atomic_write(&self.path, &data)
    }

    /// session 對應之有效帳號（滑動延長）
    pub fn session_user(&self, token: &str) -> Option<(String, Role)> {
        let mut ss = self.sessions.lock();
        let s = ss.get_mut(token)?;
        if s.exp < Instant::now() {
            ss.remove(token);
            return None;
        }
        let users = self.users.lock();
        let u = users.iter().find(|u| u.username == s.user && !u.disabled)?;
        s.exp = Instant::now() + SESSION_TTL;
        Some((u.username.clone(), u.role))
    }

    fn start_session(&self, user: &str) -> String {
        let t = new_token();
        let mut ss = self.sessions.lock();
        let now = Instant::now();
        ss.retain(|_, s| s.exp > now);
        ss.insert(t.clone(), Session { user: user.into(), exp: now + SESSION_TTL });
        t
    }

    fn end_sessions_of(&self, user: &str) {
        self.sessions.lock().retain(|_, s| s.user != user);
    }

    pub fn login(&self, username: &str, password: &str) -> Result<(String, Role), (StatusCode, String)> {
        let key = username.to_lowercase();
        if let Some((n, t)) = self.fails.lock().get(&key) {
            if *n >= MAX_FAILS && t.elapsed().as_secs() < LOCK_SECS {
                let wait = LOCK_SECS - t.elapsed().as_secs();
                return Err((StatusCode::TOO_MANY_REQUESTS, format!("登入失敗次數過多，請 {wait} 秒後再試")));
            }
        }
        let found = {
            let users = self.users.lock();
            users.iter().find(|u| u.username == username).cloned()
        };
        let ok = match &found {
            Some(u) => !u.disabled && verify_password(password, &u.hash),
            None => {
                // 帳號不存在也做一次雜湊，避免以回應時間猜帳號
                let _ = verify_password(password, "$argon2id$v=19$m=19456,t=2,p=1$c2FsdHNhbHQ$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA");
                false
            }
        };
        if !ok {
            let mut f = self.fails.lock();
            let e = f.entry(key).or_insert((0, Instant::now()));
            if e.1.elapsed().as_secs() >= LOCK_SECS {
                e.0 = 0;
            }
            e.0 += 1;
            e.1 = Instant::now();
            return Err((StatusCode::UNAUTHORIZED, "帳號或密碼錯誤".into()));
        }
        self.fails.lock().remove(&key);
        let u = found.unwrap();
        {
            let mut users = self.users.lock();
            if let Some(x) = users.iter_mut().find(|x| x.username == u.username) {
                x.last_login = now_iso();
            }
            let snapshot = users.clone();
            drop(users);
            let _ = self.save(&snapshot);
        }
        Ok((self.start_session(&u.username), u.role))
    }

    pub fn logout(&self, token: &str) {
        self.sessions.lock().remove(token);
    }

    pub fn list(&self) -> Vec<Value> {
        self.users
            .lock()
            .iter()
            .filter(|u| !u.username.starts_with('\u{0}'))
            .map(|u| {
                json!({
                    "username": u.username, "role": u.role, "role_label": u.role.label(),
                    "display": u.display, "disabled": u.disabled,
                    "created": u.created, "last_login": u.last_login, "perms": u.role.perms(),
                })
            })
            .collect()
    }

    fn active_admins(users: &[User]) -> usize {
        users.iter().filter(|u| u.role == Role::Admin && !u.disabled).count()
    }

    pub fn create(&self, username: &str, password: &str, role: Role, display: &str) -> Result<(), String> {
        if !valid_username(username) {
            return Err("帳號需 1–32 字元，不可含空白或 / \\ \" ' < > &".into());
        }
        if password.chars().count() < 8 {
            return Err("密碼至少 8 個字元".into());
        }
        let mut users = self.users.lock();
        if users.iter().any(|u| u.username.eq_ignore_ascii_case(username)) {
            return Err(format!("帳號 {username} 已存在"));
        }
        let hash = hash_password(password).map_err(|e| e.to_string())?;
        let mut next = users.clone();
        next.retain(|u| !u.username.starts_with('\u{0}'));
        next.push(User {
            username: username.into(),
            role,
            hash,
            display: display.trim().into(),
            disabled: false,
            created: now_iso(),
            last_login: String::new(),
        });
        self.save(&next).map_err(|e| format!("寫入帳號檔失敗：{e}"))?;
        *users = next;
        Ok(())
    }

    pub fn update(&self, username: &str, role: Option<Role>, disabled: Option<bool>, display: Option<String>, password: Option<String>) -> Result<(), String> {
        let mut users = self.users.lock();
        let mut next = users.clone();
        let Some(u) = next.iter_mut().find(|u| u.username == username) else {
            return Err(format!("找不到帳號 {username}"));
        };
        if let Some(r) = role {
            u.role = r;
        }
        if let Some(d) = disabled {
            u.disabled = d;
        }
        if let Some(d) = display {
            u.display = d.trim().into();
        }
        let pw_changed = password.is_some();
        if let Some(p) = password {
            if p.chars().count() < 8 {
                return Err("密碼至少 8 個字元".into());
            }
            u.hash = hash_password(&p).map_err(|e| e.to_string())?;
        }
        let kicked = u.disabled || pw_changed || role.is_some();
        if Self::active_admins(&next) == 0 {
            return Err("至少要保留一個啟用中的管理者".into());
        }
        self.save(&next).map_err(|e| format!("寫入帳號檔失敗：{e}"))?;
        *users = next;
        drop(users);
        if kicked {
            self.end_sessions_of(username);
        }
        Ok(())
    }

    pub fn delete(&self, username: &str) -> Result<(), String> {
        let mut users = self.users.lock();
        let mut next = users.clone();
        let before = next.len();
        next.retain(|u| u.username != username);
        if next.len() == before {
            return Err(format!("找不到帳號 {username}"));
        }
        if Self::active_admins(&next) == 0 {
            return Err("至少要保留一個啟用中的管理者".into());
        }
        self.save(&next).map_err(|e| format!("寫入帳號檔失敗：{e}"))?;
        *users = next;
        drop(users);
        self.end_sessions_of(username);
        Ok(())
    }

    pub fn check_password(&self, username: &str, pw: &str) -> bool {
        self.users
            .lock()
            .iter()
            .find(|u| u.username == username)
            .map(|u| verify_password(pw, &u.hash))
            .unwrap_or(false)
    }
}

// ── 中介層 ───────────────────────────────────────────────────────────────────

pub fn cookie_token(h: &axum::http::HeaderMap) -> Option<String> {
    h.get_all(header::COOKIE).iter().filter_map(|v| v.to_str().ok()).find_map(|v| {
        v.split(';').find_map(|kv| {
            let (k, val) = kv.trim().split_once('=')?;
            (k == COOKIE && !val.is_empty()).then(|| val.to_string())
        })
    })
}

fn is_public(path: &str) -> bool {
    const EXACT: [&str; 8] = [
        "/login", "/favicon.ico", "/api/logo", "/api/health", "/api/about",
        "/api/auth/login", "/api/auth/logout", "/api/auth/me",
    ];
    EXACT.contains(&path) || path == "/api/auth/setup" || path.starts_with("/static/") || path.starts_with("/cesium/")
}

fn admin_only(method: &Method, path: &str) -> bool {
    path.starts_with("/api/admin/")
        || path.starts_with("/api/auth/users")
        || path == "/api/ais/key"
        || (path.starts_with("/api/update/") && method != Method::GET)
        || (path.starts_with("/api/ephemeris/") && method != Method::GET)
}

fn json_err(status: StatusCode, msg: &str) -> Response {
    (status, Json(json!({"error": msg}))).into_response()
}

pub async fn guard(State(st): State<Arc<AppState>>, mut req: Request, next: Next) -> Response {
    let loopback = req
        .extensions()
        .get::<ConnectInfo<SocketAddr>>()
        .map(|c| c.0.ip().is_loopback())
        .unwrap_or(false);
    let path = req.uri().path().to_string();
    let enabled = st.auth.enabled();
    let caller = if !enabled {
        Some(Caller {
            user: None,
            role: if loopback { Role::Admin } else { Role::Viewer },
        })
    } else {
        cookie_token(req.headers())
            .and_then(|t| st.auth.session_user(&t))
            .map(|(u, r)| Caller { user: Some(u), role: r })
    };
    if caller.is_none() && !is_public(&path) {
        if path.starts_with("/api/") {
            return json_err(StatusCode::UNAUTHORIZED, "請先登入");
        }
        let q = req.uri().path_and_query().map(|p| p.as_str()).unwrap_or("/");
        let loc = format!("/login?next={}", urlencode(q));
        let mut r = StatusCode::SEE_OTHER.into_response();
        r.headers_mut().insert(header::LOCATION, HeaderValue::from_str(&loc).unwrap_or(HeaderValue::from_static("/login")));
        return r;
    }
    if admin_only(req.method(), &path) && !caller.as_ref().is_some_and(|c| c.is_admin()) {
        return json_err(StatusCode::FORBIDDEN, if enabled { "需要管理者權限" } else { "此操作只能在執行程式的那台電腦上進行" });
    }
    req.extensions_mut().insert(caller.unwrap_or(Caller { user: None, role: Role::Viewer }));
    next.run(req).await
}

fn urlencode(s: &str) -> String {
    s.bytes()
        .map(|b| match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' | b'/' => (b as char).to_string(),
            _ => format!("%{b:02X}"),
        })
        .collect()
}

// ── API ──────────────────────────────────────────────────────────────────────

type St = State<Arc<AppState>>;

pub fn extend(r: Router<Arc<AppState>>) -> Router<Arc<AppState>> {
    r.route("/login", get(page_login))
        .route("/api/auth/me", get(api_me))
        .route("/api/auth/login", post(api_login))
        .route("/api/auth/logout", post(api_logout))
        .route("/api/auth/setup", post(api_setup))
        .route("/api/auth/password", post(api_password))
        .route("/api/auth/users", get(api_users).post(api_user_create))
        .route("/api/auth/users/{name}", put(api_user_update).delete(api_user_delete))
}

async fn page_login() -> Response {
    let raw = crate::assets::get("ext/login.html").unwrap_or_default();
    axum::response::Html(String::from_utf8_lossy(&raw).into_owned()).into_response()
}

fn session_cookie(token: &str, max_age: u64) -> HeaderValue {
    HeaderValue::from_str(&format!("{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"))
        .unwrap_or(HeaderValue::from_static(""))
}

async fn api_me(State(st): St, ConnectInfo(a): ConnectInfo<SocketAddr>, req: Request) -> Response {
    let enabled = st.auth.enabled();
    let loopback = a.ip().is_loopback();
    if !enabled {
        let role = if loopback { Role::Admin } else { Role::Viewer };
        return Json(json!({
            "auth_enabled": false, "logged_in": false, "user": null,
            "role": role, "role_label": role.label(), "perms": role.perms(),
            "can_setup": loopback,
        }))
        .into_response();
    }
    match cookie_token(req.headers()).and_then(|t| st.auth.session_user(&t)) {
        Some((u, r)) => Json(json!({
            "auth_enabled": true, "logged_in": true, "user": u,
            "role": r, "role_label": r.label(), "perms": r.perms(), "can_setup": false,
        }))
        .into_response(),
        None => Json(json!({"auth_enabled": true, "logged_in": false, "user": null, "can_setup": false})).into_response(),
    }
}

#[derive(Deserialize)]
struct LoginReq {
    username: String,
    password: String,
}

async fn api_login(State(st): St, Json(b): Json<LoginReq>) -> Response {
    if !st.auth.enabled() {
        return json_err(StatusCode::BAD_REQUEST, "尚未建立帳號，不需登入");
    }
    let st2 = st.clone();
    let res = tokio::task::spawn_blocking(move || st2.auth.login(b.username.trim(), &b.password)).await;
    match res {
        Ok(Ok((tok, role))) => {
            let mut r = Json(json!({"ok": true, "role": role, "role_label": role.label()})).into_response();
            r.headers_mut().insert(header::SET_COOKIE, session_cookie(&tok, SESSION_TTL.as_secs()));
            r
        }
        Ok(Err((s, m))) => json_err(s, &m),
        Err(_) => json_err(StatusCode::INTERNAL_SERVER_ERROR, "登入處理失敗"),
    }
}

async fn api_logout(State(st): St, req: Request) -> Response {
    if let Some(t) = cookie_token(req.headers()) {
        st.auth.logout(&t);
    }
    let mut r = Json(json!({"ok": true})).into_response();
    r.headers_mut().insert(header::SET_COOKIE, session_cookie("", 0));
    r
}

#[derive(Deserialize)]
struct SetupReq {
    username: String,
    password: String,
    #[serde(default)]
    display: String,
}

/// 建立第一個管理者（僅限尚無帳號且由本機操作）
async fn api_setup(State(st): St, ConnectInfo(a): ConnectInfo<SocketAddr>, Json(b): Json<SetupReq>) -> Response {
    if !a.ip().is_loopback() {
        return json_err(StatusCode::FORBIDDEN, "第一個管理者只能在執行程式的那台電腦上建立");
    }
    if st.auth.enabled() {
        return json_err(StatusCode::CONFLICT, "已有帳號，請登入後由管理者新增");
    }
    let st2 = st.clone();
    let u = b.username.trim().to_string();
    let res = tokio::task::spawn_blocking(move || {
        st2.auth.create(&u, &b.password, Role::Admin, &b.display)?;
        st2.auth.login(&u, &b.password).map_err(|(_, m)| m)
    })
    .await;
    match res {
        Ok(Ok((tok, _))) => {
            st.satadmin.audit(&b.username, "建立第一個管理者", &b.username);
            let mut r = Json(json!({"ok": true})).into_response();
            r.headers_mut().insert(header::SET_COOKIE, session_cookie(&tok, SESSION_TTL.as_secs()));
            r
        }
        Ok(Err(m)) => json_err(StatusCode::BAD_REQUEST, &m),
        Err(_) => json_err(StatusCode::INTERNAL_SERVER_ERROR, "建立失敗"),
    }
}

#[derive(Deserialize)]
struct PwReq {
    old: String,
    new: String,
}

async fn api_password(State(st): St, Extension(c): Extension<Caller>, Json(b): Json<PwReq>) -> Response {
    let Some(u) = c.user.clone() else {
        return json_err(StatusCode::BAD_REQUEST, "尚未登入");
    };
    let st2 = st.clone();
    let res = tokio::task::spawn_blocking(move || {
        if !st2.auth.check_password(&u, &b.old) {
            return Err("舊密碼錯誤".to_string());
        }
        st2.auth.update(&u, None, None, None, Some(b.new))
    })
    .await;
    match res {
        Ok(Ok(())) => {
            st.satadmin.audit(&c.name(), "變更自己的密碼", "");
            Json(json!({"ok": true, "relogin": true})).into_response()
        }
        Ok(Err(m)) => json_err(StatusCode::BAD_REQUEST, &m),
        Err(_) => json_err(StatusCode::INTERNAL_SERVER_ERROR, "變更失敗"),
    }
}

async fn api_users(State(st): St) -> Json<Value> {
    Json(json!({"users": st.auth.list(), "auth_enabled": st.auth.enabled()}))
}

#[derive(Deserialize)]
struct UserReq {
    username: Option<String>,
    password: Option<String>,
    role: Option<String>,
    display: Option<String>,
    disabled: Option<bool>,
}

async fn api_user_create(State(st): St, Extension(c): Extension<Caller>, Json(b): Json<UserReq>) -> Response {
    let (Some(u), Some(p)) = (b.username.clone(), b.password.clone()) else {
        return json_err(StatusCode::BAD_REQUEST, "需要帳號與密碼");
    };
    let Some(role) = b.role.as_deref().map(Role::parse).unwrap_or(Some(Role::Viewer)) else {
        return json_err(StatusCode::BAD_REQUEST, "角色需為 viewer／editor／admin");
    };
    let st2 = st.clone();
    let u2 = u.trim().to_string();
    let disp = b.display.clone().unwrap_or_default();
    match tokio::task::spawn_blocking(move || st2.auth.create(&u2, &p, role, &disp)).await {
        Ok(Ok(())) => {
            st.satadmin.audit(&c.name(), "新增帳號", &format!("{} （{}）", u.trim(), role.label()));
            Json(json!({"ok": true})).into_response()
        }
        Ok(Err(m)) => json_err(StatusCode::BAD_REQUEST, &m),
        Err(_) => json_err(StatusCode::INTERNAL_SERVER_ERROR, "新增失敗"),
    }
}

async fn api_user_update(State(st): St, Extension(c): Extension<Caller>, Path(name): Path<String>, Json(b): Json<UserReq>) -> Response {
    let role = match b.role.as_deref() {
        None => None,
        Some(s) => match Role::parse(s) {
            Some(r) => Some(r),
            None => return json_err(StatusCode::BAD_REQUEST, "角色需為 viewer／editor／admin"),
        },
    };
    let mut what = Vec::new();
    if let Some(r) = role {
        what.push(format!("角色→{}", r.label()));
    }
    if let Some(d) = b.disabled {
        what.push(if d { "停用".into() } else { "啟用".into() });
    }
    if b.password.is_some() {
        what.push("重設密碼".into());
    }
    if b.display.is_some() {
        what.push("顯示名稱".into());
    }
    let st2 = st.clone();
    let n2 = name.clone();
    match tokio::task::spawn_blocking(move || st2.auth.update(&n2, role, b.disabled, b.display, b.password)).await {
        Ok(Ok(())) => {
            st.satadmin.audit(&c.name(), "修改帳號", &format!("{name}：{}", what.join("、")));
            Json(json!({"ok": true})).into_response()
        }
        Ok(Err(m)) => json_err(StatusCode::BAD_REQUEST, &m),
        Err(_) => json_err(StatusCode::INTERNAL_SERVER_ERROR, "修改失敗"),
    }
}

async fn api_user_delete(State(st): St, Extension(c): Extension<Caller>, Path(name): Path<String>) -> Response {
    if c.user.as_deref() == Some(name.as_str()) {
        return json_err(StatusCode::BAD_REQUEST, "不能刪除自己目前登入的帳號");
    }
    match st.auth.delete(&name) {
        Ok(()) => {
            st.satadmin.audit(&c.name(), "刪除帳號", &name);
            Json(json!({"ok": true})).into_response()
        }
        Err(m) => json_err(StatusCode::BAD_REQUEST, &m),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("sd_auth_{name}_{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        d.join("accounts.json")
    }

    #[test]
    fn roles_and_sessions() {
        let p = tmp("roles");
        let a = Auth::load(p.clone());
        assert!(!a.enabled());
        a.create("boss", "password1", Role::Admin, "").unwrap();
        assert!(a.enabled());
        assert!(a.create("BOSS", "password1", Role::Viewer, "").is_err(), "帳號不分大小寫重複");
        assert!(a.create("x y", "password1", Role::Viewer, "").is_err(), "空白");
        assert!(a.create("short", "1234567", Role::Viewer, "").is_err(), "密碼太短");
        a.create("ed", "password2", Role::Editor, "編輯").unwrap();
        // 重新載入：雜湊保存
        let a = Auth::load(p.clone());
        assert_eq!(a.list().len(), 2);
        let raw = std::fs::read_to_string(&p).unwrap();
        assert!(!raw.contains("password2") && raw.contains("$argon2id$"));
        let (tok, role) = a.login("ed", "password2").unwrap();
        assert_eq!(role, Role::Editor);
        assert_eq!(a.session_user(&tok).unwrap().1, Role::Editor);
        assert!(a.login("ed", "wrong").is_err());
        // 停用 → session 失效
        a.update("ed", None, Some(true), None, None).unwrap();
        assert!(a.session_user(&tok).is_none());
        assert!(a.login("ed", "password2").is_err());
        // 最後一個管理者不能降級／刪除
        assert!(a.update("boss", Some(Role::Viewer), None, None, None).is_err());
        assert!(a.delete("boss").is_err());
        // 鎖定
        for _ in 0..MAX_FAILS {
            let _ = a.login("boss", "nope");
        }
        assert_eq!(a.login("boss", "password1").unwrap_err().0, StatusCode::TOO_MANY_REQUESTS);
    }

    #[test]
    fn broken_file_locks_instead_of_opening() {
        let p = tmp("broken");
        std::fs::create_dir_all(p.parent().unwrap()).unwrap();
        std::fs::write(&p, b"{not json").unwrap();
        let a = Auth::load(p);
        assert!(a.enabled(), "壞檔不可退回免登入");
        assert!(a.list().is_empty());
    }

    #[test]
    fn cookie_parse_and_paths() {
        let mut h = axum::http::HeaderMap::new();
        h.insert(header::COOKIE, HeaderValue::from_static("a=1; sd_sid=abc; b=2"));
        assert_eq!(cookie_token(&h).as_deref(), Some("abc"));
        assert!(is_public("/static/js/x.js") && is_public("/login") && !is_public("/api/search"));
        assert!(admin_only(&Method::POST, "/api/update/app") && !admin_only(&Method::GET, "/api/update/status"));
        assert!(admin_only(&Method::GET, "/api/auth/users") && admin_only(&Method::POST, "/api/admin/reload_cats"));
    }
}
