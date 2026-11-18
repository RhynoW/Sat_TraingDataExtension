/* Conjunction & Maneuver Lab — RPO 控制分頁（第二階段 Sprint 3）。依賴 lab.js（I18N、t、tpl、$、fmt、setupCanvas、download、postJson、status）與 lab_maneuver.js（mAxes、mLegend）。 */
'use strict';

Object.assign(I18N.zh, {
  tab_rpo: 'RPO 控制', r_case: '示範案例', r_keep: '安全區半徑（m）', r_close: '接近速度上限（m/s）', r_corr: '走廊半角（°）',
  r_axis: '走廊軸向', r_fault: '故障注入：通訊中斷時刻（秒，空白＝不注入）', r_trigger: '中斷觸發時間（秒）', r_orbits: '被動安全圈數',
  r_run: '執行 RPO 模擬', r_done: '完成：{n} 次脈衝，耗時 {s} 秒',
  r_note: '同一控制律分別在 HCW 線性模型（設計）與 GCRF 數值傳播（J2–J4＋差分阻力，閉迴路重播）中執行；全時間軸檢查安全區、接近速度與走廊；每個控制段預存撤離脈衝並以 5 種執行誤差情境驗證被動安全。',
  rs_pass: '通過：非線性重播無違規、預存撤離脈衝全部安全', rs_fail: '未通過', rs_invalid_design: '設計不可行', rs_invalid_scenario: '場景驗證失敗',
  rr_nominal_violations: '標稱重播有安全違規', rr_abort_unsafe: '部分預存撤離脈衝不安全', rr_fault_abort_unsafe: '故障注入後撤離不安全',
  rr_transfer_dv_exceeds: '轉移脈衝超過單次上限（轉移時間可能接近整數週期）', rr_transfer_singular: 'HCW 轉移矩陣奇異（轉移時間為整數週期）',
  rk_dv: '總 Δv（設計／重播）', rk_burns: '脈衝數（設計／重播）', rk_min: '最近距離', rk_close: '最大接近速度', rk_abort: '撤離表安全', rk_fault: '故障注入',
  rk_fuel: '推進劑', rk_elapsed: '計算時間', fault_safe: '撤離安全', fault_unsafe: '撤離不安全', fault_na: '未注入',
  rd_tr: '相對軌跡（T–R 平面，目標星在原點）', rd_dist: '距離與安全區', rd_close: '接近速度', rd_abort: '預存撤離脈衝：非線性最差距離',
  rd_3d: '3D 相對軌跡（拖曳旋轉、滾輪縮放）', rd_appl: 'HCW 適用前提與假設',
  rl_design: 'HCW 設計', rl_replay: '非線性重播', rl_keep: '安全區', rl_corr: '走廊', rl_burn: '脈衝', rl_coast: '中斷滑行', rl_abort: '撤離軌跡',
  rl_limit: '上限', rl_safe: '安全', rl_unsafe: '不安全',
  rc_idx: '#', rc_type: '段落', rc_label: '說明', rc_start: '開始 s', rc_end: '結束 s', rc_arr: '到達誤差 m（HCW／重播）', rc_burns: '脈衝', rc_dv: 'Δv m/s',
  rc_viol: '違規', seg_transfer: '轉移', seg_hold: '駐留', seg_fly_around: '繞飛',
  vt_keep_out: '安全區', vt_closing_speed: '接近速度', vt_corridor: '走廊',
  kv_ecc: '目標偏心率', kv_range: '最大相對距離', kv_frac: '距離／軌道半徑', kv_hcw: 'HCW 適用', kv_notes: '假設', kv_fault: '故障注入',
  fault_txt: '中斷 {a} s → 觸發 {b} s，執行 {c} s 預存脈衝 {d} m/s；滑行最近 {e} m；撤離後最差 {f} m',
  case_base_nominal: '基準：V-bar 接近', case_fault_comm_loss: '故障注入：通訊中斷', case_keep_out_violation: '安全區違規',
  case_corridor_violation: '走廊違規（繞飛納入走廊）', case_closing_speed_violation: '接近速度違規', case_abort_dv_too_small: '撤離 Δv 上限不足',
  case_rbar_approach: 'R-bar 接近', case_transfer_dv_exceeds: '轉移 Δv 超限（設計不可行）', r_meta: '步長 {h} s；HCW n = {n} rad/s；撤離表 {e} 筆（每段起點＋每 {u} s）'
});
Object.assign(I18N.en, {
  tab_rpo: 'RPO control', r_case: 'Demo case', r_keep: 'Keep-out radius (m)', r_close: 'Max closing speed (m/s)', r_corr: 'Corridor half-angle (°)',
  r_axis: 'Corridor axis', r_fault: 'Fault injection: comm loss at (s; blank = none)', r_trigger: 'Loss trigger time (s)', r_orbits: 'Passive-safety orbits',
  r_run: 'Run RPO simulation', r_done: 'Done: {n} burns in {s} s',
  r_note: 'The same control law runs in the linear HCW model (design) and in GCRF numerical propagation (J2–J4 plus differential drag, closed-loop replay). Keep-out, closing speed and corridor are checked over the whole timeline; an abort burn is stored for every control segment and its passive safety verified under 5 execution-error cases.',
  rs_pass: 'Pass: no violations in the nonlinear replay and every stored abort burn is safe', rs_fail: 'Fail', rs_invalid_design: 'Design infeasible', rs_invalid_scenario: 'Scenario validation failed',
  rr_nominal_violations: 'Safety violations in the nominal replay', rr_abort_unsafe: 'Some stored abort burns are unsafe', rr_fault_abort_unsafe: 'Abort after fault injection is unsafe',
  rr_transfer_dv_exceeds: 'Transfer burn exceeds the single-burn limit (duration may be close to a whole number of periods)', rr_transfer_singular: 'HCW transfer matrix singular (duration is a whole number of periods)',
  rk_dv: 'Total Δv (design / replay)', rk_burns: 'Burns (design / replay)', rk_min: 'Closest range', rk_close: 'Max closing speed', rk_abort: 'Abort table safe', rk_fault: 'Fault injection',
  rk_fuel: 'Propellant', rk_elapsed: 'Compute time', fault_safe: 'abort safe', fault_unsafe: 'abort unsafe', fault_na: 'not injected',
  rd_tr: 'Relative trajectory (T–R plane, target at origin)', rd_dist: 'Range and keep-out', rd_close: 'Closing speed', rd_abort: 'Stored abort burns: worst nonlinear range',
  rd_3d: '3D relative trajectory (drag to rotate, wheel to zoom)', rd_appl: 'HCW applicability and assumptions',
  rl_design: 'HCW design', rl_replay: 'Nonlinear replay', rl_keep: 'keep-out', rl_corr: 'corridor', rl_burn: 'burn', rl_coast: 'loss coast', rl_abort: 'abort path',
  rl_limit: 'limit', rl_safe: 'safe', rl_unsafe: 'unsafe',
  rc_idx: '#', rc_type: 'Segment', rc_label: 'Label', rc_start: 'Start s', rc_end: 'End s', rc_arr: 'Arrival error m (HCW / replay)', rc_burns: 'Burns', rc_dv: 'Δv m/s',
  rc_viol: 'Violations', seg_transfer: 'transfer', seg_hold: 'hold', seg_fly_around: 'fly-around',
  vt_keep_out: 'keep-out', vt_closing_speed: 'closing speed', vt_corridor: 'corridor',
  kv_ecc: 'Target eccentricity', kv_range: 'Max relative range', kv_frac: 'Range / orbit radius', kv_hcw: 'HCW applicable', kv_notes: 'Assumptions', kv_fault: 'Fault injection',
  fault_txt: 'Loss at {a} s → trigger {b} s; executes burn stored at {c} s ({d} m/s); closest during coast {e} m; worst after abort {f} m',
  case_base_nominal: 'Base: V-bar approach', case_fault_comm_loss: 'Fault: comm loss', case_keep_out_violation: 'Keep-out violation',
  case_corridor_violation: 'Corridor violation (fly-around in corridor)', case_closing_speed_violation: 'Closing-speed violation', case_abort_dv_too_small: 'Abort Δv limit too small',
  case_rbar_approach: 'R-bar approach', case_transfer_dv_exceeds: 'Transfer Δv exceeds limit (infeasible design)', r_meta: 'Step {h} s; HCW n = {n} rad/s; abort table {e} entries (each segment start + every {u} s)'
});
Object.assign(I18N.ja, {
  tab_rpo: 'RPO 制御', r_case: 'デモケース', r_keep: '安全域半径（m）', r_close: '接近速度上限（m/s）', r_corr: '回廊半角（°）',
  r_axis: '回廊軸', r_fault: '故障注入：通信途絶時刻（秒、空欄＝なし）', r_trigger: '途絶判定時間（秒）', r_orbits: '受動安全周回数',
  r_run: 'RPO シミュレーションを実行', r_done: '完了：インパルス {n} 回、{s} 秒',
  r_note: '同じ制御則を HCW 線形モデル（設計）と GCRF 数値伝播（J2–J4＋差分抗力、閉ループ再生）で実行する。全期間で安全域、接近速度、回廊を検査し、各制御区間に退避インパルスを事前保存して 5 種の実行誤差ケースで受動安全を検証する。',
  rs_pass: '合格：非線形再生で違反なし、保存済み退避インパルスはすべて安全', rs_fail: '不合格', rs_invalid_design: '設計が実行不能', rs_invalid_scenario: 'シナリオ検証に失敗',
  rr_nominal_violations: '標準再生で安全違反あり', rr_abort_unsafe: '一部の保存済み退避インパルスが安全でない', rr_fault_abort_unsafe: '故障注入後の退避が安全でない',
  rr_transfer_dv_exceeds: '遷移インパルスが単発上限を超過（遷移時間が整数周期に近い可能性）', rr_transfer_singular: 'HCW 遷移行列が特異（遷移時間が整数周期）',
  rk_dv: '総 Δv（設計／再生）', rk_burns: 'インパルス数（設計／再生）', rk_min: '最接近距離', rk_close: '最大接近速度', rk_abort: '退避表の安全', rk_fault: '故障注入',
  rk_fuel: '推進剤', rk_elapsed: '計算時間', fault_safe: '退避安全', fault_unsafe: '退避不安全', fault_na: '注入なし',
  rd_tr: '相対軌跡（T–R 平面、目標は原点）', rd_dist: '距離と安全域', rd_close: '接近速度', rd_abort: '保存済み退避インパルス：非線形最悪距離',
  rd_3d: '3D 相対軌跡（ドラッグで回転、ホイールで拡大縮小）', rd_appl: 'HCW 適用条件と仮定',
  rl_design: 'HCW 設計', rl_replay: '非線形再生', rl_keep: '安全域', rl_corr: '回廊', rl_burn: 'インパルス', rl_coast: '途絶中の慣性飛行', rl_abort: '退避軌跡',
  rl_limit: '上限', rl_safe: '安全', rl_unsafe: '不安全',
  rc_idx: '#', rc_type: '区間', rc_label: '説明', rc_start: '開始 s', rc_end: '終了 s', rc_arr: '到達誤差 m（HCW／再生）', rc_burns: 'インパルス', rc_dv: 'Δv m/s',
  rc_viol: '違反', seg_transfer: '遷移', seg_hold: '保持', seg_fly_around: '周回',
  vt_keep_out: '安全域', vt_closing_speed: '接近速度', vt_corridor: '回廊',
  kv_ecc: '目標の離心率', kv_range: '最大相対距離', kv_frac: '距離／軌道半径', kv_hcw: 'HCW 適用', kv_notes: '仮定', kv_fault: '故障注入',
  fault_txt: '途絶 {a} s → 判定 {b} s、{c} s 保存のインパルス {d} m/s を実行；慣性飛行中の最接近 {e} m；退避後の最悪 {f} m',
  case_base_nominal: '基準：V-bar 接近', case_fault_comm_loss: '故障注入：通信途絶', case_keep_out_violation: '安全域違反',
  case_corridor_violation: '回廊違反（周回を回廊に含める）', case_closing_speed_violation: '接近速度違反', case_abort_dv_too_small: '退避 Δv 上限不足',
  case_rbar_approach: 'R-bar 接近', case_transfer_dv_exceeds: '遷移 Δv 超過（設計不能）', r_meta: 'ステップ {h} s；HCW n = {n} rad/s；退避表 {e} 件（各区間開始＋{u} s ごと）'
});

