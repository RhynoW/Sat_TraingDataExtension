/* Conjunction & Maneuver Lab（第二階段 Sprint 1）：批次分析、場景 JSON、事件表、距離歷程、交會平面圖。 */
'use strict';

const I18N = {
  zh: {
    page_title: '會合與機動實驗室', nav_home: '返回主頁',
    subtitle: '第二階段 Sprint 2：會合事件核心與避碰決策',
    tab_batch: '批次分析', tab_scenario: '場景 JSON',
    f_primary: '主星 NORAD 編號', f_start: '起始時刻（UTC）', f_duration: '分析天數（≤ 7）', f_threshold: '篩選門檻（km）',
    f_coarse: '粗掃步長（秒）', f_hbr: '預設硬體半徑（m）', f_sig_p: '主星 RTN σ（km，逗號分隔）', f_sig_s: '次星預設 RTN σ（km）',
    f_secondaries: '次星清單：每行一個 NORAD 編號，或 CSV（表頭 norad_id,name,line1,line2,hbr_m,sigma_r_km,sigma_t_km,sigma_n_km）',
    f_demo: '示範場景', f_json: '場景 JSON（satdash.scenario/v1）',
    btn_load_csv: '載入 CSV 檔', btn_check_csv: '檢查清單', btn_run: '執行分析', btn_load_json: '載入 JSON 檔',
    btn_dl_csv: '下載事件 CSV', btn_dl_json: '下載完整 JSON',
    batch_note: '星曆：SGP4（WGS-72）轉 GCRF；搜尋：自適應細分，保證門檻內、相隔超過 1 秒的近接都會被找到；協方差：展示模式（固定 RTN σ、忽略相關項）。',
    running: '計算中…', done: '完成：{n} 個事件，耗時 {s} 秒', failed: '失敗：{e}',
    csv_ok: '可分析 {n} 顆', csv_err: '第 {line} 行 {code}：{msg}',
    k_pairs: '分析配對', k_pairs_err: '（{n} 個失敗）', k_events: '門檻內事件', k_maxpc: '最大 Pc（Foster）', k_minmiss: '最近距離', k_elapsed: '計算時間',
    c_tca: 'TCA（UTC）', c_sec: '次星', c_miss: '距離 km', c_vrel: '相對速度 km/s', c_r: 'R km', c_t: 'T km', c_n: 'N km',
    c_ang: '接近角 °', c_pcf: 'Pc Foster', c_pcc: 'Pc Chan', c_app: '適用性', c_flag: '標記',
    app_pass: '通過初步篩選', app_fail: '未通過初步篩選', app_und: '無法判定',
    d_info: '事件資訊', d_series: '距離歷程（對數刻度）', d_bplane: '交會平面（B-plane）',
    kv_tca: 'TCA', kv_miss: '最小距離', kv_vrel: '相對速度', kv_rtn: '距離 RTN 分量', kv_ang: '接近角',
    kv_pc: 'Pc（Foster／Chan）', kv_cov: '協方差', kv_app: '適用性篩選', kv_tenc: '交會時長 T_enc', kv_lin: '直線度 δ_lin',
    kv_reasons: '原因', kv_flag: '標記',
    acc_title: '數值精度與預報準確度',
    acc_body: 'TCA 與距離顯示的位數代表求根數值精度（容差 1e-6 s），不代表預報準確度。預報準確度受輸入狀態限制：公開 TLE 在 LEO 約為公里級；本頁協方差為展示假設，Pc 只在該假設下成立。',
    bp_note: '原點為主星；藍色橢圓為合併位置協方差 1σ／2σ／3σ；紅點為次星位置，紅圈為合併硬體半徑（過小時放大顯示）。',
    series_thr: '門檻', no_events: '門檻內沒有事件。全窗最近：{d} km @ {t}',
    s_invalid: '場景驗證失敗：{codes}', search_meta: '搜尋：粗掃 {c} s、最小步長 {m} s、極小值 {n} 個、評估 {e} 次',
    hbr_enlarged: '（放大顯示）'
  },
  en: {
    page_title: 'Conjunction & Maneuver Lab', nav_home: 'Home',
    subtitle: 'Phase 2 Sprint 2: conjunction core and collision-avoidance decisions',
    tab_batch: 'Batch analysis', tab_scenario: 'Scenario JSON',
    f_primary: 'Primary NORAD ID', f_start: 'Start (UTC)', f_duration: 'Days (≤ 7)', f_threshold: 'Screening threshold (km)',
    f_coarse: 'Coarse step (s)', f_hbr: 'Default hard-body radius (m)', f_sig_p: 'Primary RTN σ (km, comma separated)', f_sig_s: 'Default secondary RTN σ (km)',
    f_secondaries: 'Secondaries: one NORAD ID per line, or CSV (header norad_id,name,line1,line2,hbr_m,sigma_r_km,sigma_t_km,sigma_n_km)',
    f_demo: 'Demo scenario', f_json: 'Scenario JSON (satdash.scenario/v1)',
    btn_load_csv: 'Load CSV file', btn_check_csv: 'Check list', btn_run: 'Run analysis', btn_load_json: 'Load JSON file',
    btn_dl_csv: 'Download events CSV', btn_dl_json: 'Download full JSON',
    batch_note: 'Ephemeris: SGP4 (WGS-72) to GCRF. Search: adaptive refinement; every approach below the threshold and more than 1 s from its neighbours is found. Covariance: demo mode (fixed RTN σ, correlations ignored).',
    running: 'Computing…', done: 'Done: {n} events in {s} s', failed: 'Failed: {e}',
    csv_ok: '{n} objects ready', csv_err: 'Line {line} {code}: {msg}',
    k_pairs: 'Pairs analysed', k_pairs_err: ' ({n} failed)', k_events: 'Events below threshold', k_maxpc: 'Max Pc (Foster)', k_minmiss: 'Closest approach', k_elapsed: 'Compute time',
    c_tca: 'TCA (UTC)', c_sec: 'Secondary', c_miss: 'Miss km', c_vrel: 'Rel. speed km/s', c_r: 'R km', c_t: 'T km', c_n: 'N km',
    c_ang: 'Approach °', c_pcf: 'Pc Foster', c_pcc: 'Pc Chan', c_app: 'Applicability', c_flag: 'Flag',
    app_pass: 'Passes initial screen', app_fail: 'Fails initial screen', app_und: 'Undetermined',
    d_info: 'Event details', d_series: 'Range history (log scale)', d_bplane: 'Encounter plane (B-plane)',
    kv_tca: 'TCA', kv_miss: 'Miss distance', kv_vrel: 'Relative speed', kv_rtn: 'Miss RTN components', kv_ang: 'Approach angle',
    kv_pc: 'Pc (Foster / Chan)', kv_cov: 'Covariance', kv_app: 'Applicability screen', kv_tenc: 'Encounter duration T_enc', kv_lin: 'Rectilinearity δ_lin',
    kv_reasons: 'Reasons', kv_flag: 'Flag',
    acc_title: 'Numerical precision vs. prediction accuracy',
    acc_body: 'The digits shown for TCA and miss distance reflect root-finding precision (1e-6 s tolerance), not prediction accuracy. Prediction accuracy is limited by the input state: public TLEs are good to about a kilometre in LEO. The covariance here is a demo assumption, and Pc holds only under it.',
    bp_note: 'Origin is the primary. Blue ellipses: combined position covariance at 1σ/2σ/3σ. Red dot: secondary; red circle: combined hard-body radius (enlarged when too small to see).',
    series_thr: 'threshold', no_events: 'No events below the threshold. Closest in window: {d} km at {t}',
    s_invalid: 'Scenario validation failed: {codes}', search_meta: 'Search: coarse {c} s, min step {m} s, {n} minima, {e} evaluations',
    hbr_enlarged: ' (enlarged)'
  },
  ja: {
    page_title: '会合・軌道変更ラボ', nav_home: 'ホームへ',
    subtitle: 'フェーズ2 スプリント2：会合イベント中核と衝突回避の意思決定',
    tab_batch: 'バッチ解析', tab_scenario: 'シナリオ JSON',
    f_primary: '主衛星 NORAD 番号', f_start: '開始時刻（UTC）', f_duration: '解析日数（7 日以内）', f_threshold: 'スクリーニング閾値（km）',
    f_coarse: '粗探索ステップ（秒）', f_hbr: '既定の物体半径（m）', f_sig_p: '主衛星 RTN σ（km、カンマ区切り）', f_sig_s: '副衛星の既定 RTN σ（km）',
    f_secondaries: '副衛星リスト：1 行に NORAD 番号 1 つ、または CSV（ヘッダ norad_id,name,line1,line2,hbr_m,sigma_r_km,sigma_t_km,sigma_n_km）',
    f_demo: 'デモシナリオ', f_json: 'シナリオ JSON（satdash.scenario/v1）',
    btn_load_csv: 'CSV ファイルを読み込む', btn_check_csv: 'リストを確認', btn_run: '解析を実行', btn_load_json: 'JSON ファイルを読み込む',
    btn_dl_csv: 'イベント CSV をダウンロード', btn_dl_json: '全 JSON をダウンロード',
    batch_note: '軌道暦：SGP4（WGS-72）→ GCRF。探索：適応的細分化により、閾値以下で隣接極小から 1 秒以上離れた接近はすべて検出。共分散：デモモード（RTN σ 固定、相関無視）。',
    running: '計算中…', done: '完了：{n} 件、{s} 秒', failed: '失敗：{e}',
    csv_ok: '{n} 機を解析可能', csv_err: '{line} 行目 {code}：{msg}',
    k_pairs: '解析ペア数', k_pairs_err: '（{n} 件失敗）', k_events: '閾値内イベント', k_maxpc: '最大 Pc（Foster）', k_minmiss: '最接近距離', k_elapsed: '計算時間',
    c_tca: 'TCA（UTC）', c_sec: '副衛星', c_miss: '距離 km', c_vrel: '相対速度 km/s', c_r: 'R km', c_t: 'T km', c_n: 'N km',
    c_ang: '接近角 °', c_pcf: 'Pc Foster', c_pcc: 'Pc Chan', c_app: '適用性', c_flag: 'フラグ',
    app_pass: '初期判定を通過', app_fail: '初期判定を不通過', app_und: '判定不能',
    d_info: 'イベント詳細', d_series: '距離の推移（対数）', d_bplane: '会合平面（B-plane）',
    kv_tca: 'TCA', kv_miss: '最小距離', kv_vrel: '相対速度', kv_rtn: '距離の RTN 成分', kv_ang: '接近角',
    kv_pc: 'Pc（Foster／Chan）', kv_cov: '共分散', kv_app: '適用性判定', kv_tenc: '会合継続時間 T_enc', kv_lin: '直線性 δ_lin',
    kv_reasons: '理由', kv_flag: 'フラグ',
    acc_title: '数値精度と予測精度',
    acc_body: 'TCA と距離の表示桁数は求根の数値精度（許容誤差 1e-6 秒）を表し、予測精度ではない。予測精度は入力状態に制約され、公開 TLE は LEO で約 1 km 級。本ページの共分散はデモ用の仮定で、Pc はその仮定の下でのみ成り立つ。',
    bp_note: '原点は主衛星。青い楕円は合成位置共分散の 1σ／2σ／3σ。赤点は副衛星、赤円は合成物体半径（小さすぎる場合は拡大表示）。',
    series_thr: '閾値', no_events: '閾値内のイベントなし。期間内の最接近：{d} km（{t}）',
    s_invalid: 'シナリオ検証に失敗：{codes}', search_meta: '探索：粗 {c} 秒、最小 {m} 秒、極小 {n} 個、評価 {e} 回',
    hbr_enlarged: '（拡大表示）'
  }
};
let LANG = 'zh';
try { LANG = localStorage.getItem('lab_lang') || 'zh'; } catch (e) { /* ignore */ }
const t = k => (I18N[LANG] && I18N[LANG][k]) || I18N.zh[k] || k;
const tpl = (k, v) => t(k).replace(/\{(\w+)\}/g, (_, x) => (v && v[x] !== undefined ? v[x] : ''));
const $ = id => document.getElementById(id);

