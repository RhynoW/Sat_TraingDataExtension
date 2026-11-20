'use strict';
// 地球儀大量衛星的瀏覽器端 SGP4（Web Worker，不占用畫面執行緒）。
// 主程式 globe.js 送 {type:'init', tles:[[line1,line2],…]} 一次，之後每秒送 {type:'prop', t:毫秒}；
// 回傳 {type:'pos', t, buf}：Float64Array（每顆 x,y,z，地固座標 ECEF，公尺；失效或已再入為 NaN）。
importScripts('/static/vendor/satellite/satellite.min.js');

const RE_KM = 6378.137;
const MAX_R_KM = RE_KM + 500000;   // 同伺服器端的高度上限檢查，排除發散的 TLE
let recs = [];

self.onmessage = (e) => {
  const m = e.data;
  if (m.type === 'init') {
    recs = m.tles.map(t => {
      try { const r = satellite.twoline2satrec(t[0], t[1]); return r && !r.error ? r : null; }
      catch (_) { return null; }
    });
    return;
  }
  if (m.type !== 'prop') return;
  const n = recs.length, out = new Float64Array(n * 3);
  const d = new Date(m.t), g = satellite.gstime(d);
  for (let i = 0; i < n; i++) {
    const r = recs[i];
    let x = NaN, y = NaN, z = NaN;
    if (r) {
      try {
        const p = satellite.propagate(r, d).position;
        if (p && isFinite(p.x)) {
          const f = satellite.eciToEcf(p, g);
          const rr = Math.sqrt(f.x * f.x + f.y * f.y + f.z * f.z);
          if (rr > RE_KM && rr < MAX_R_KM) { x = f.x * 1000; y = f.y * 1000; z = f.z * 1000; }
        }
      } catch (_) { /* 個別 TLE 失效不影響其他衛星 */ }
    }
    out[i * 3] = x; out[i * 3 + 1] = y; out[i * 3 + 2] = z;
  }
  self.postMessage({ type: 'pos', t: m.t, buf: out }, [out.buffer]);
};
