//! 第二階段跨語言比對命令列：讀 JSON 輸入、輸出 JSON 到 stdout（由 Python tools/phase2_xlang_report.py 呼叫）。
//!
//! 子命令：
//!   validate <scenario.json>
//!   schema-cases <schema_cases.json>                 （base 路徑相對於 cases 檔）
//!   e2e <scenario.json> <eop.csv>
//!   maneuver <scenario.json> <eop.csv>              → 避碰決策報告（同 Python maneuver.run）
//!   sgp4 <input.json>          {"tles":[{"line1","line2"}],"times":[iso]}
//!   frames <input.json> <eop.csv>   {"cases":[{"t":iso,"r_teme":[3],"v_teme":[3]}]}
//!   propagate <input.json> <eop.csv> {"epoch","r_km","v_kms","duration_s","step_s","zonal","drag","ballistic_m2_kg","out_times":[τ]}
//!   kepler-tca <input.json>    {"cases":[{"e1":[6],"e2":[6],"t1","step","cov3":[[3]],"hbr_km"}]}
//!   pc <input.json>            {"cases":[{"miss":[2],"c2":[[2]],"hbr_km"}]}
//!   adaptive-tle <input.json> <eop.csv>
//!       {"start","duration_s","coarse_step_s","threshold_km","min_step_s"?,"pairs":[{"p":{"line1","line2"},"s":{...}}]}
//!       → [{"minima":[{"tau","miss_km","v_rel_kms","flag"}],"n_evals"}]（all_minima，依 τ 排序）
//!   covprop <input.json> <eop.csv>
//!       {"epoch","r_km","v_kms","P0":6×6 GCRF,"duration_s","state_step_s","cov_step_s","zonal","q_km2_s3","out_times":[τ]}
//!       → [{"P":6×6}]（地球定向表範圍 [−1, duration_s+1] s，與 Python 測試相同）
//!   csv-parse <file.csv>       → {"rows","errors"}（同 Python parse_secondaries）
//!   batch <request.json> <eop.csv> <tle_fixture.json>   → 批次報告（TLE 由 fixture 的 "tles" 查詢）
#[path = "../phase2/mod.rs"]
mod phase2;

use std::path::Path;

use phase2::eop::Eop;
use phase2::{batch, covprop, csvio, e2e, ephemeris, maneuver, frames, integrator, kepler, pc, schema, screening, tca, timescale::UtcTime, V3};
use serde_json::{json, Value};

fn read(p: &str) -> anyhow::Result<Value> {
    Ok(serde_json::from_str(&std::fs::read_to_string(p)?)?)
}

fn v3(v: &Value) -> V3 {
    [v[0].as_f64().unwrap(), v[1].as_f64().unwrap(), v[2].as_f64().unwrap()]
}

fn elements(v: &Value) -> kepler::Elements {
    let a: Vec<f64> = v.as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect();
    kepler::Elements { a_km: a[0], e: a[1], i_rad: a[2], raan_rad: a[3], argp_rad: a[4], m0_rad: a[5] }
}