let STATE = null;        // {kind, data, events, seriesFor(ev), sel}
let SORT = { key: 'pcf', dir: -1 };

function setLang(lang) {
  if (!I18N[lang]) return;
  LANG = lang;
  try { localStorage.setItem('lab_lang', lang); } catch (e) { /* ignore */ }
  document.documentElement.lang = { zh: 'zh-Hant', en: 'en', ja: 'ja' }[lang];
  document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll('.lang-btn').forEach(b => b.classList.toggle('active', b.dataset.lang === lang));
  if (STATE) render();
  if (window.labManeuverRender) window.labManeuverRender();
}
window.setLang = setLang;

const fmtPc = p => (p === null || p === undefined) ? '—' : (p === 0 ? '0' : p.toExponential(2));
const fmt = (x, d) => (x === null || x === undefined || !isFinite(x)) ? '—' : Number(x).toFixed(d);
const status = (html, err) => { const s = $('status'); s.innerHTML = html; s.className = err ? 'err' : ''; };

function appBadge(st) {
  const cls = st === 'passes_initial_screen' ? 'b-pass' : st === 'fails_initial_screen' ? 'b-fail' : 'b-und';
  const lab = st === 'passes_initial_screen' ? t('app_pass') : st === 'fails_initial_screen' ? t('app_fail') : t('app_und');
  return `<span class="badge ${cls}">${lab}</span>`;
}

