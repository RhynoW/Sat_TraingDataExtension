//! RPO 場景：以歷史 TLE 重建兩顆衛星之相對接近幾何 + Chan Pc（排序代理）。
//! 對應 Python physics/rpo.py；案例預設由 scripts/sync_web.py 匯出為 config/rpo_presets.json。

use std::collections::HashMap;
use std::path::Path;

use chrono::{DateTime, Duration, NaiveDate, NaiveDateTime, Utc};
use once_cell::sync::Lazy;
use serde_json::{json, Value};

use crate::config::{Config, RAW_TABLE};
use crate::index::open_ro;
use crate::physics::{compute_pc_chan, eci_to_llh, gmst_rad, round_to, Propagator};

pub const DEFAULT_PRIMARY: u32 = 58573;
pub const DEFAULT_SECONDARY: u32 = 59884;
const SIGMA_N_KM: f64 = 0.1;

static PRESETS: Lazy<Value> = Lazy::new(|| {
    serde_json::from_str(include_str!("../config/rpo_presets.json")).expect("rpo_presets.json 格式錯誤")
});

fn key(p: u32, s: u32) -> String {
    format!("{p}_{s}")
}

pub fn preset_for(p: u32, s: u32, variant: Option<&str>) -> Value {
    if let Some(v) = variant {
        if let Some(x) = PRESETS["variants"].get(key(p, s)).and_then(|m| m.get(v)) {
            return x.clone();
        }
    }
    PRESETS["presets"]
        .get(key(p, s))
        .cloned()
        .unwrap_or_else(|| json!({}))
}

/// 檔案快取的說明文字（標題、事件、時間軸）改用目前的案例預設：修改文字後不必刪快取重算
pub fn refresh_meta(data: &mut Value, preset: &Value) {
    let Some(meta) = data.get_mut("meta").and_then(|m| m.as_object_mut()) else { return };
    for k in ["title", "subtitle", "events", "timeline", "phases"] {
        if let Some(x) = preset.get(k) {
            meta.insert(k.to_string(), x.clone());
        }
    }
}

pub fn valid_variant(p: u32, s: u32, variant: Option<&str>) -> Option<String> {
    let v = variant?;
    PRESETS["variants"].get(key(p, s))?.get(v).map(|_| v.to_string())
}

fn split_key(k: &str) -> (u32, u32) {
    let mut it = k.split('_').map(|x| x.parse().unwrap_or(0));
    (it.next().unwrap_or(0), it.next().unwrap_or(0))
}

pub fn presets_list() -> Value {
    let mut out = Vec::new();
    if let Some(m) = PRESETS["presets"].as_object() {
        for (k, info) in m {
            let (p, s) = split_key(k);
            out.push(json!({"primary": p, "secondary": s,
                            "title": info.get("title").cloned().unwrap_or_else(|| json!(format!("{p} × {s}")))}));
        }
    }
    if let Some(m) = PRESETS["variants"].as_object() {
        for (k, vs) in m {
            let (p, s) = split_key(k);
            for (v, info) in vs.as_object().into_iter().flatten() {
                out.push(json!({"primary": p, "secondary": s, "variant": v,
                                "title": info.get("title").cloned().unwrap_or_else(|| json!(format!("{p} × {s} ({v})")))}));
            }
        }
    }
    json!({"presets": out})
}

/// 解析 "2024-03-01" / "2024-05-16T20:10Z" / "...T20:10:00Z" / 含 +00:00
pub fn parse_time(s: &str) -> Option<DateTime<Utc>> {
    let s = s.trim();
    if let Ok(t) = DateTime::parse_from_rfc3339(s) {
        return Some(t.with_timezone(&Utc));
    }
    let body = s.trim_end_matches('Z');
    for f in ["%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"] {
        if let Ok(t) = NaiveDateTime::parse_from_str(body, f) {
            return Some(t.and_utc());
        }
    }
    NaiveDate::parse_from_str(body, "%Y-%m-%d")
        .ok()
        .map(|d| d.and_hms_opt(0, 0, 0).unwrap().and_utc())
}

fn iso_z(t: &DateTime<Utc>) -> String {
    let s = t.to_rfc3339_opts(chrono::SecondsFormat::AutoSi, true);
    s
}