let RSTATE = null;   // {data, yaw, pitch, zoom}
let RDEMOS = [];

function rFill(sc) {
  const L = sc.rpo_limits || {}, C = L.comm_loss || {}, F = (sc.rpo || {}).fault || {};
  $('r-keep').value = L.keep_out_m ?? 200; $('r-close').value = L.max_closing_ms ?? 0.5; $('r-corr').value = L.corridor_half_angle_deg ?? 10;
  $('r-axis').value = L.corridor_axis || '-T'; $('r-fault').value = F.comm_loss_start_s ?? ''; $('r-trigger').value = C.trigger_s ?? 600;
  $('r-orbits').value = C.safe_orbits ?? 3;
}

function rApply(sc) {
  const L = sc.rpo_limits = sc.rpo_limits || {};
  const num = id => { const x = parseFloat($(id).value); return isFinite(x) ? x : null; };
  [['keep_out_m', 'r-keep'], ['max_closing_ms', 'r-close'], ['corridor_half_angle_deg', 'r-corr']].forEach(([k, id]) => { const v = num(id); if (v !== null) L[k] = v; });
  L.corridor_axis = $('r-axis').value;
  L.comm_loss = L.comm_loss || { strategy: 'abort_to_hold' };
  if (num('r-trigger') !== null) L.comm_loss.trigger_s = num('r-trigger');
  if (num('r-orbits') !== null) L.comm_loss.safe_orbits = num('r-orbits');
  sc.rpo = sc.rpo || {};
  if (num('r-fault') !== null) sc.rpo.fault = { comm_loss_start_s: num('r-fault') }; else delete sc.rpo.fault;
  return sc;
}

