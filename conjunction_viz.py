#!/usr/bin/env python3
"""
conjunction_viz.py — 通用 conjunction/rendezvous 視覺化：任意 primary × secondary NORAD
=======================================================================================
把 Shenlong(58573)×ObjectG(59884) 的一次性重建產品化。對任兩顆衛星：
  1. 自動抓兩者 TLE 重疊時間窗（raw_tle_archive），逐時刻用「最近 elset」SGP4 傳播；
  2. 算相對距離、range-rate，以及**兩個 LVLH/RTN 座標系**下對方的位置：
       primary 視角：secondary 在 primary RTN frame 的 (R,T,N)
       secondary 視角：primary 在 secondary RTN frame 的 (R2,T2,N2)
     （供「從各自角度觀察對方」的 3D 立體圖）；
  3. 雙物體平均高度序列（a−R⊕）。

輸出：
  compute_pair_series(...) → dict（rel / altP / altS / meta / summary），app 分頁直接吃。
  write_html(data, out)    → 自包含互動四視角 HTML（可當 Artifact 分享）。
  CLI： python conjunction_viz.py 58573 59884 --out figs/rpo.html

已知案例預設（標題/事件時間軸）內建於 _PRESETS；未知 pair 自動產生通用標題與 TCA 標記。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import duckdb
import numpy as np
import pandas as pd
from sgp4.api import Satrec, jday

RE, MU = 6378.137, 398600.4418
DB_DEFAULT = "space_db.duckdb"

# 已知事件預設（標題、副題、事件標記、時間軸）
_PRESETS = {
    (58573, 59884): {
        "title": "Shenlong Spaceplane — Secondary Object Deployment & Re-approach",
        "subtitle": ("China's reusable spaceplane 58573 released 59884 near 605 km on 24 May 2024, "
                     "departed to ~1,700 km, then re-approached to 1.4 km in June — a drift reversal "
                     "that requires thrust."),
        "events": [
            {"t": "2024-05-24T16:30Z", "label": "DEPLOY", "color": "--crit"},
            {"t": "2024-05-25T08:33Z", "label": "1ST OBS", "color": "--sec"},
            {"t": "2024-06-06T00:00Z", "label": "RE-APPROACH", "color": "--crit"},
            {"t": "2024-06-14T10:13Z", "label": "TCA 1.4 km", "color": "--crit"},
        ],
        "timeline": [
            {"d": "14 Dec 2023", "c": "", "t": "<b>Launch.</b> Shenlong (58573) reaches LEO on its third mission (CASC)."},
            {"d": "Jan–Feb 2024", "c": "", "t": "<b>Maneuvers.</b> Repeated orbit changes over the mission's first months."},
            {"d": "24 May 2024", "c": "crit", "t": "<b>Deployment.</b> Secondary released in a 16:30–22:50 UTC window near 605 km."},
            {"d": "25 May 2024", "c": "sec", "t": "<b>First elset.</b> Object G (59884) catalogued 15:13 UTC — ~9–16 h after separation."},
            {"d": "25 May–5 Jun", "c": "", "t": "<b>Departure.</b> Along-track separation grows steadily to ~1,720 km."},
            {"d": "6–8 Jun 2024", "c": "crit", "t": "<b>Re-approach.</b> Separation collapses 1,439 km → 5.9 km in ~3 days. "
                                                    "Natural along-track drift is monotonic — reversing it requires thrust."},
            {"d": "8–18 Jun 2024", "c": "crit", "t": "<b>Proximity operations.</b> Held within ~2–80 km for ~10 days; "
                                                     "closest approach 1.41 km on 14 Jun 10:13 UTC. HCW residual peaks at "
                                                     "13.0 km (75× the debris-calibrated baseline), along-track dominated "
                                                     "(T 12.2 / N 0.13 km) — the signature of an in-plane burn."},
            {"d": "19 Jun–21 Jul", "c": "", "t": "<b>Departure again.</b> Separation grows to 13,704 km by 21 Jul 2024."},
        ],
    },
}


# ────────────────────────────────────────────────────────────────────────────
def _load_tles(con, nid):
    df = con.execute(
        "SELECT epoch_utc, object_name, line1, line2, sma_km FROM raw_tle_archive "
        "WHERE norad_id=? AND line1 IS NOT NULL AND sma_km IS NOT NULL ORDER BY epoch_utc",
        [int(nid)]).fetchdf()
    if df.empty:
        return df, None
    df["epoch_utc"] = pd.to_datetime(df["epoch_utc"], utc=True)
    import re
    name = re.sub(r"^0\s+", "", str(df["object_name"].iloc[-1]).strip())  # 去 TLE line-0 分類碼
    return df.drop_duplicates("epoch_utc").reset_index(drop=True), name


def _recs(df):
    recs, ep = [], []
    for _, r in df.iterrows():
        try:
            recs.append(Satrec.twoline2rv(r.line1, r.line2))
            ep.append(r.epoch_utc.to_pydatetime().timestamp())
        except Exception:
            pass
    return recs, np.array(ep)


def _prop(recs, ep_ts, t):
    j = int(np.argmin(np.abs(ep_ts - t.timestamp())))
    jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
    e, r, v = recs[j].sgp4(jd, fr)
    if e != 0:
        return None, None
    return np.array(r), np.array(v)


def _rtn_basis(r, v):
    R = r / np.linalg.norm(r)
    h = np.cross(r, v); N = h / np.linalg.norm(h); Tt = np.cross(N, R)
    return R, Tt, N


def compute_pair_series(db: str, primary: int, secondary: int,
                        start: str | None = None, end: str | None = None,
                        step_min: float = 30.0, max_pts: int = 1400,
                        alt_pad_days: float = 20.0) -> dict:
    """回傳 dict：rel[{t,d,R,T,N,R2,T2,N2,rr}], altP, altS, meta, summary。

    start/end 為 ISO 日期（None → 用兩者 TLE 重疊窗）。step_min 會自動放大以不超過 max_pts。"""
    con = duckdb.connect(db, read_only=True)
    P, pname = _load_tles(con, primary)
    S, sname = _load_tles(con, secondary)
    if P.empty or S.empty:
        con.close()
        miss = primary if P.empty else secondary
        raise ValueError(f"raw_tle_archive 無 NORAD {miss} 的 TLE（可先用 backfill_tle_history.py 回補）")

    # 重疊窗
    lo = max(P.epoch_utc.min(), S.epoch_utc.min())
    hi = min(P.epoch_utc.max(), S.epoch_utc.max())
    if start:
        lo = max(lo, pd.Timestamp(start, tz="UTC"))
    if end:
        hi = min(hi, pd.Timestamp(end, tz="UTC"))
    if hi <= lo:
        con.close()
        raise ValueError(f"兩顆 TLE 無時間重疊（{primary}:{P.epoch_utc.min()}~{P.epoch_utc.max()} "
                         f"vs {secondary}:{S.epoch_utc.min()}~{S.epoch_utc.max()}）")
    # 自動步長
    span_min = (hi - lo).total_seconds() / 60.0
    step = max(step_min, span_min / max_pts)

    Precs, Pep = _recs(P); Srecs, Sep = _recs(S)
    rel = []
    t = lo.to_pydatetime()
    tend = hi.to_pydatetime()
    while t <= tend:
        rp, vp = _prop(Precs, Pep, t); rs, vs = _prop(Srecs, Sep, t)
        if rp is not None and rs is not None:
            dr = rs - rp                      # primary → secondary
            Rp, Tp, Np = _rtn_basis(rp, vp)
            Rs, Ts, Ns = _rtn_basis(rs, vs)
            dist = float(np.linalg.norm(dr))
            rr = float((dr @ (vs - vp)) / dist) if dist > 0 else 0.0
            rel.append({
                "t": t.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
                "d": round(dist, 3),
                "R": round(float(dr @ Rp), 3), "T": round(float(dr @ Tp), 3), "N": round(float(dr @ Np), 3),
                "R2": round(float((-dr) @ Rs), 3), "T2": round(float((-dr) @ Ts), 3), "N2": round(float((-dr) @ Ns), 3),
                "rr": round(rr, 5),
            })
        t += timedelta(minutes=step)

    # 高度序列（窗 ±pad）
    a0 = lo - timedelta(days=float(alt_pad_days))
    a1 = hi + timedelta(days=float(alt_pad_days))
    def _alt(df):
        m = (df.epoch_utc >= a0) & (df.epoch_utc <= a1)
        return [{"t": e.isoformat().replace("+00:00", "Z"), "a": round(float(a) - RE, 3)}
                for e, a in zip(df[m].epoch_utc, df[m].sma_km) if a == a]
    altP, altS = _alt(P), _alt(S)
    con.close()

    if not rel:
        raise ValueError("無有效傳播點（TLE 可能不足或 SGP4 失敗）。")

    dists = np.array([x["d"] for x in rel])
    imin = int(dists.argmin())
    preset = _PRESETS.get((int(primary), int(secondary)), {})
    meta = {
        "primId": int(primary), "secId": int(secondary),
        "primName": pname or f"NORAD {primary}", "secName": sname or f"NORAD {secondary}",
        "title": preset.get("title", f"Relative Motion — {pname} × {sname}"),
        "subtitle": preset.get("subtitle",
                    f"SGP4 reconstruction of the relative geometry between {primary} and {secondary}."),
        "events": preset.get("events", [{"t": rel[imin]["t"], "label": "TCA", "color": "--crit"}]),
        "timeline": preset.get("timeline", []),
        "window": [rel[0]["t"], rel[-1]["t"]],
    }
    aP = np.array([x["a"] for x in altP]) if altP else np.array([np.nan])
    aS = np.array([x["a"] for x in altS]) if altS else np.array([np.nan])
    summary = {
        "n": len(rel), "step_min": round(step, 1),
        "d_first": rel[0]["d"], "d_last": rel[-1]["d"],
        "d_min": round(float(dists.min()), 3), "d_min_t": rel[imin]["t"],
        "d_max": round(float(dists.max()), 3),
        "altP_span": round(float(np.nanmax(aP) - np.nanmin(aP)), 2),
        "altS_span": round(float(np.nanmax(aS) - np.nanmin(aS)), 2),
        "altP_last": round(float(aP[-1]), 2) if len(aP) else None,
        "altS_last": round(float(aS[-1]), 2) if len(aS) else None,
    }
    return {"rel": rel, "altP": altP, "altS": altS, "meta": meta, "summary": summary}


# ────────────────────────────────────────────────────────────────────────────
def write_html(data: dict, out_path: str) -> str:
    """把 data 嵌入通用互動 HTML 模板並寫檔。回傳路徑。"""
    tpl = _HTML_TEMPLATE.replace("/*__DATA__*/", json.dumps(data))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(tpl, encoding="utf-8")
    return out_path


def main():
    ap = argparse.ArgumentParser(description="通用 conjunction/rendezvous 四視角視覺化")
    ap.add_argument("primary", type=int)
    ap.add_argument("secondary", type=int)
    ap.add_argument("--db", default=DB_DEFAULT)
    ap.add_argument("--start", default=None, help="ISO 日期，預設用 TLE 重疊窗起")
    ap.add_argument("--end", default=None)
    ap.add_argument("--step-min", type=float, default=30.0)
    ap.add_argument("--out", default=None, help="輸出 HTML 路徑（預設 figs/rpo_<p>_<s>.html）")
    args = ap.parse_args()

    print(f"計算 {args.primary} × {args.secondary} …")
    data = compute_pair_series(args.db, args.primary, args.secondary,
                               start=args.start, end=args.end, step_min=args.step_min)
    s = data["summary"]; m = data["meta"]
    print(f"  {m['primName']} × {m['secName']}")
    print(f"  窗 {m['window'][0][:16]} ~ {m['window'][1][:16]}  {s['n']} 點 @ {s['step_min']}min")
    print(f"  range: first={s['d_first']} min={s['d_min']}(@{s['d_min_t'][:16]}) last={s['d_last']} km")
    print(f"  高度: primary Δ{s['altP_span']}km  secondary Δ{s['altS_span']}km")
    out = args.out or f"figs/rpo_{args.primary}_{args.secondary}.html"
    write_html(data, out)
    print(f"HTML → {out}")


# ── 通用互動 HTML 模板（四視角 2D；標籤/事件/時間軸由 DATA.meta 驅動）──────────────
_HTML_TEMPLATE = r"""<title>Relative Motion Reconstruction</title>
<style>
  :root{
    --ground:#0A0D13;--panel:#10141D;--elev:#161C28;--line:rgba(255,255,255,.06);--hair:rgba(255,255,255,.10);
    --ink:#E8ECF4;--muted:#828DA6;--faint:#525C72;--prim:#F2A73B;--sec:#35C6F4;--crit:#FF5C4E;--ok:#4FD08A;
    --mono:ui-monospace,"JetBrains Mono","SF Mono",Menlo,Consolas,monospace;
    --sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;}
  @media (prefers-color-scheme:light){:root{
    --ground:#EEF1F6;--panel:#FBFCFE;--elev:#FFFFFF;--line:rgba(10,20,40,.08);--hair:rgba(10,20,40,.16);
    --ink:#141A24;--muted:#586074;--faint:#9AA2B4;--prim:#B9760A;--sec:#0E7FB0;--crit:#D63A2C;--ok:#1E9E63;}}
  :root[data-theme="dark"]{--ground:#0A0D13;--panel:#10141D;--elev:#161C28;--line:rgba(255,255,255,.06);--hair:rgba(255,255,255,.10);
    --ink:#E8ECF4;--muted:#828DA6;--faint:#525C72;--prim:#F2A73B;--sec:#35C6F4;--crit:#FF5C4E;--ok:#4FD08A;}
  :root[data-theme="light"]{--ground:#EEF1F6;--panel:#FBFCFE;--elev:#FFFFFF;--line:rgba(10,20,40,.08);--hair:rgba(10,20,40,.16);
    --ink:#141A24;--muted:#586074;--faint:#9AA2B4;--prim:#B9760A;--sec:#0E7FB0;--crit:#D63A2C;--ok:#1E9E63;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased;line-height:1.55;
    background-image:radial-gradient(1200px 600px at 78% -10%,rgba(242,167,59,.06),transparent 60%);}
  .wrap{max-width:1180px;margin:0 auto;padding:34px 22px 60px}
  .eyebrow{font-family:var(--mono);font-size:11px;letter-spacing:.28em;text-transform:uppercase;color:var(--prim);
    margin:0 0 12px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
  .eyebrow .dot{width:6px;height:6px;border-radius:50%;background:var(--prim);box-shadow:0 0 8px var(--prim)}
  h1{font-size:clamp(26px,4.2vw,42px);line-height:1.05;margin:0 0 14px;font-weight:700;letter-spacing:-.01em;text-wrap:balance}
  .lede{color:var(--muted);max-width:66ch;font-size:15.5px;margin:0 0 22px}
  .legend{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 26px}
  .chip{display:flex;align-items:center;gap:9px;background:var(--panel);border:1px solid var(--line);border-radius:8px;
    padding:8px 13px;font-family:var(--mono);font-size:12px}
  .chip .sw{width:11px;height:11px;border-radius:3px}.chip small{color:var(--muted);letter-spacing:.04em}
  .toggle{position:fixed;top:14px;right:14px;z-index:20;background:var(--panel);color:var(--muted);border:1px solid var(--hair);
    border-radius:7px;padding:7px 11px;font-family:var(--mono);font-size:11px;letter-spacing:.1em;cursor:pointer}
  .toggle:hover{color:var(--ink)}
  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;background:var(--line);
    border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:0 0 30px}
  .stat{background:var(--panel);padding:15px 16px}
  .stat .k{font-family:var(--mono);font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--muted)}
  .stat .v{font-family:var(--mono);font-size:21px;font-weight:600;margin-top:6px;font-variant-numeric:tabular-nums}
  .stat .v small{font-size:12px;color:var(--muted);font-weight:400}
  .stat.crit .v{color:var(--crit)}.stat.prim .v{color:var(--prim)}.stat.sec .v{color:var(--sec)}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px 20px 12px;margin:0 0 22px}
  .panel h2{font-size:14px;font-family:var(--mono);letter-spacing:.06em;text-transform:uppercase;margin:0 0 3px}
  .panel .sub{color:var(--muted);font-size:13px;margin:0 0 14px;max-width:74ch}
  .phead{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap}
  .ctrls{display:flex;gap:6px}
  .seg{font-family:var(--mono);font-size:11px;letter-spacing:.08em;color:var(--muted);background:transparent;
    border:1px solid var(--hair);border-radius:6px;padding:5px 10px;cursor:pointer}
  .seg[aria-pressed="true"]{color:var(--ground);background:var(--prim);border-color:var(--prim)}
  .chartbox{position:relative;width:100%}
  svg{display:block;width:100%;height:auto;overflow:visible}
  .grid line{stroke:var(--line);stroke-width:1}
  .axis text{fill:var(--muted);font-family:var(--mono);font-size:10.5px}
  .axis .lbl{fill:var(--faint);font-size:10px;letter-spacing:.14em;text-transform:uppercase}
  .tip{position:absolute;pointer-events:none;background:var(--elev);border:1px solid var(--hair);border-radius:8px;
    padding:8px 10px;font-family:var(--mono);font-size:11.5px;color:var(--ink);box-shadow:0 8px 24px rgba(0,0,0,.4);
    opacity:0;transition:opacity .08s;white-space:nowrap;z-index:5;font-variant-numeric:tabular-nums}
  .tip .tt{color:var(--muted);font-size:10px;letter-spacing:.06em}
  .cursor{stroke:var(--hair);stroke-width:1;stroke-dasharray:3 3}
  .mk{stroke-width:1.4}.mklab{font-family:var(--mono);font-size:9.5px;letter-spacing:.05em}
  .twocol{display:grid;grid-template-columns:1fr 1fr;gap:22px}
  @media(max-width:820px){.twocol{grid-template-columns:1fr}}
  .tlrow{display:grid;grid-template-columns:130px 1fr;gap:16px;padding:12px 0;border-top:1px solid var(--line)}
  .tlrow:first-child{border-top:0}
  .tldate{font-family:var(--mono);font-size:12px;color:var(--prim);letter-spacing:.03em}
  .tlrow.sec .tldate{color:var(--sec)}.tlrow.crit .tldate{color:var(--crit)}
  .tltxt{font-size:13.5px}.tltxt b{font-weight:600}
  .foot{color:var(--faint);font-size:12px;line-height:1.7;font-family:var(--mono);margin-top:28px;border-top:1px solid var(--line);padding-top:18px}
  .foot b{color:var(--muted);font-weight:600}
  .note{color:var(--muted);font-size:11.5px;font-family:var(--mono);margin:2px 0 10px}
</style>
<button class="toggle" id="themeBtn">◐ THEME</button>
<div class="wrap">
  <p class="eyebrow"><span class="dot"></span>TASA SSA · RELATIVE-MOTION RECONSTRUCTION · TLE+SGP4</p>
  <h1 id="h1"></h1>
  <p class="lede" id="lede"></p>
  <div class="legend" id="legend"></div>
  <div class="stats" id="stats"></div>
  <div class="panel">
    <div class="phead"><div><h2>① Relative separation vs time</h2>
      <p class="sub">Range between the two objects, both propagated to a common clock from their nearest elset.</p></div>
      <div class="ctrls"><button class="seg" id="segLog" aria-pressed="true">LOG</button>
        <button class="seg" id="segLin" aria-pressed="false">LINEAR</button></div></div>
    <div class="chartbox" id="c_dist"></div>
  </div>
  <div class="twocol">
    <div class="panel"><h2>② LVLH relative-motion map</h2>
      <p class="sub">Secondary in the primary's radial/along-track frame, coloured by time.</p>
      <p class="note" id="rtnnote"></p><div class="chartbox" id="c_rtn"></div></div>
    <div class="panel"><h2>③ Range-rate vs time</h2>
      <p class="sub">Closing (−) vs opening (+) speed. Persistently positive = receding.</p>
      <div class="chartbox" id="c_rr"></div></div>
  </div>
  <div class="panel"><h2>④ Mean altitude — both objects</h2>
    <p class="sub">Per-elset mean altitude (a−R⊕): a tight band = a stable object; steps = maneuvers.</p>
    <div class="chartbox" id="c_alt"></div></div>
  <div class="panel" id="tlpanel"><h2>⑤ Timeline of events</h2><div id="tl"></div></div>
  <div class="foot" id="foot"></div>
</div>
<script>
const DATA=/*__DATA__*/;
const T=s=>Date.parse(s);
const fmtT=ms=>{const d=new Date(ms);const p=n=>String(n).padStart(2,'0');return `${d.getUTCMonth()+1}/${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}Z`;};
const fmtD=ms=>{const d=new Date(ms);const mo=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];return `${mo[d.getUTCMonth()]} ${d.getUTCDate()}`;};
const SVGNS="http://www.w3.org/2000/svg";
function el(t,a={}){const e=document.createElementNS(SVGNS,t);for(const k in a)e.setAttribute(k,a[k]);return e;}
function niceTicks(lo,hi,n=5){const r=hi-lo||1;let s=Math.pow(10,Math.floor(Math.log10(r/n)));const e=r/n/s;let m=e>=7.5?10:e>=3.5?5:e>=1.5?2:1;s*=m;const t=[];for(let v=Math.ceil(lo/s)*s;v<=hi+1e-9;v+=s)t.push(v);return t;}
function logTicks(lo,hi){const t=[];for(let p=Math.floor(Math.log10(lo));p<=Math.ceil(Math.log10(hi));p++)for(const m of[1,2,5]){const v=m*Math.pow(10,p);if(v>=lo*.999&&v<=hi*1.001)t.push(v);}return t;}
const col=k=>getComputedStyle(document.documentElement).getPropertyValue(k).trim();
function lineChart(box,opt){box.innerHTML="";const W=box.clientWidth||760,H=opt.h||300,m={l:56,r:opt.mr||16,t:14,b:34};
  const iw=W-m.l-m.r,ih=H-m.t-m.b;const svg=el("svg",{viewBox:`0 0 ${W} ${H}`});box.appendChild(svg);
  const xs=opt.series.flatMap(s=>s.pts.map(p=>p.x));const xlo=opt.xlo??Math.min(...xs),xhi=opt.xhi??Math.max(...xs);
  let ylo=opt.ylo,yhi=opt.yhi;const ally=opt.series.flatMap(s=>s.pts.map(p=>p.y)).filter(v=>opt.log?v>0:true);
  if(ylo==null)ylo=Math.min(...ally);if(yhi==null)yhi=Math.max(...ally);
  if(opt.log){ylo=Math.max(ylo,opt.logmin||.1);}else{const pad=(yhi-ylo)*.08||1;if(!opt.tightTop)yhi+=pad;ylo-=pad;if(opt.y0&&ylo>0)ylo=0;}
  const X=v=>m.l+(v-xlo)/(xhi-xlo||1)*iw;
  const Y=opt.log?(v=>m.t+ih-(Math.log10(Math.max(v,ylo))-Math.log10(ylo))/(Math.log10(yhi)-Math.log10(ylo))*ih):(v=>m.t+ih-(v-ylo)/(yhi-ylo||1)*ih);
  const g=el("g",{class:"grid"});svg.appendChild(g);const ax=el("g",{class:"axis"});svg.appendChild(ax);
  const yt=opt.log?logTicks(ylo,yhi):niceTicks(ylo,yhi,5);
  yt.forEach(v=>{const y=Y(v);g.appendChild(el("line",{x1:m.l,x2:m.l+iw,y1:y,y2:y}));const tx=el("text",{x:m.l-9,y:y+3.5,"text-anchor":"end"});tx.textContent=opt.yfmt?opt.yfmt(v):(Math.abs(v)>=1000?(v/1000)+"k":(+v.toFixed(2)));ax.appendChild(tx);});
  const xt=niceTicks(xlo,xhi,Math.min(6,Math.max(3,Math.floor(iw/110))));
  xt.forEach(v=>{const x=X(v);g.appendChild(el("line",{x1:x,x2:x,y1:m.t,y2:m.t+ih}));const tx=el("text",{x,y:H-12,"text-anchor":"middle"});tx.textContent=fmtD(v);ax.appendChild(tx);});
  const yl=el("text",{class:"lbl",transform:`translate(15,${m.t+ih/2}) rotate(-90)`,"text-anchor":"middle"});yl.textContent=opt.ylabel;ax.appendChild(yl);
  (opt.markers||[]).forEach(mk=>{const x=X(mk.x);if(x<m.l-1||x>m.l+iw+1)return;svg.appendChild(el("line",{x1:x,x2:x,y1:m.t,y2:m.t+ih,class:"mk",stroke:col(mk.color),"stroke-dasharray":mk.dash||"4 3",opacity:.9}));const lab=el("text",{x:x+4,y:m.t+11,class:"mklab",fill:col(mk.color)});lab.textContent=mk.label;svg.appendChild(lab);});
  opt.series.forEach(s=>{let d="",st=false;s.pts.forEach(p=>{if(opt.log&&p.y<=0){st=false;return;}const x=X(p.x),y=Y(p.y);d+=(st?"L":"M")+x.toFixed(1)+" "+y.toFixed(1)+" ";st=true;});
    svg.appendChild(el("path",{d,fill:"none",stroke:col(s.color),"stroke-width":s.w||1.8,"stroke-linejoin":"round","stroke-linecap":"round",opacity:s.op??1}));
    if(s.dots)s.pts.forEach((p,i)=>{if(i%(s.dotEvery||6))return;if(opt.log&&p.y<=0)return;svg.appendChild(el("circle",{cx:X(p.x),cy:Y(p.y),r:s.r||2.1,fill:col(s.color),opacity:.85}));});
    if(s.zero!=null){const yz=Y(s.zero);svg.appendChild(el("line",{x1:m.l,x2:m.l+iw,y1:yz,y2:yz,stroke:col('--hair'),"stroke-width":1}));}});
  const cur=el("line",{class:"cursor",y1:m.t,y2:m.t+ih,x1:m.l,x2:m.l,opacity:0});svg.appendChild(cur);
  const marks=opt.series.map(s=>{const c=el("circle",{r:4,fill:col(s.color),stroke:col('--panel'),"stroke-width":2,opacity:0});svg.appendChild(c);return c;});
  const tip=document.createElement("div");tip.className="tip";box.appendChild(tip);
  const hit=el("rect",{x:m.l,y:m.t,width:iw,height:ih,fill:"transparent"});svg.appendChild(hit);
  hit.addEventListener("mousemove",ev=>{const rb=svg.getBoundingClientRect();const px=(ev.clientX-rb.left)*(W/rb.width);const xv=xlo+(px-m.l)/iw*(xhi-xlo);
    let html=`<div class="tt">${fmtT(xv)}</div>`,any=false;
    opt.series.forEach((s,si)=>{if(!s.pts.length){marks[si].setAttribute("opacity",0);return;}let best=s.pts[0],bd=1e18;for(const p of s.pts){const d=Math.abs(p.x-xv);if(d<bd){bd=d;best=p;}}
      if(opt.log&&best.y<=0){marks[si].setAttribute("opacity",0);return;}marks[si].setAttribute("cx",X(best.x));marks[si].setAttribute("cy",Y(best.y));marks[si].setAttribute("opacity",1);
      html+=`<div><span style="color:${col(s.color)}">■</span> ${s.name}: <b>${opt.tipfmt?opt.tipfmt(best.y):best.y}</b></div>`;any=true;});
    cur.setAttribute("x1",X(xv));cur.setAttribute("x2",X(xv));cur.setAttribute("opacity",any?1:0);tip.innerHTML=html;tip.style.opacity=1;
    const bx=box.getBoundingClientRect();let lft=(ev.clientX-bx.left)+14;if(lft+tip.offsetWidth>box.clientWidth)lft=(ev.clientX-bx.left)-tip.offsetWidth-14;
    tip.style.left=lft+"px";tip.style.top=Math.max(4,(ev.clientY-bx.top)-10)+"px";});
  hit.addEventListener("mouseleave",()=>{tip.style.opacity=0;cur.setAttribute("opacity",0);marks.forEach(c=>c.setAttribute("opacity",0));});}