struct Recs {
    props: Vec<Propagator>,
    epochs: Vec<f64>, // unix 秒
    lo: DateTime<Utc>,
    hi: DateTime<Utc>,
}

impl Recs {
    /// 以 epoch 最接近 t 之 elset 傳播（同 Python np.argmin(|ep - t|)）
    fn prop(&self, t: &DateTime<Utc>) -> Option<[f64; 3]> {
        let x = t.timestamp() as f64 + t.timestamp_subsec_micros() as f64 * 1e-6;
        let i = self.epochs.partition_point(|e| *e < x);
        let j = if i == 0 {
            0
        } else if i >= self.epochs.len() {
            self.epochs.len() - 1
        } else if (self.epochs[i] - x).abs() < (x - self.epochs[i - 1]).abs() {
            i
        } else {
            i - 1
        };
        self.props[j].position(t)
    }
}

fn load_recs(
    db: &Path,
    nid: u32,
    window: Option<(DateTime<Utc>, DateTime<Utc>)>,
    exclude: &[(DateTime<Utc>, DateTime<Utc>)],
) -> anyhow::Result<Option<(Recs, Option<String>)>> {
    let con = open_ro(db)?;
    let cols: Vec<String> = {
        let mut st = con.prepare(&format!(
            "SELECT column_name FROM information_schema.columns WHERE table_name='{RAW_TABLE}'"
        ))?;
        let v = st
            .query_map([], |r| r.get::<_, String>(0))?
            .collect::<Result<Vec<_>, _>>()?;
        v
    };
    let has = |c: &str| cols.iter().any(|x| x == c);
    let has_tle = has("line1") && has("line2");
    let elem_cols = [
        "eccentricity",
        "inclination_deg",
        "raan_deg",
        "argp_deg",
        "mean_anomaly_deg",
        "mean_motion",
    ];
    let has_elem = elem_cols.iter().all(|c| has(c));
    if !has_tle && !has_elem {
        anyhow::bail!("raw_tle_archive 既無 line1/line2、亦無平均根數欄位，無法傳播");
    }
    let name_sel = if has("object_name") { "object_name" } else { "NULL" };
    let tle_sel = if has_tle { "line1, line2" } else { "NULL, NULL" };
    let elem_sel = if has_elem {
        format!(
            "{}, {}",
            elem_cols.join(", "),
            if has("bstar") { "bstar" } else { "0.0" }
        )
    } else {
        "NULL, NULL, NULL, NULL, NULL, NULL, NULL".into()
    };
    let mut where_ = format!("norad_id = {nid}");
    if let Some((a, b)) = window {
        where_ += &format!(
            " AND epoch_utc >= TIMESTAMP '{}' AND epoch_utc <= TIMESTAMP '{}'",
            a.format("%Y-%m-%d %H:%M:%S%.6f"),
            b.format("%Y-%m-%d %H:%M:%S%.6f")
        );
    }
    let sql = format!(
        "SELECT epoch_us(epoch_utc), {name_sel}, {tle_sel}, {elem_sel}
         FROM {RAW_TABLE} WHERE {where_} ORDER BY epoch_utc"
    );
    let mut st = con.prepare(&sql)?;
    #[allow(clippy::type_complexity)]
    let rows: Vec<(
        i64,
        Option<String>,
        Option<String>,
        Option<String>,
        [Option<f64>; 7],
    )> = st
        .query_map([], |r| {
            Ok((
                r.get(0)?,
                r.get(1)?,
                r.get(2)?,
                r.get(3)?,
                [
                    r.get(4)?,
                    r.get(5)?,
                    r.get(6)?,
                    r.get(7)?,
                    r.get(8)?,
                    r.get(9)?,
                    r.get(10)?,
                ],
            ))
        })?
        .collect::<Result<_, _>>()?;

    let mut props = Vec::new();
    let mut epochs = Vec::new();
    let mut last_ep: Option<i64> = None;
    let mut name = None;
    for (us, nm, l1, l2, el) in rows {
        if last_ep == Some(us) {
            continue; // drop_duplicates("epoch_utc")
        }
        last_ep = Some(us);
        let Some(t) = DateTime::from_timestamp_micros(us) else {
            continue;
        };
        if exclude.iter().any(|(a, b)| t >= *a && t <= *b) {
            continue;
        }
        if let Some(n) = nm {
            name = Some(n.trim().trim_start_matches("0 ").trim().to_string());
        }
        let p = match (&l1, &l2) {
            (Some(a), Some(b)) => Propagator::from_tle(a, b),
            _ => match el {
                [Some(e), Some(i), Some(ra), Some(ap), Some(ma), Some(mm), bs] => {
                    Propagator::from_elements(t.naive_utc(), e, i, ra, ap, ma, mm, bs.unwrap_or(0.0))
                }
                _ => None,
            },
        };
        if let Some(p) = p {
            props.push(p);
            epochs.push(us as f64 * 1e-6);
        }
    }
    if props.is_empty() {
        return Ok(None);
    }
    let lo = DateTime::from_timestamp_micros((epochs[0] * 1e6) as i64).unwrap();
    let hi = DateTime::from_timestamp_micros((epochs[epochs.len() - 1] * 1e6) as i64).unwrap();
    Ok(Some((
        Recs {
            props,
            epochs,
            lo,
            hi,
        },
        name,
    )))
}