function parseSigma(s) {
  const a = s.split(/[,\s]+/).filter(Boolean).map(Number);
  return a.length === 3 && a.every(x => x > 0) ? a : null;
}

function secondariesCsv() {
  const raw = $('b-secs').value.trim();
  const first = raw.split(/\r?\n/).find(l => l.trim() && !l.trim().startsWith('#')) || '';
  if (/norad_id|line1/i.test(first)) return raw;
  return 'norad_id\n' + raw.split(/[\r\n,;\s]+/).filter(Boolean).join('\n');
}

async function postJson(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({ status: 'error', error: 'HTTP ' + r.status }));
  return j;
}

function showCsvErrors(errors, nrows) {
  const box = $('csvmsg');
  const lines = [`<div>${tpl('csv_ok', { n: nrows })}</div>`];
  (errors || []).forEach(e => lines.push(`<div class="err">${tpl('csv_err', { line: e.line, code: e.code, msg: e.message })}</div>`));
  box.innerHTML = lines.join('');
}

async function checkCsv() {
  const j = await postJson('/api/lab/csv/parse', { text: secondariesCsv() });
  showCsvErrors(j.errors, (j.rows || []).length);
}

async function runBatch() {
  const btn = $('b-run');
  const sp = parseSigma($('b-sigp').value), ss = parseSigma($('b-sigs').value);
  const startVal = $('b-start').value;
  if (!sp || !ss || !startVal) { status(tpl('failed', { e: 'σ / start' }), true); return; }
  btn.disabled = true;
  status(t('running'));
  const body = {
    primary: { norad_id: parseInt($('b-primary').value, 10) },
    secondaries_csv: secondariesCsv(),
    start: startVal.length === 16 ? startVal + ':00Z' : startVal + 'Z',
    duration_s: Math.round(parseFloat($('b-days').value) * 86400),
    threshold_km: parseFloat($('b-thr').value),
    coarse_step_s: parseFloat($('b-coarse').value),
    defaults: { hbr_m: parseFloat($('b-hbr').value), sigma_km_primary: sp, sigma_km_secondary: ss }
  };
  try {
    const j = await postJson('/api/lab/batch', body);
    if (j.csv) showCsvErrors(j.csv.errors, j.csv.n_rows);
    if (j.status !== 'ok') { status(tpl('failed', { e: j.error || JSON.stringify(j).slice(0, 200) }), true); return; }
    const seriesByNorad = {};
    j.pairs.forEach(p => { if (p.series) seriesByNorad[p.secondary_norad] = p; });
    STATE = { kind: 'batch', data: j, events: j.events.slice(), sel: null,
              pairOf: ev => seriesByNorad[ev.secondary_norad], start: j.start, threshold: j.threshold_km };
    status(tpl('done', { n: j.events.length, s: j.elapsed_s }));
    render();
  } catch (e) {
    status(tpl('failed', { e: e.message }), true);
  } finally { btn.disabled = false; }
}