async function rLoadDemos() {
  try {
    const j = await (await fetch('/api/lab/rpo/demo')).json();
    RDEMOS = j.scenarios;
    const sel = $('r-case');
    const fill = () => { const cur = sel.value || '0'; sel.innerHTML = RDEMOS.map((s, i) => `<option value="${i}">${t('case_' + s.id)}</option>`).join(''); sel.value = cur; };
    fill();
    sel.onchange = () => { const s = RDEMOS[+sel.value]; $('r-json').value = JSON.stringify(s.scenario, null, 1); rFill(s.scenario); $('r-msg').textContent = j.description; };
    sel.onchange();
    rLoadDemos.refill = fill;
  } catch (e) { /* 示範案例載入失敗不影響其他分頁 */ }
}

async function rRun() {
  const btn = $('r-run');
  let sc;
  try { sc = JSON.parse($('r-json').value); } catch (e) { $('r-msg').innerHTML = `<span class="err">JSON: ${e.message}</span>`; return; }
  rApply(sc);
  $('r-json').value = JSON.stringify(sc, null, 1);
  btn.disabled = true;
  status(t('running'));
  const t0 = performance.now();
  try {
    const j = await postJson('/api/lab/rpo', { scenario: sc });
    if (j.status === 'error') { status(tpl('failed', { e: j.error }), true); return; }
    if (j.status === 'invalid_scenario') {
      $('r-msg').innerHTML = `<span class="err">${tpl('s_invalid', { codes: j.validation.codes.join(', ') })}</span>` +
        (j.validation.messages || []).map(m => `<div class="err">${m}</div>`).join('');
      status(''); return;
    }
    $('r-msg').textContent = '';
    RSTATE = { data: j, yaw: -0.5, pitch: 0.4, zoom: 1 };
    status(tpl('r_done', { n: ((j.replay || {}).burns || []).length, s: ((performance.now() - t0) / 1000).toFixed(2) }));
    labRpoRender();
  } catch (e) {
    status(tpl('failed', { e: e.message }), true);
  } finally { btn.disabled = false; }
}