fn main() -> anyhow::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    anyhow::ensure!(args.len() >= 3, "用法：phase2_cli <子命令> <輸入> [eop.csv]");
    let out = match args[1].as_str() {
        "validate" => schema::validate(&read(&args[2])?).to_json(),
        "schema-cases" => {
            let spec = read(&args[2])?;
            let dir = Path::new(&args[2]).parent().unwrap();
            let base = read(dir.join(spec["base"].as_str().unwrap()).to_str().unwrap())?;
            let res: Vec<Value> = spec["cases"].as_array().unwrap().iter().map(|c| {
                let v = schema::validate(&phase2::apply_ops(&base, &c["ops"]));
                json!({"name": c["name"], "codes": v.codes})
            }).collect();
            json!(res)
        }
        "e2e" => e2e::run(&read(&args[2])?, &Eop::load(Path::new(&args[3]))?)?,
        "maneuver" => maneuver::run(&read(&args[2])?, &Eop::load(Path::new(&args[3]))?)?,
        "sgp4" => {
            let inp = read(&args[2])?;
            let times: Vec<UtcTime> = inp["times"].as_array().unwrap().iter().map(|t| UtcTime::parse(t.as_str().unwrap()).unwrap()).collect();
            let res: Vec<Value> = inp["tles"].as_array().unwrap().iter().map(|t| {
                let (l1, l2) = (t["line1"].as_str().unwrap(), t["line2"].as_str().unwrap());
                let states: Vec<Value> = times.iter().map(|tm| match e2e::sgp4_teme(l1, l2, tm) {
                    Ok((r, v)) => json!({"r": r, "v": v}),
                    Err(e) => json!({"error": e.to_string()}),
                }).collect();
                json!(states)
            }).collect();
            json!(res)
        }
        "frames" => {
            let inp = read(&args[2])?;
            let eop = Eop::load(Path::new(&args[3]))?;
            let res: Vec<Value> = inp["cases"].as_array().unwrap().iter().map(|c| {
                let t = UtcTime::parse(c["t"].as_str().unwrap()).unwrap();
                let er = frames::earth_rotation(&t, &eop).unwrap();
                let (rg, vg) = frames::teme_to_gcrf(v3(&c["r_teme"]), v3(&c["v_teme"]), &er);
                let (ri, vi) = frames::teme_to_itrf(v3(&c["r_teme"]), v3(&c["v_teme"]), &er);
                json!({"r_gcrf": rg, "v_gcrf": vg, "r_itrf": ri, "v_itrf": vi})
            }).collect();
            json!(res)
        }
        "propagate" => {
            let c = read(&args[2])?;
            let eop = Eop::load(Path::new(&args[3]))?;
            let ep = UtcTime::parse(c["epoch"].as_str().unwrap())?;
            let dur = c["duration_s"].as_f64().unwrap();
            let (zonal, drag) = (c["zonal"].as_bool().unwrap(), c["drag"].as_bool().unwrap());
            let ert = if zonal || drag { Some(frames::EarthRotationTable::new(ep, 0.0, dur, &eop)?) } else { None };
            let fm = phase2::forces::ForceModel::new(zonal, drag, c["ballistic_m2_kg"].as_f64().unwrap_or(0.0));
            let tr = integrator::propagate(v3(&c["r_km"]), v3(&c["v_kms"]), 0.0, dur, c["step_s"].as_f64().unwrap(), &fm, ert.as_ref());
            let res: Vec<Value> = c["out_times"].as_array().unwrap().iter().map(|t| {
                let (r, v, a) = tr.state(t.as_f64().unwrap());
                json!({"r": r, "v": v, "a": a})
            }).collect();
            json!(res)
        }
        "kepler-tca" => {
            let inp = read(&args[2])?;
            let res: Vec<Value> = inp["cases"].as_array().unwrap().iter().map(|c| {
                let (e1, e2) = (elements(&c["e1"]), elements(&c["e2"]));
                let rel = |t: f64| {
                    let (r1, v1, a1) = kepler::state(&e1, t);
                    let (r2, v2, a2) = kepler::state(&e2, t);
                    (phase2::la::sub(r2, r1), phase2::la::sub(v2, v1), phase2::la::sub(a2, a1))
                };
                let t1 = c["t1"].as_f64().unwrap();
                let r = tca::find_minima(&rel, 0.0, t1, c["step"].as_f64().unwrap(), None);
                let g = r.global_min().unwrap().clone();
                let cov: Vec<Vec<f64>> = c["cov3"].as_array().unwrap().iter().map(|row| row.as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect()).collect();
                let c3 = [[cov[0][0], cov[0][1], cov[0][2]], [cov[1][0], cov[1][1], cov[1][2]], [cov[2][0], cov[2][1], cov[2][2]]];
                let hbr = c["hbr_km"].as_f64().unwrap();
                let (m2, c2, _) = pc::project(g.r_rel, g.v_rel, &c3);
                let period = 2.0 * std::f64::consts::PI * (e1.a_km.powi(3) / phase2::constants::GM_KM3_S2).sqrt();
                let others: Vec<f64> = r.all_minima.iter().map(|m| m.tau).collect();
                let c3f = move |_t: f64| c3;
                let scr = screening::screen(&rel, g.tau, Some(&c3f), "demo", hbr, period, &others, (0.0, t1));
                json!({"tau": g.tau, "miss_km": g.miss_km, "v_rel_kms": phase2::la::norm(g.v_rel), "n_minima": r.all_minima.len(),
                       "pc_foster": pc::pc_foster(m2, &c2, hbr).ok(), "pc_chan": pc::pc_chan(m2, &c2, hbr).ok(),
                       "screen": scr["status"], "t_enc_s": scr["metrics"]["t_enc_s"]})
            }).collect();
            json!(res)
        }
        "pc" => {
            let inp = read(&args[2])?;
            let res: Vec<Value> = inp["cases"].as_array().unwrap().iter().map(|c| {
                let m = [c["miss"][0].as_f64().unwrap(), c["miss"][1].as_f64().unwrap()];
                let c2 = [[c["c2"][0][0].as_f64().unwrap(), c["c2"][0][1].as_f64().unwrap()],
                          [c["c2"][1][0].as_f64().unwrap(), c["c2"][1][1].as_f64().unwrap()]];
                let h = c["hbr_km"].as_f64().unwrap();
                json!({"foster": pc::pc_foster(m, &c2, h).ok(), "chan": pc::pc_chan(m, &c2, h).ok()})
            }).collect();
            json!(res)
        }
        "adaptive-tle" => {
            let inp = read(&args[2])?;
            let eop = Eop::load(Path::new(&args[3]))?;
            let start = UtcTime::parse(inp["start"].as_str().unwrap())?;
            let dur = inp["duration_s"].as_f64().unwrap();
            let ert = frames::EarthRotationTable::new(start, -1.0, dur + 1.0, &eop)?;
            let mut res = Vec::new();
            for pr in inp["pairs"].as_array().unwrap() {
                let mk = |o: &Value| ephemeris::Sgp4Ephemeris::new(o["line1"].as_str().unwrap(), o["line2"].as_str().unwrap(), start, &ert, (0.0, dur));
                let (p, s) = (mk(&pr["p"])?, mk(&pr["s"])?);
                let rel = ephemeris::RelativeState::new(&p, &s);
                let r = tca::find_minima_adaptive(&|t| rel.rv(t), &|t| rel.rva(t), 0.0, dur, tca::AdaptiveParams {
                    coarse_step: inp["coarse_step_s"].as_f64().unwrap_or(phase2::constants::SEARCH_COARSE_STEP_S),
                    threshold_km: inp["threshold_km"].as_f64(),
                    min_step: inp.get("min_step_s").and_then(Value::as_f64).unwrap_or(phase2::constants::SEARCH_MIN_STEP_S),
                    ..Default::default()
                });
                let minima: Vec<Value> = r.all_minima.iter().map(|a| json!({"tau": a.tau, "miss_km": a.miss_km,
                    "v_rel_kms": phase2::la::norm(a.v_rel), "flag": a.flag})).collect();
                res.push(json!({"minima": minima, "n_evals": rel.n_evals.get()}));
            }
            json!(res)
        }
        "covprop" => {
            let c = read(&args[2])?;
            let eop = Eop::load(Path::new(&args[3]))?;
            let ep = UtcTime::parse(c["epoch"].as_str().unwrap())?;
            let dur = c["duration_s"].as_f64().unwrap();
            let zonal = c["zonal"].as_bool().unwrap_or(true);
            let ert = frames::EarthRotationTable::new(ep, -1.0, dur + 1.0, &eop)?;
            let fm = phase2::forces::ForceModel::new(zonal, false, 0.0);
            let eph = ephemeris::NumericalEphemeris::new(integrator::propagate(v3(&c["r_km"]), v3(&c["v_kms"]), 0.0, dur,
                c["state_step_s"].as_f64().unwrap(), &fm, Some(&ert)));
            let p0: Vec<Vec<f64>> = c["P0"].as_array().unwrap().iter()
                .map(|r| r.as_array().unwrap().iter().map(|x| x.as_f64().unwrap()).collect()).collect();
            let trk = covprop::CovarianceTrack::new(&eph, covprop::m6_from(&p0), 0.0, dur, c["cov_step_s"].as_f64().unwrap(),
                Some(&ert), zonal, c["q_km2_s3"].as_f64().unwrap_or(0.0));
            let mut res = Vec::new();
            for t in c["out_times"].as_array().unwrap() {
                res.push(json!({"P": covprop::m6_to_vec(&trk.at(t.as_f64().unwrap())?)}));
            }
            json!(res)
        }
        "csv-parse" => csvio::parse_secondaries(&std::fs::read_to_string(&args[2])?),
        "batch" => {
            let body = read(&args[2])?;
            let eop = Eop::load(Path::new(&args[3]))?;
            anyhow::ensure!(args.len() >= 5, "用法：phase2_cli batch <request.json> <eop.csv> <tle_fixture.json>");
            let fx = read(&args[4])?;
            let lookup = |n: i64| fx["tles"].get(n.to_string()).map(|t| (
                t["name"].as_str().unwrap_or("").to_string(), t["line1"].as_str().unwrap_or("").to_string(),
                t["line2"].as_str().unwrap_or("").to_string()));
            match batch::prepare_request(&body) {
                Ok((req, _parsed)) => batch::run_batch(&req, &eop, &lookup)?,
                Err(e) => e,
            }
        }
        other => anyhow::bail!("未知子命令 {other}"),
    };
    println!("{}", serde_json::to_string(&out)?);
    Ok(())
}