struct Sample {
    t: DateTime<Utc>,
    rp: [f64; 3],
    rs: [f64; 3],
    d: f64,
}

fn sample(p: &Recs, s: &Recs, t0: DateTime<Utc>, t1: DateTime<Utc>, step_s: f64) -> Vec<Sample> {
    let n = ((t1 - t0).num_milliseconds() as f64 / 1000.0 / step_s).floor() as i64 + 1;
    (0..n.max(0))
        .filter_map(|k| {
            let t = t0 + Duration::milliseconds((k as f64 * step_s * 1000.0) as i64);
            let rp = p.prop(&t)?;
            let rs = s.prop(&t)?;
            let d = ((rs[0] - rp[0]).powi(2) + (rs[1] - rp[1]).powi(2) + (rs[2] - rp[2]).powi(2)).sqrt();
            d.is_finite().then_some(Sample { t, rp, rs, d })
        })
        .collect()
}

fn pick_focus_center(
    preset: &Value,
    coarse: &[Sample],
    lo: DateTime<Utc>,
    hi: DateTime<Utc>,
) -> DateTime<Utc> {
    let events = preset
        .get("events")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut cand = preset
        .get("focus_center")
        .and_then(Value::as_str)
        .map(str::to_string);
    if cand.is_none() {
        cand = events
            .iter()
            .find(|e| e["label"].as_str().unwrap_or("").to_uppercase().contains("TCA"))
            .and_then(|e| e["t"].as_str().map(str::to_string));
    }
    if cand.is_none() {
        cand = events.last().and_then(|e| e["t"].as_str().map(str::to_string));
    }
    if let Some(t) = cand.as_deref().and_then(parse_time) {
        if lo <= t && t <= hi {
            return t;
        }
    }
    coarse
        .iter()
        .min_by(|a, b| a.d.total_cmp(&b.d))
        .map(|c| c.t)
        .unwrap()
}

/// np.gradient（中央差分、端點單側差分）
fn gradient(v: &[[f64; 3]]) -> Vec<[f64; 3]> {
    let n = v.len();
    if n < 2 {
        return vec![[1.0; 3]; n];
    }
    (0..n)
        .map(|i| {
            let (a, b, h) = if i == 0 {
                (0, 1, 1.0)
            } else if i == n - 1 {
                (n - 2, n - 1, 1.0)
            } else {
                (i - 1, i + 1, 2.0)
            };
            [0, 1, 2].map(|c| (v[b][c] - v[a][c]) / h)
        })
        .collect()
}

fn cesium_lla(r: &[f64; 3], t: &DateTime<Utc>, dp: i32, alt_dp: i32) -> Value {
    let l = eci_to_llh(r, gmst_rad(t));
    json!([
        round_to(l[1], dp),
        round_to(l[0], dp),
        round_to(l[2] * 1000.0, alt_dp)
    ])
}