function labRpoRender() {
  if (rLoadDemos.refill) rLoadDemos.refill();
  if (!RSTATE || document.body.dataset.pane !== 'rpo') return;
  const d = RSTATE.data;
  $('r-results').style.display = 'block';
  const cls = d.status === 'pass' ? 'ok' : d.status === 'fail' ? 'warn' : 'crit';
  const rs = (d.reasons || []).map(r => t('rr_' + r)).concat(d.reason ? [t('rr_' + d.reason) + (d.segment !== undefined ? `（#${d.segment}，${d.stage}）` : '')] : []);
  $('r-banner').className = 'banner ' + cls;
  $('r-banner').innerHTML = `<b>${t('rs_' + d.status)}</b> <span class="hint">${d.status}${d.reason ? ' · ' + d.reason : ''}${(d.reasons || []).length ? ' · ' + d.reasons.join(', ') : ''}</span>` +
    (rs.length ? `<div>${rs.join('；')}</div>` : '');
  if (!d.replay) { ['r-kpis', 'r-detail', 'r-thead', 'r-tbody'].forEach(id => { $(id).innerHTML = ''; }); $('r-meta').textContent = ''; return; }
  const R = d.replay, D = d.design, A = d.abort, F = d.fault;
  const faultTxt = !F ? t('fault_na') : F.status !== 'evaluated' ? F.status : (F.safe ? t('fault_safe') : t('fault_unsafe')) + `（${fmt(F.nl_worst_m, 0)} m）`;
  $('r-kpis').innerHTML = [
    [`${fmt(D.total_dv_ms, 3)} / ${fmt(R.total_dv_ms, 3)} m/s`, t('rk_dv')], [`${D.burns.length} / ${R.burns.length}`, t('rk_burns')],
    [fmt(R.min_dist_m, 1) + ' m', t('rk_min')], [fmt(R.max_closing_ms, 3) + ' m/s', t('rk_close')],
    [`${d.checks.abort_entries_safe} / ${d.checks.abort_entries}`, t('rk_abort')], [faultTxt, t('rk_fault')],
    [R.propellant_kg !== null ? fmt(R.propellant_kg * 1000, 0) + ' g' : '—', t('rk_fuel')], [fmt((d.timing || {}).elapsed_s, 2) + ' s', t('rk_elapsed')]
  ].map(([v, l]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
  $('r-meta').textContent = tpl('r_meta', { h: d.step_s, n: D.n_rad_s.toExponential(4), e: A.entries.length, u: A.update_s });
  const ap = d.applicability;
  const kv = [[t('kv_ecc'), ap.target_eccentricity.toExponential(2)], [t('kv_range'), fmt(ap.max_range_m, 0) + ' m'],
    [t('kv_frac'), ap.range_frac.toExponential(2)], [t('kv_hcw'), ap.hcw_applicable ? t('yes') : t('no')]];
  if (F && F.status === 'evaluated') kv.push([t('kv_fault'), tpl('fault_txt', { a: F.comm_loss_start_s, b: F.trigger_t_s, c: F.stored_entry_t_s, d: fmt(F.dv_ms, 3), e: fmt(F.coast_min_dist_m, 0), f: fmt(F.nl_worst_m, 0) })]);
  kv.push([t('kv_notes'), d.notes.join('；')]);
  $('r-detail').innerHTML = `
    <div class="card"><h3>${t('rd_tr')}</h3><canvas id="rc-tr" height="380"></canvas></div>
    <div class="card"><h3>${t('rd_3d')}</h3><canvas id="rc-3d" class="drag" height="380"></canvas></div>
    <div class="card"><h3>${t('rd_dist')}</h3><canvas id="rc-dist" height="240"></canvas></div>
    <div class="card"><h3>${t('rd_close')}</h3><canvas id="rc-close" height="240"></canvas></div>
    <div class="card"><h3>${t('rd_abort')}</h3><canvas id="rc-abort" height="240"></canvas></div>
    <div class="card"><h3>${t('rd_appl')}</h3><dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl></div>`;
  rDrawTR(d); rDraw3d(d); rDrawSeries(d, 'rc-dist'); rDrawSeries(d, 'rc-close'); rDrawAbort(d); rSetup3d(d);
  const cols = ['rc_idx', 'rc_type', 'rc_label', 'rc_start', 'rc_end', 'rc_arr', 'rc_burns', 'rc_dv', 'rc_viol'];
  $('r-thead').innerHTML = cols.map((c, i) => `<th class="${i === 1 || i === 2 || i === 8 ? 'l' : ''}">${t(c)}</th>`).join('');
  $('r-tbody').innerHTML = R.segments.map((s, i) => {
    const ds = D.segments[i] || {};
    const vs = R.violations.filter(v => v.segment === i).map(v => `<span class="chk n">${t('vt_' + v.type)} ${fmt(v.worst, v.type === 'corridor' ? 1 : 3)}（${v.count}）</span>`).join(' ');
    const arr = s.arrival_error_m !== undefined ? `${fmt(ds.arrival_error_m, 2)} / ${fmt(s.arrival_error_m, 2)}` : '—';
    return `<tr><td>${i}</td><td class="l">${t('seg_' + s.type)}</td><td class="l">${s.label || ''}</td><td>${s.start_s}</td><td>${s.end_s}</td><td>${arr}</td><td>${s.n_burns}</td><td>${fmt(s.dv_ms, 3)}</td><td class="l">${vs || '<span class="chk y">✓</span>'}</td></tr>`;
  }).join('');
}
window.labRpoRender = labRpoRender;

function rDrawTR(d) {
  const cv = $('rc-tr'); if (!cv) return;
  const { ctx, w, h } = setupCanvas(cv);
  const L = d.limits, R = d.replay.timeline.rtn_m, Dd = d.design.timeline.rtn_m, F = d.fault;
  const pts = R.concat(Dd, (F && F.abort_path_rtn_m) || [], (F && F.coast_path_rtn_m) || []);
  const ext = Math.max(L.keep_out_m * 1.5, ...pts.map(p => Math.max(Math.abs(p[0]), Math.abs(p[1])))) * 1.08;
  const cx = w / 2, cy = h / 2, k = Math.min(w, h) / 2 / ext;
  const X = p => cx + p[1] * k, Y = p => cy - p[0] * k;
  ctx.strokeStyle = '#21262d'; ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(w, cy); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();
  ctx.fillStyle = '#8b949e'; ctx.font = '11px Segoe UI, sans-serif';
  ctx.fillText('+T (V-bar)', w - 70, cy - 6); ctx.fillText('+R', cx + 6, 14); ctx.fillText(`±${fmt(ext, 0)} m`, 6, h - 8);
  // 走廊（軸向在 T–R 平面時畫扇形）
  const ax = { '+R': [1, 0], '-R': [-1, 0], '+T': [0, 1], '-T': [0, -1] }[L.corridor_axis];
  if (ax) {
    const ang = Math.atan2(ax[0], ax[1]), half = L.corridor_half_angle_deg * Math.PI / 180, rr = L.corridor_range_m * k;
    ctx.fillStyle = 'rgba(210,153,34,0.10)'; ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, rr, -(ang + half), -(ang - half)); ctx.closePath(); ctx.fill();
  }
  ctx.strokeStyle = '#f85149'; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.arc(cx, cy, L.keep_out_m * k, 0, 2 * Math.PI); ctx.stroke(); ctx.setLineDash([]);
  const path = (arr, col, wd, dash) => { if (!arr || !arr.length) return; ctx.strokeStyle = col; ctx.lineWidth = wd; ctx.setLineDash(dash || []); ctx.beginPath(); arr.forEach((p, i) => i ? ctx.lineTo(X(p), Y(p)) : ctx.moveTo(X(p), Y(p))); ctx.stroke(); ctx.setLineDash([]); };
  path(Dd, '#8b949e', 1.2, [5, 4]);
  path(R, '#58a6ff', 1.6);
  if (F && F.status === 'evaluated') { path(F.coast_path_rtn_m, '#d29922', 1.6); path(F.abort_path_rtn_m, '#f85149', 1.4); }
  const tl = d.replay.timeline;
  d.replay.burns.forEach(b => {
    let i = tl.t_s.findIndex(x => x >= b.t_s); if (i < 0) i = tl.t_s.length - 1;
    const p = tl.rtn_m[i]; ctx.fillStyle = '#bc8cff'; ctx.beginPath(); ctx.arc(X(p), Y(p), 2.6, 0, 2 * Math.PI); ctx.fill();
  });
  ctx.fillStyle = '#e6edf3'; ctx.beginPath(); ctx.arc(cx, cy, 3, 0, 2 * Math.PI); ctx.fill();
  mLegend(ctx, [['#8b949e', t('rl_design')], ['#58a6ff', t('rl_replay')], ['#bc8cff', t('rl_burn')], ['#f85149', t('rl_keep')], ['#d29922', t('rl_corr') + ' / ' + t('rl_coast')], ['#f85149', t('rl_abort')]], 8, 18);
}

function rDrawSeries(d, id) {
  const cv = $(id); if (!cv) return;
  const { ctx, w, h } = setupCanvas(cv);
  const tl = d.replay.timeline, L0 = 50, R0 = 10, T0 = 10, B0 = 24, isDist = id === 'rc-dist';
  const ys = isDist ? tl.dist_m : tl.closing_ms;
  const lim = isDist ? d.limits.keep_out_m : d.limits.max_closing_ms;
  const lo = isDist ? 0 : Math.min(0, ...ys), hi = Math.max(...ys, lim) * 1.1;
  const t1 = tl.t_s[tl.t_s.length - 1] || 1;
  const X = s => L0 + (w - L0 - R0) * s / t1, Y = v => T0 + (h - T0 - B0) * (1 - (v - lo) / (hi - lo || 1));
  mAxes(ctx, w, h, L0, R0, T0, B0);
  for (let i = 0; i <= 4; i++) { const v = lo + (hi - lo) * i / 4; ctx.fillText(isDist ? v.toFixed(0) : v.toFixed(2), 4, Y(v) + 4); }
  for (let s = 0; s <= t1; s += 3600) ctx.fillText((s / 3600).toFixed(0) + 'h', X(s) - 6, h - 8);
  ctx.strokeStyle = '#30363d';
  d.replay.segments.forEach(s => { ctx.beginPath(); ctx.moveTo(X(s.start_s), T0); ctx.lineTo(X(s.start_s), h - B0); ctx.stroke(); });
  ctx.strokeStyle = '#f85149'; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(L0, Y(lim)); ctx.lineTo(w - R0, Y(lim)); ctx.stroke(); ctx.setLineDash([]);
  if (!isDist) { const rr = d.limits.closing_range_m; ctx.fillStyle = '#8b949e'; ctx.fillText(`${t('rl_limit')}（< ${rr} m）`, w - R0 - 110, Y(lim) - 4); }
  ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 1.3; ctx.beginPath();
  ys.forEach((v, i) => { const x = X(tl.t_s[i]), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
}

function rDrawAbort(d) {
  const cv = $('rc-abort'); if (!cv) return;
  const { ctx, w, h } = setupCanvas(cv);
  const E = d.abort.entries, ko = d.limits.keep_out_m, L0 = 50, R0 = 10, T0 = 10, B0 = 24;
  const t1 = Math.max(...E.map(e => e.t_s), 1), hi = Math.max(...E.map(e => e.nl_worst_m), ko) * 1.15;
  const X = s => L0 + (w - L0 - R0) * s / t1, Y = v => T0 + (h - T0 - B0) * (1 - v / hi);
  mAxes(ctx, w, h, L0, R0, T0, B0);
  for (let i = 0; i <= 4; i++) { const v = hi * i / 4; ctx.fillText(v.toFixed(0), 4, Y(v) + 4); }
  for (let s = 0; s <= t1; s += 3600) ctx.fillText((s / 3600).toFixed(0) + 'h', X(s) - 6, h - 8);
  ctx.strokeStyle = '#f85149'; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(L0, Y(ko)); ctx.lineTo(w - R0, Y(ko)); ctx.stroke(); ctx.setLineDash([]);
  E.forEach(e => {
    const x = X(e.t_s);
    ctx.strokeStyle = '#484f58'; ctx.beginPath(); ctx.moveTo(x, Y(Math.min(...e.nl_min_dist_m))); ctx.lineTo(x, Y(Math.max(...e.nl_min_dist_m))); ctx.stroke();
    ctx.fillStyle = e.safe ? '#3fb950' : '#d29922'; ctx.beginPath(); ctx.arc(x, Y(e.nl_worst_m), 3.5, 0, 2 * Math.PI); ctx.fill();
  });
  mLegend(ctx, [['#3fb950', t('rl_safe')], ['#d29922', t('rl_unsafe')], ['#f85149', t('rl_keep')]], w - R0 - 6, T0 + 14, true);
}

function rSetup3d(d) {
  const cv = $('rc-3d'); if (!cv) return;
  let drag = null;
  cv.onpointerdown = e => { drag = { x: e.clientX, y: e.clientY }; cv.setPointerCapture(e.pointerId); };
  cv.onpointermove = e => { if (!drag) return; RSTATE.yaw += (e.clientX - drag.x) * 0.01; RSTATE.pitch = Math.max(-1.5, Math.min(1.5, RSTATE.pitch + (e.clientY - drag.y) * 0.01)); drag = { x: e.clientX, y: e.clientY }; rDraw3d(d); };
  cv.onpointerup = () => { drag = null; };
  cv.onwheel = e => { e.preventDefault(); RSTATE.zoom = Math.max(0.2, Math.min(20, RSTATE.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15))); rDraw3d(d); };
}

function rDraw3d(d) {
  const cv = $('rc-3d'); if (!cv) return;
  const { ctx, w, h } = setupCanvas(cv);
  const S = RSTATE, cy_ = Math.cos(S.yaw), sy = Math.sin(S.yaw), cp = Math.cos(S.pitch), sp = Math.sin(S.pitch);
  // RTN → 繪圖座標：x = T、y = N、z = R
  const rot = p => { const x = p[1], y = p[2], z = p[0]; const x1 = cy_ * x - sy * y, y1 = sy * x + cy_ * y; return [x1, cp * y1 - sp * z, sp * y1 + cp * z]; };
  const R = d.replay.timeline.rtn_m, F = d.fault, ko = d.limits.keep_out_m;
  const all = R.concat((F && F.abort_path_rtn_m) || []);
  const ext = Math.max(ko * 1.5, ...all.flatMap(p => p.map(Math.abs)));
  const k = Math.min(w, h) / 2 / ext * 0.85 * S.zoom, cx = w / 2, cyc = h / 2;
  const P = p => { const q = rot(p); return [cx + k * q[0], cyc - k * q[2]]; };
  ctx.font = '11px Segoe UI, sans-serif';
  [['R', [ext * 0.5, 0, 0]], ['T', [0, ext * 0.5, 0]], ['N', [0, 0, ext * 0.5]]].forEach(([lab, v]) => {
    const a = P([0, 0, 0]), b = P(v); ctx.strokeStyle = '#484f58'; ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    ctx.fillStyle = '#8b949e'; ctx.fillText(lab, b[0] + 3, b[1] - 3);
  });
  ctx.strokeStyle = 'rgba(248,81,73,0.6)';
  [[0, 1], [1, 2], [0, 2]].forEach(([i, j]) => {
    ctx.beginPath();
    for (let s = 0; s <= 48; s++) { const a = s / 48 * 2 * Math.PI, p = [0, 0, 0]; p[i] = ko * Math.cos(a); p[j] = ko * Math.sin(a); const [x, y] = P(p); s ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
    ctx.stroke();
  });
  const path = (arr, col, wd) => { if (!arr || !arr.length) return; ctx.strokeStyle = col; ctx.lineWidth = wd; ctx.beginPath(); arr.forEach((p, i) => { const [x, y] = P(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke(); };
  path(d.design.timeline.rtn_m, '#6e7681', 1);
  path(R, '#58a6ff', 1.6);
  if (F && F.status === 'evaluated') { path(F.coast_path_rtn_m, '#d29922', 1.6); path(F.abort_path_rtn_m, '#f85149', 1.3); }
  const o = P([0, 0, 0]); ctx.fillStyle = '#e6edf3'; ctx.beginPath(); ctx.arc(o[0], o[1], 3, 0, 2 * Math.PI); ctx.fill();
  ctx.fillText(`±${fmt(ext / S.zoom, 0)} m`, 6, 14);
  mLegend(ctx, [['#6e7681', t('rl_design')], ['#58a6ff', t('rl_replay')], ['#f85149', t('rl_keep') + ' / ' + t('rl_abort')], ['#d29922', t('rl_coast')]], 8, 30);
}

document.addEventListener('DOMContentLoaded', () => {
  $('r-run').onclick = rRun;
  $('r-load').onclick = () => $('r-file').click();
  $('r-file').onchange = async ev => { const f = ev.target.files[0]; if (f) { $('r-json').value = await f.text(); try { rFill(JSON.parse($('r-json').value)); } catch (e) { /* ignore */ } } };
  $('r-dl').onclick = () => RSTATE && download('rpo_result.json', JSON.stringify(RSTATE.data, null, 1), 'application/json');
  window.addEventListener('resize', () => { if (RSTATE && document.body.dataset.pane === 'rpo') labRpoRender(); });
  rLoadDemos();
});