async function runScenario() {
  const btn = $('s-run');
  let sc;
  try { sc = JSON.parse($('s-json').value); } catch (e) { $('s-msg').innerHTML = `<span class="err">JSON: ${e.message}</span>`; return; }
  btn.disabled = true;
  status(t('running'));
  const t0 = performance.now();
  try {
    const j = await postJson('/api/lab/scenario', sc);
    if (j.status === 'invalid_scenario') {
      $('s-msg').innerHTML = `<span class="err">${tpl('s_invalid', { codes: j.validation.codes.join(', ') })}</span>` +
        (j.validation.messages || []).map(m => `<div class="err">${m}</div>`).join('');
      status(''); return;
    }
    if (j.status !== 'ok') { status(tpl('failed', { e: j.error }), true); return; }
    $('s-msg').innerHTML = '';
    const sec = j.objects.secondary || {};
    j.events.forEach(e => { e.secondary_norad = sec.norad_id; e.secondary_name = sec.name; });
    const pair = { series: j.series, secondary_name: sec.name, global_min: j.search.global_min };
    STATE = { kind: 'scenario', data: j, events: j.events.slice(), sel: null, pairOf: () => pair,
              start: j.start, threshold: j.threshold_km };
    status(tpl('done', { n: j.events.length, s: ((performance.now() - t0) / 1000).toFixed(2) }));
    render();
  } catch (e) {
    status(tpl('failed', { e: e.message }), true);
  } finally { btn.disabled = false; }
}