pub fn compute_scene(
    cfg: &Config,
    primary: u32,
    secondary: u32,
    variant: Option<&str>,
    names: &dyn Fn(u32) -> Option<String>,
) -> anyhow::Result<Value> {
    let db = cfg.resolve_db().ok_or_else(|| anyhow::anyhow!("找不到資料庫"))?;
    let preset = preset_for(primary, secondary, variant);
    let window = preset.get("window").and_then(Value::as_array).and_then(|w| {
        Some((
            parse_time(w.first()?.as_str()?)?,
            parse_time(w.get(1)?.as_str()?)?,
        ))
    });
    let excl = |nid: u32| -> Vec<(DateTime<Utc>, DateTime<Utc>)> {
        preset["exclude_epochs"][nid.to_string()]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|w| Some((parse_time(w.get(0)?.as_str()?)?, parse_time(w.get(1)?.as_str()?)?)))
            .collect()
    };
    let focus_hours = preset.get("focus_hours").and_then(Value::as_f64).unwrap_or(12.0);
    let fine_step_s = preset.get("fine_step_s").and_then(Value::as_f64).unwrap_or(60.0);

    let (prec, pname) = load_recs(&db, primary, window, &excl(primary))?
        .ok_or_else(|| anyhow::anyhow!("raw_tle_archive 無 NORAD {primary} 的 TLE（可先回補歷史 TLE）"))?;
    let (srec, sname) = load_recs(&db, secondary, window, &excl(secondary))?
        .ok_or_else(|| anyhow::anyhow!("raw_tle_archive 無 NORAD {secondary} 的 TLE（可先回補歷史 TLE）"))?;
    let pname = pname
        .or_else(|| names(primary))
        .unwrap_or_else(|| format!("NORAD {primary}"));
    let sname = sname
        .or_else(|| names(secondary))
        .unwrap_or_else(|| format!("NORAD {secondary}"));

    let (mut lo, mut hi) = (prec.lo.max(srec.lo), prec.hi.min(srec.hi));
    if let Some(sp) = preset.get("span").and_then(Value::as_array) {
        if let (Some(a), Some(b)) = (
            sp.first().and_then(Value::as_str).and_then(parse_time),
            sp.get(1).and_then(Value::as_str).and_then(parse_time),
        ) {
            lo = a;
            hi = b;
        }
    }
    if hi <= lo {
        anyhow::bail!(
            "兩顆 TLE 無時間重疊（{primary}:{}~{} vs {secondary}:{}~{}）",
            prec.lo,
            prec.hi,
            srec.lo,
            srec.hi
        );
    }

    let (sr, st, srad) = (cfg.sigma_r_km, cfg.sigma_t_km, cfg.sat_radius_km);
    let pc = |d: f64| compute_pc_chan(d, sr, st, srad);

    let span_min = (hi - lo).num_seconds() as f64 / 60.0;
    let coarse_step_min = (span_min / 1500.0).max(30.0);
    let coarse = sample(&prec, &srec, lo, hi, coarse_step_min * 60.0);
    if coarse.is_empty() {
        anyhow::bail!("無有效傳播點（TLE 可能不足或 SGP4 失敗）");
    }
    let series: Vec<Value> = coarse
        .iter()
        .map(|c| json!({"t": iso_z(&c.t), "d": round_to(c.d, 3), "pc": pc(c.d)}))
        .collect();

    let fc = pick_focus_center(&preset, &coarse, lo, hi);
    let fh = Duration::milliseconds((focus_hours * 3_600_000.0) as i64);
    let (f0, f1) = (lo.max(fc - fh), hi.min(fc + fh));
    let mut fine = sample(&prec, &srec, f0, f1, fine_step_s);
    if fine.is_empty() {
        fine = sample(&prec, &srec, lo, hi, coarse_step_min * 60.0);
    }

    // RTN（LVLH）：R = 徑向、N = r × v（有限差分速度）、T = N × R
    let rps: Vec<[f64; 3]> = fine.iter().map(|f| f.rp).collect();
    let vps = gradient(&rps);
    let unit = |v: [f64; 3]| {
        let n = (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]).sqrt().max(1e-12);
        [v[0] / n, v[1] / n, v[2] / n]
    };
    let cross = |a: [f64; 3], b: [f64; 3]| {
        [
            a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0],
        ]
    };
    let dot = |a: [f64; 3], b: [f64; 3]| a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

    let orbit: Vec<Value> = fine
        .iter()
        .zip(&vps)
        .map(|(f, v)| {
            let r = unit(f.rp);
            let n = unit(cross(f.rp, *v));
            let t = cross(n, r);
            let rel = [f.rs[0] - f.rp[0], f.rs[1] - f.rp[1], f.rs[2] - f.rp[2]];
            json!({
                "t": iso_z(&f.t),
                "p": cesium_lla(&f.rp, &f.t, 4, 1),
                "s": cesium_lla(&f.rs, &f.t, 4, 1),
                "d": round_to(f.d, 4),
                "pc": pc(f.d),
                "rtn": [round_to(dot(rel, r), 4), round_to(dot(rel, t), 4), round_to(dot(rel, n), 4)],
            })
        })
        .collect();

    let trail = preset
        .get("trail_step_min")
        .and_then(Value::as_f64)
        .and_then(|tsm| {
            let tr = sample(&prec, &srec, lo, hi, tsm * 60.0);
            (!tr.is_empty()).then(|| {
                json!({
                    "step_min": tsm,
                    "t": tr.iter().map(|x| iso_z(&x.t)).collect::<Vec<_>>(),
                    "p": tr.iter().map(|x| cesium_lla(&x.rp, &x.t, 3, 0)).collect::<Vec<_>>(),
                    "s": tr.iter().map(|x| cesium_lla(&x.rs, &x.t, 3, 0)).collect::<Vec<_>>(),
                    "d": tr.iter().map(|x| round_to(x.d, 2)).collect::<Vec<_>>(),
                })
            })
        });

    let imin = fine
        .iter()
        .enumerate()
        .min_by(|a, b| round_to(a.1.d, 4).total_cmp(&round_to(b.1.d, 4)))
        .map(|x| x.0)
        .unwrap();
    let g = coarse.iter().min_by(|a, b| a.d.total_cmp(&b.d)).unwrap();
    let get = |k: &str, d: Value| preset.get(k).cloned().unwrap_or(d);
    let meta = json!({
        "primId": primary, "secId": secondary,
        "primName": pname, "secName": sname,
        "title": get("title", json!(format!("相對接近 3D — {pname} × {sname}"))),
        "subtitle": get("subtitle", json!(format!(
            "{primary} 與 {secondary} 之 SGP4 相對幾何重建與 Pc（Chan 首階排序代理，非作業級）。"))),
        "events": get("events", json!([{"t": orbit[imin]["t"], "label": "TCA"}])),
        "timeline": get("timeline", json!([])),
        "focus": [iso_z(&f0), iso_z(&f1)],
        "overlap": [iso_z(&lo), iso_z(&hi)],
        "sigma_r": sr, "sigma_t": st, "sigma_n": SIGMA_N_KM, "sat_radius": srad,
        "trail_s": preset.get("trail_hours").and_then(Value::as_f64).unwrap_or(1.5) * 3600.0,
        "phases": get("phases", json!([])),
        "frame_note": "相對分量為 secondary−primary 於 primary 之 RTN(LVLH)：R 徑向外、T 沿軌、N 軌道面法向；SGP4/TEME 幾何重建，公開 TLE 級精度",
        "variant": variant,
        "engine": "rust",
    });
    let mut summary = json!({
        "d_min": orbit[imin]["d"], "t_min": orbit[imin]["t"], "pc_max": orbit[imin]["pc"],
        "d_min_global": round_to(g.d, 3), "t_min_global": iso_z(&g.t),
        "n_orbit": orbit.len(), "fine_step_s": fine_step_s,
        "n_series": series.len(), "coarse_step_min": round_to(coarse_step_min, 1),
    });
    tracing::info!(
        "RPO 場景 {primary}×{secondary}：TCA {} d_min={} km（orbit {} 點、series {} 點）",
        summary["t_min"],
        summary["d_min"],
        orbit.len(),
        series.len()
    );
    let mut out = json!({"orbit": orbit, "series": series, "meta": meta});
    if let Some(tr) = trail {
        summary["n_trail"] = json!(tr["t"].as_array().map(Vec::len).unwrap_or(0));
        out["trail"] = tr;
    }
    out["summary"] = summary;
    Ok(out)
}

pub fn cache_file(cfg: &Config, p: u32, s: u32, variant: Option<&str>) -> std::path::PathBuf {
    let suffix = variant.map(|v| format!("_{v}")).unwrap_or_default();
    cfg.home
        .join("DB")
        .join(format!("rpo_scene_{p}_{s}{suffix}.json"))
}

/// 記憶體快取型別（key: (p, s, variant)）
pub type SceneCache = HashMap<(u32, u32, Option<String>), std::sync::Arc<Value>>;