function rtnChart(box,rel){box.innerHTML="";const W=box.clientWidth||560,H=300,m={l:54,r:14,t:14,b:38};const iw=W-m.l-m.r,ih=H-m.t-m.b;
  const svg=el("svg",{viewBox:`0 0 ${W} ${H}`});box.appendChild(svg);const Tv=rel.map(p=>p.T),Rv=rel.map(p=>p.R);
  let tlo=Math.min(...Tv),thi=Math.max(...Tv),rlo=Math.min(...Rv),rhi=Math.max(...Rv);const tp=(thi-tlo)*.06||1,rp=(rhi-rlo)*.12||1;tlo-=tp;thi+=tp;rlo-=rp;rhi+=rp;
  const X=v=>m.l+(v-tlo)/(thi-tlo)*iw,Y=v=>m.t+ih-(v-rlo)/(rhi-rlo)*ih;
  const g=el("g",{class:"grid"});svg.appendChild(g);const ax=el("g",{class:"axis"});svg.appendChild(ax);
  niceTicks(tlo,thi,5).forEach(v=>{const x=X(v);g.appendChild(el("line",{x1:x,x2:x,y1:m.t,y2:m.t+ih}));const t=el("text",{x,y:H-20,"text-anchor":"middle"});t.textContent=Math.abs(v)>=1000?(v/1000).toFixed(1)+"k":v.toFixed(0);ax.appendChild(t);});
  niceTicks(rlo,rhi,5).forEach(v=>{const y=Y(v);g.appendChild(el("line",{x1:m.l,x2:m.l+iw,y1:y,y2:y}));const t=el("text",{x:m.l-8,y:y+3.5,"text-anchor":"end"});t.textContent=v.toFixed(1);ax.appendChild(t);});
  if(0>rlo&&0<rhi){const y0=Y(0);svg.appendChild(el("line",{x1:m.l,x2:m.l+iw,y1:y0,y2:y0,stroke:col('--hair')}));}
  if(0>tlo&&0<thi){const x0=X(0);svg.appendChild(el("line",{x1:x0,x2:x0,y1:m.t,y2:m.t+ih,stroke:col('--hair')}));}
  ax.appendChild(Object.assign(el("text",{class:"lbl",x:m.l+iw/2,y:H-4,"text-anchor":"middle"}),{textContent:"ALONG-TRACK  T  (km)"}));
  ax.appendChild(Object.assign(el("text",{class:"lbl",transform:`translate(13,${m.t+ih/2}) rotate(-90)`,"text-anchor":"middle"}),{textContent:"RADIAL  R  (km)"}));
  const c1=col('--prim'),c2=col('--sec');const hx=s=>s.startsWith('#')?s:'#888888';
  const lerp=(a,b,t)=>{a=hx(a);b=hx(b);const pa=[1,3,5].map(i=>parseInt(a.slice(i,i+2),16)),pb=[1,3,5].map(i=>parseInt(b.slice(i,i+2),16));return`rgb(${pa.map((v,i)=>Math.round(v+(pb[i]-v)*t)).join(',')})`;};
  svg.appendChild(el("circle",{cx:X(0),cy:Y(0),r:5,fill:"none",stroke:col('--crit'),"stroke-width":1.5}));
  const olab=el("text",{x:X(0)+8,y:Y(0)-6,class:"mklab",fill:col('--crit')});olab.textContent="REF (0,0)";svg.appendChild(olab);
  const tip=document.createElement("div");tip.className="tip";box.appendChild(tip);
  rel.forEach((p,i)=>{const t=i/(rel.length-1||1);const c=el("circle",{cx:X(p.T),cy:Y(p.R),r:2.6,fill:lerp(c1,c2,t),opacity:.8});
    c.addEventListener("mousemove",ev=>{tip.innerHTML=`<div class="tt">${fmtT(p.x)}</div>R <b>${p.R}</b> · T <b>${p.T}</b> · N <b>${p.N}</b> km<br><span class="tt">range ${p.d} km</span>`;tip.style.opacity=1;
      const bx=box.getBoundingClientRect();let lft=(ev.clientX-bx.left)+14;if(lft+150>box.clientWidth)lft=(ev.clientX-bx.left)-160;tip.style.left=lft+"px";tip.style.top=((ev.clientY-bx.top)-10)+"px";});
    c.addEventListener("mouseleave",()=>tip.style.opacity=0);svg.appendChild(c);});}