const COLS = [
  ['tca', 'c_tca', e => e.tca_utc.replace('T', ' ').replace(/\.\d+Z$/, 'Z'), e => e.tca_tau_s, 'l'],
  ['sec', 'c_sec', e => `${e.secondary_name || ''} <span class="hint">${e.secondary_norad || ''}</span>`, e => String(e.secondary_name || ''), 'l'],
  ['miss', 'c_miss', e => fmt(e.miss_km, 3), e => e.miss_km],
  ['vrel', 'c_vrel', e => fmt(e.v_rel_kms, 4), e => e.v_rel_kms],
  ['r', 'c_r', e => fmt(e.miss_rtn_km[0], 3), e => e.miss_rtn_km[0]],
  ['t', 'c_t', e => fmt(e.miss_rtn_km[1], 3), e => e.miss_rtn_km[1]],
  ['n', 'c_n', e => fmt(e.miss_rtn_km[2], 3), e => e.miss_rtn_km[2]],
  ['ang', 'c_ang', e => fmt(e.approach_angle_deg, 1), e => e.approach_angle_deg],
  ['pcf', 'c_pcf', e => fmtPc((e.pc || {}).foster), e => (e.pc || {}).foster || 0],
  ['pcc', 'c_pcc', e => fmtPc((e.pc || {}).chan), e => (e.pc || {}).chan || 0],
  ['app', 'c_app', e => appBadge(e.applicability.status), e => e.applicability.status, 'l'],
  ['flag', 'c_flag', e => e.flag, e => e.flag, 'l']
];