function build(){const m=DATA.meta,s=DATA.summary;
  document.title=m.title;document.getElementById("h1").textContent=m.title;
  document.getElementById("lede").innerHTML=m.subtitle;
  document.getElementById("legend").innerHTML=
    `<span class="chip"><span class="sw" style="background:var(--prim)"></span>${m.primId} · ${m.primName}&nbsp;<small>primary</small></span>`+
    `<span class="chip"><span class="sw" style="background:var(--sec)"></span>${m.secId} · ${m.secName}&nbsp;<small>secondary</small></span>`;
  document.getElementById("stats").innerHTML=[
    {k:"Closest approach",v:s.d_min<10?s.d_min.toFixed(2):s.d_min.toFixed(0),u:"km",c:"crit"},
    {k:"Window",v:fmtD(T(m.window[0])),u:"→ "+fmtD(T(m.window[1])),c:""},
    {k:"Separation · end",v:s.d_last<10?s.d_last.toFixed(2):s.d_last.toFixed(0),u:"km",c:""},
    {k:"Primary Δaltitude",v:s.altP_span.toFixed(0),u:"km span",c:"prim"},
    {k:"Secondary Δaltitude",v:s.altS_span.toFixed(0),u:"km span",c:"sec"},
  ].map(x=>`<div class="stat ${x.c}"><div class="k">${x.k}</div><div class="v">${x.v} <small>${x.u}</small></div></div>`).join("");
  const rel=DATA.rel.map(p=>({...p,x:T(p.t)}));
  const markers=(m.events||[]).map(e=>({x:T(e.t),color:e.color,label:e.label}));
  let distLog=true;
  const drawDist=()=>lineChart(document.getElementById("c_dist"),{h:320,log:distLog,logmin:0.1,ylabel:"RANGE (km)",markers,tipfmt:v=>v.toFixed(2)+" km",
    series:[{name:"range",color:'--prim',pts:rel.map(p=>({x:p.x,y:p.d})),dots:true,dotEvery:Math.max(1,Math.floor(rel.length/130)),w:1.6}]});
  drawDist();const seg=()=>{document.getElementById("segLog").setAttribute("aria-pressed",distLog);document.getElementById("segLin").setAttribute("aria-pressed",!distLog);};
  document.getElementById("segLog").onclick=()=>{distLog=true;seg();drawDist();};document.getElementById("segLin").onclick=()=>{distLog=false;seg();drawDist();};
  const maxT=Math.max(...rel.map(p=>Math.abs(p.T))),maxR=Math.max(...rel.map(p=>Math.abs(p.R))),maxN=Math.max(...rel.map(p=>Math.abs(p.N)));
  document.getElementById("rtnnote").textContent=`Axes independent — |T|≤${maxT.toFixed(0)} km vs |R|≤${maxR.toFixed(1)}, |N|≤${maxN.toFixed(1)} km.`;
  rtnChart(document.getElementById("c_rtn"),rel);
  lineChart(document.getElementById("c_rr"),{h:236,ylabel:"RANGE-RATE (km/s)",markers,tipfmt:v=>v.toFixed(4),series:[{name:"ṙ",color:'--sec',pts:rel.map(p=>({x:p.x,y:p.rr})),w:1.5,zero:0}]});
  const aP=DATA.altP.map(p=>({x:T(p.t),y:p.a})),aS=DATA.altS.map(p=>({x:T(p.t),y:p.a}));
  lineChart(document.getElementById("c_alt"),{h:300,ylabel:"MEAN ALTITUDE (km)",markers,tipfmt:v=>v.toFixed(2)+" km",
    series:[{name:m.primName,color:'--prim',pts:aP,dots:true,dotEvery:Math.max(1,Math.floor(aP.length/140)),r:1.7,w:1.4},
            {name:m.secName,color:'--sec',pts:aS,dots:true,dotEvery:Math.max(1,Math.floor(aS.length/140)),r:1.7,w:1.4}]});
  const tl=m.timeline||[];document.getElementById("tlpanel").style.display=tl.length?"":"none";
  document.getElementById("tl").innerHTML=tl.map(r=>`<div class="tlrow ${r.c}"><div class="tldate">${r.d}</div><div class="tltxt">${r.t}</div></div>`).join("");
  document.getElementById("foot").innerHTML=`<b>METHOD.</b> Both objects propagated to a common clock with SGP4, each state from its nearest Space-Track elset; relative position in the primary's RTN frame; range-rate = d̂·Δv; altitude = a−R⊕.<br>`+
    `<b>CAVEAT.</b> TLE/SGP4 positions carry ~1–5 km uncertainty (largest along-track); sub-km ranges sit within that noise floor — a geometry reconstruction, not an operational Pc.<br>`+
    `<b>DATA.</b> ${s.n} samples @ ${s.step_min}-min · ${fmtT(T(m.window[0]))} → ${fmtT(T(m.window[1]))}.`;}
const root=document.documentElement;
document.getElementById("themeBtn").onclick=()=>{const cur=root.getAttribute("data-theme")||(matchMedia("(prefers-color-scheme:dark)").matches?"dark":"light");root.setAttribute("data-theme",cur==="dark"?"light":"dark");setTimeout(build,20);};
build();let rt;addEventListener("resize",()=>{clearTimeout(rt);rt=setTimeout(build,150);});
</script>"""


if __name__ == "__main__":
    main()