function render() {
  const S = STATE, d = S.data;
  $('results').style.display = 'block';
  const evs = S.events;
  const maxPc = evs.reduce((m, e) => Math.max(m, (e.pc || {}).foster || 0), 0);
  const minMiss = evs.reduce((m, e) => Math.min(m, e.miss_km), Infinity);
  let pairsTxt = '1';
  if (S.kind === 'batch') {
    const nerr = d.pairs.filter(p => p.status !== 'ok').length;
    pairsTxt = `${d.pairs.length - nerr}${nerr ? tpl('k_pairs_err', { n: nerr }) : ''}`;
  }
  $('kpis').innerHTML = [
    [pairsTxt, t('k_pairs')], [evs.length, t('k_events')], [fmtPc(maxPc), t('k_maxpc')],
    [isFinite(minMiss) ? fmt(minMiss, 3) + ' km' : '—', t('k_minmiss')],
    [S.kind === 'batch' ? d.elapsed_s + ' s' : '—', t('k_elapsed')]
  ].map(([v, l]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
  const srch = d.search || {};
  $('search-meta').textContent = tpl('search_meta', { c: srch.coarse_step_s, m: srch.min_step_s,
    n: S.kind === 'scenario' ? srch.n_minima : d.pairs.reduce((a, p) => a + (p.n_minima || 0), 0),
    e: S.kind === 'scenario' ? srch.n_evals : d.pairs.reduce((a, p) => a + (p.n_evals || 0), 0) });
  $('thead').innerHTML = COLS.map(c => `<th class="${c[4] || ''}" data-k="${c[0]}">${t(c[1])}${SORT.key === c[0] ? (SORT.dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('');
  document.querySelectorAll('#thead th').forEach(th => th.onclick = () => {
    SORT = { key: th.dataset.k, dir: SORT.key === th.dataset.k ? -SORT.dir : -1 };
    render();
  });
  const col = COLS.find(c => c[0] === SORT.key);
  evs.sort((a, b) => { const x = col[3](a), y = col[3](b); return (x > y ? 1 : x < y ? -1 : 0) * SORT.dir; });
  $('tbody').innerHTML = evs.map((e, i) => `<tr data-i="${i}" class="${S.sel === e ? 'sel' : ''}">` +
    COLS.map(c => `<td class="${c[4] || ''}">${c[2](e)}</td>`).join('') + '</tr>').join('');
  document.querySelectorAll('#tbody tr').forEach(tr => tr.onclick = () => { S.sel = evs[+tr.dataset.i]; render(); });
  if (!S.sel && evs.length) S.sel = evs[0];
  renderDetail();
}

function renderDetail() {
  const S = STATE, e = S.sel, box = $('detail');
  if (!e) {
    const gm = S.kind === 'scenario' ? S.data.search.global_min : null;
    box.innerHTML = gm ? `<div class="card"><p class="hint">${tpl('no_events', { d: fmt(gm.miss_km, 3), t: gm.tca_utc })}</p></div>` : '';
    return;
  }
  const a = e.applicability, m = a.metrics || {}, pc = e.pc || {};
  const kv = [
    [t('kv_tca'), e.tca_utc], [t('kv_miss'), fmt(e.miss_km, 4) + ' km'], [t('kv_vrel'), fmt(e.v_rel_kms, 4) + ' km/s'],
    [t('kv_rtn'), e.miss_rtn_km.map(x => fmt(x, 3)).join(' / ') + ' km'], [t('kv_ang'), fmt(e.approach_angle_deg, 2) + '°'],
    [t('kv_pc'), `${fmtPc(pc.foster)} / ${fmtPc(pc.chan)}`],
    [t('kv_cov'), `${pc.covariance_mode || '—'}（${(pc.covariance_source || []).join(', ')}）`],
    [t('kv_app'), appBadge(a.status)],
    [t('kv_tenc'), m.t_enc_s !== undefined ? fmt(m.t_enc_s, 2) + ' s' : '—'],
    [t('kv_lin'), m.delta_lin_km !== undefined ? m.delta_lin_km.toExponential(2) + ' km' : '—'],
    [t('kv_reasons'), (a.reasons || []).join(', ') || '—'], [t('kv_flag'), e.flag]
  ];
  box.innerHTML = `
    <div class="card"><h3>${t('d_info')}</h3><dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl>
      <div class="acc"><b>${t('acc_title')}</b><br>${t('acc_body')}</div></div>
    <div class="card"><h3>${t('d_series')}</h3><canvas id="cv-series" height="260"></canvas></div>
    <div class="card"><h3>${t('d_bplane')}</h3><canvas id="cv-bp" height="300"></canvas><p class="hint" id="bp-note">${t('bp_note')}</p></div>`;
  drawSeries(S.pairOf(e), e);
  drawBplane(e);
}

function setupCanvas(cv) {
  const dpr = window.devicePixelRatio || 1, w = cv.clientWidth, h = cv.height;
  cv.width = w * dpr; cv.height = h * dpr; cv.style.height = h + 'px';
  const ctx = cv.getContext('2d');
  ctx.scale(dpr, dpr);
  return { ctx, w, h };
}

function drawSeries(pair, sel) {
  const cv = $('cv-series');
  if (!cv || !pair || !pair.series) return;
  const { ctx, w, h } = setupCanvas(cv);
  const d = pair.series.d_km, step = pair.series.step_s, n = d.length, T = step * (n - 1);
  const L = 54, R = 10, Tp = 10, B = 26;
  const evs = STATE.events.filter(e => STATE.pairOf(e) === pair);
  const lo = Math.max(1e-3, Math.min(STATE.threshold, ...d, ...evs.map(e => e.miss_km)) * 0.5);
  const hi = Math.max(...d, STATE.threshold) * 1.2;
  const ly0 = Math.log10(lo), ly1 = Math.log10(hi);
  const X = s => L + (w - L - R) * s / T, Y = v => Tp + (h - Tp - B) * (1 - (Math.log10(Math.max(v, lo)) - ly0) / (ly1 - ly0));
  ctx.font = '11px Segoe UI, sans-serif';
  ctx.strokeStyle = '#21262d'; ctx.fillStyle = '#8b949e'; ctx.lineWidth = 1;
  for (let p = Math.ceil(ly0); p <= Math.floor(ly1); p++) {
    const y = Y(10 ** p);
    ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(w - R, y); ctx.stroke();
    ctx.fillText(p >= 0 ? String(10 ** p) : (10 ** p).toFixed(-p), 4, y + 4);
  }
  const days = T / 86400;
  const tick = days > 2 ? 86400 : days > 0.5 ? 21600 : 3600;
  for (let s = 0; s <= T + 1; s += tick) {
    ctx.beginPath(); ctx.moveTo(X(s), Tp); ctx.lineTo(X(s), h - B); ctx.stroke();
    ctx.fillText((tick >= 86400 ? (s / 86400).toFixed(0) + 'd' : (s / 3600).toFixed(0) + 'h'), X(s) - 8, h - 8);
  }
  ctx.strokeStyle = '#d29922'; ctx.setLineDash([4, 3]);
  ctx.beginPath(); ctx.moveTo(L, Y(STATE.threshold)); ctx.lineTo(w - R, Y(STATE.threshold)); ctx.stroke();
  ctx.setLineDash([]); ctx.fillStyle = '#d29922'; ctx.fillText(t('series_thr'), w - R - 40, Y(STATE.threshold) - 4);
  // 等間隔取樣抓不到窄谷：把事件的真正極小值（TCA, 距離）併入點列再畫線
  const pts = d.map((v, i) => [i * step, v]).concat(evs.map(e => [e.tca_tau_s, e.miss_km])).sort((p, q) => p[0] - q[0]);
  ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 1.3; ctx.beginPath();
  pts.forEach(([s, v], i) => { const x = X(s), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke();
  evs.forEach(e => {
    ctx.fillStyle = e === sel ? '#f85149' : '#e6edf3';
    ctx.beginPath(); ctx.arc(X(e.tca_tau_s), Y(e.miss_km), e === sel ? 4.5 : 2.5, 0, 2 * Math.PI); ctx.fill();
  });
}

function drawBplane(e) {
  const cv = $('cv-bp');
  if (!cv || !e.bplane) return;
  const { ctx, w, h } = setupCanvas(cv);
  const [mx, my] = e.bplane.miss_km, C = e.bplane.cov_km2;
  const a = C[0][0], b = C[0][1], c = C[1][1];
  const md = 0.5 * (a + c), dd = Math.sqrt(0.25 * (a - c) ** 2 + b * b);
  const l1 = md + dd, l2 = Math.max(md - dd, 0), th = 0.5 * Math.atan2(2 * b, a - c);
  const ext = Math.max(3 * Math.sqrt(l1), Math.abs(mx) * 1.2, Math.abs(my) * 1.2, 1e-3);
  const cx = w / 2, cy = h / 2, k = Math.min(w, h) / 2 / ext * 0.92;
  ctx.strokeStyle = '#21262d'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(w, cy); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();
  ctx.fillStyle = '#8b949e'; ctx.font = '11px Segoe UI, sans-serif';
  ctx.fillText(`±${ext.toPrecision(3)} km`, 6, 14);
  [1, 2, 3].forEach(s => {
    ctx.strokeStyle = `rgba(88,166,255,${1.0 - 0.25 * s})`;
    ctx.beginPath(); ctx.ellipse(cx, cy, s * Math.sqrt(l1) * k, s * Math.sqrt(l2) * k, -th, 0, 2 * Math.PI); ctx.stroke();
  });
  const px = cx + mx * k, py = cy - my * k;
  const hbr = (e.pc || {}).hbr_km || 0;
  let rr = hbr * k, enlarged = false;
  if (rr < 4) { rr = 4; enlarged = true; }
  ctx.strokeStyle = '#f85149'; ctx.beginPath(); ctx.arc(px, py, rr, 0, 2 * Math.PI); ctx.stroke();
  ctx.fillStyle = '#f85149'; ctx.beginPath(); ctx.arc(px, py, 2, 0, 2 * Math.PI); ctx.fill();
  ctx.fillStyle = '#e6edf3'; ctx.beginPath(); ctx.arc(cx, cy, 2.5, 0, 2 * Math.PI); ctx.fill();
  if (enlarged) $('bp-note').textContent = t('bp_note') + t('hbr_enlarged');
}

function download(name, text, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const aEl = document.createElement('a');
  aEl.href = url; aEl.download = name; document.body.appendChild(aEl); aEl.click(); aEl.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

async function downloadCsv() {
  if (!STATE) return;
  const evs = STATE.events.map(e => ({ ...e, primary_norad: e.primary_norad || (STATE.data.objects || {}).primary?.norad_id }));
  const r = await fetch('/api/lab/batch.csv', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ events: evs }) });
  download('conjunction_events.csv', await r.text(), 'text/csv;charset=utf-8');
}

async function loadDemos() {
  try {
    const j = await (await fetch('/api/lab/demo')).json();
    const sel = $('s-demo');
    sel.innerHTML = j.scenarios.map((s, i) => `<option value="${i}">${s.id}</option>`).join('');
    const show = () => { const s = j.scenarios[+sel.value]; $('s-json').value = JSON.stringify(s.scenario, null, 1); $('s-msg').textContent = s.description; };
    sel.onchange = show; show();
  } catch (e) { /* 示範場景載入失敗不影響批次分析 */ }
}

function init() {
  const now = new Date(Date.now() - (Date.now() % 60000));
  $('b-start').value = now.toISOString().slice(0, 16);
  document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'pane-' + b.dataset.pane));
    document.body.dataset.pane = b.dataset.pane;
    if (b.dataset.pane === 'maneuver' && window.labManeuverRender) window.labManeuverRender();
  });
  $('b-run').onclick = runBatch;
  $('b-check').onclick = checkCsv;
  $('b-load').onclick = () => $('b-file').click();
  $('b-file').onchange = async ev => { const f = ev.target.files[0]; if (f) { $('b-secs').value = await f.text(); checkCsv(); } };
  $('s-run').onclick = runScenario;
  $('s-load').onclick = () => $('s-file').click();
  $('s-file').onchange = async ev => { const f = ev.target.files[0]; if (f) $('s-json').value = await f.text(); };
  $('dl-csv').onclick = downloadCsv;
  $('dl-json').onclick = () => STATE && download('lab_result.json', JSON.stringify(STATE.data, null, 1), 'application/json');
  window.addEventListener('resize', () => { if (STATE && STATE.sel) renderDetail(); });
  setLang(LANG);
  loadDemos();
}
document.addEventListener('DOMContentLoaded', init);
