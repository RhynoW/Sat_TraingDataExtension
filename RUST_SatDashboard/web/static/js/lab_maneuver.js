/* Conjunction & Maneuver Lab — 避碰決策分頁（第二階段 Sprint 2）。依賴 lab.js 的 I18N、t、tpl、$、fmt、fmtPc、setupCanvas、download、postJson、status。 */
'use strict';

Object.assign(I18N.zh, {
  tab_maneuver: '避碰決策', m_case: '示範案例', m_win_a: '機動窗起點（TCA 前分鐘）', m_win_b: '機動窗終點（TCA 前分鐘）',
  m_notice: '最短通知時間（分鐘）', m_dv: 'Δv 範圍（m/s，最小, 最大）', m_budget: 'Δv 預算（m/s）',
  m_pc: 'Pc 目標（僅傳播模式協方差採用）', m_miss: '最小距離目標（km）', m_grid: '網格（機動時刻數, Δv 量級數, 驗證上限）',
  m_ids: '二次篩選追加物體（NORAD 編號，逗號或換行分隔；由伺服器資料庫取 TLE）', m_run: '搜尋避碰方案',
  m_note: '沿跡向單脈衝：在機動窗起點取主星狀態建立不機動的參考軌跡，所有候選方案自同一軌跡分岔；線性 STM 預篩整個網格，再以非線性傳播驗證、重新搜尋 TCA、重算 Pc 並做二次篩選。',
  st_feasible_solution_found: '找到可行方案', st_no_solution_found: '在指定網格內未找到方案',
  st_infeasible_constraints: '限制條件互相衝突（不可行）', st_no_maneuver_required: '不需機動',
  st_target_not_found: '找不到目標交會事件', st_invalid_scenario: '場景驗證失敗',
  rs_notice_window_conflict: '最短通知時間之後已沒有合法的機動時刻（最早可執行時刻晚於機動窗終點）',
  rs_window_before_data_start: '機動窗落在分析起點之前，沒有可用的星曆',
  rs_no_along_track_thrust: '主星沒有沿跡向（±T）推力方向',
  rs_dv_budget_below_min_dv: 'Δv 預算小於搜尋的最小 Δv',
  rs_no_linear_candidate_met_targets: '線性預篩中沒有任何網格點達標；以下為最大 Δv 下最佳候選的驗證結果。這不代表不存在可行方案，只代表在此網格、預算與方法下未找到',
  rs_verified_candidates_failed: '線性預篩達標的候選經非線性驗證後都未通過；可放寬目標、增加驗證上限或網格密度',
  rs_reference_meets_targets: '參考軌跡（不機動）的交會已符合目標',
  rs_no_event_near_conjunction_tca: '指定的 TCA 附近（±¼ 週期）沒有門檻內的事件',
  rs_no_event_below_threshold: '分析窗內沒有門檻內的事件', rs_reference_lost: '參考軌跡上找不到目標事件',
  mk_target: '目標事件（參考軌跡）', mk_best: '建議方案', mk_after: '機動後', mk_fuel: '推進劑', mk_verified: '驗證／通過', mk_elapsed: '計算時間',
  mc_burn: '機動時刻（UTC）', mc_rel: '距 TCA（分）', mc_dir: '方向', mc_dv: 'Δv m/s', mc_lin: '線性預測距離 km', mc_miss: '機動後距離 km',
  mc_dmiss: '距離改善 km', mc_pcb: 'Pc 前', mc_pca: 'Pc 後', mc_app: '適用性', mc_da: 'Δa m', mc_dp: 'Δ週期 s', mc_fuel: '推進劑 g',
  mc_new: '新增／變近交會', mc_checks: '檢查', mc_pass: '結果',
  ck_target_found: '找到目標', ck_miss: '距離', ck_pc: 'Pc', ck_no_new_conjunction: '無新增交會',
  pass: '通過', fail: '未通過', best_tag: '建議',
  md_crit: '判定條件與涵蓋範圍', md_dvmap: '各機動時刻達標所需最小 Δv（線性預篩）', md_series: '距離歷程：參考與建議方案（對數刻度）',
  md_bplane: '交會平面：機動前後', md_3d: '3D 幾何（拖曳旋轉、滾輪縮放）', v_local: 'TCA 附近', v_global: '全域軌道',
  kv_target_tca: '目標 TCA', kv_window: '可用機動窗（UTC）', kv_earliest: '最早可執行', kv_dvs: 'Δv 搜尋範圍', kv_signs: '推力方向',
  kv_min_miss: '距離目標', kv_pc_target: 'Pc 目標', kv_pc_used: 'Pc 目標採用', kv_crit_note: '說明', kv_coverage: '二次篩選涵蓋範圍',
  kv_ref_model: '參考軌跡模型', kv_handover: '交接時刻', kv_grid: '搜尋網格', kv_ref_event: '參考事件',
  kv_unresolved: '查無 TLE 的 NORAD 編號', yes: '是', no: '否',
  grid_txt: '{t} 個時刻 × {d} 個量級 × {s} 方向 = {c} 格；網格間距 {g} s；線性達標 {p} 個時刻；驗證 {v} 個（上限 {m}）',
  dv_lbl_p: '+T（加速，抬升軌道）', dv_lbl_m: '−T（減速，降低軌道）', leg_ref: '參考（不機動）', leg_best: '建議方案',
  leg_sec: '次星', leg_burn: '機動點', min_miss_line: '距離目標', tca_lbl: 'TCA', x_rel_tca_min: '距 TCA（分）', x_rel_tca_h: '距 TCA（時）',
  bp_note2: '各自交會平面：原點為主星；藍色為機動前、綠色為機動後的合併協方差 1σ／3σ 與次星位置。',
  local_note: '座標為參考主星在參考 TCA 時的 RTN 軸（T 向右、N 向內、R 向上，km）；橘色為機動前次星相對軌跡、綠色為機動後。',
  global_note: 'GCRF；TCA 前後半個週期。機動前後的軌道差異在全域尺度下幾乎重疊，請切換到「TCA 附近」。',
  pc_cmp_no: '（假設不一致，不可直接比較）', m_ids_bad: '查無 TLE：{ids}',
  case_base_feasible: '基準：可行', case_notice_window_conflict: '通知時間衝突', case_window_before_data_start: '機動窗早於資料起點',
  case_dv_budget_below_min: 'Δv 預算不足', case_no_along_track_thrust: '沒有沿跡向推力', case_no_solution_small_dv: 'Δv 太小：網格內無解',
  case_no_maneuver_required: '已達標：不需機動', case_target_not_found: '找不到目標事件', case_demo_covariance_miss_only: '展示協方差：只用距離判定',
  case_new_conjunction_rejects_best: '二次篩選拒收最省方案'
});
Object.assign(I18N.en, {
  tab_maneuver: 'Avoidance decision', m_case: 'Demo case', m_win_a: 'Window start (min before TCA)', m_win_b: 'Window end (min before TCA)',
  m_notice: 'Minimum notice (min)', m_dv: 'Δv range (m/s, min, max)', m_budget: 'Δv budget (m/s)',
  m_pc: 'Pc target (used only with propagated covariance)', m_miss: 'Miss-distance target (km)', m_grid: 'Grid (burn times, Δv levels, verify limit)',
  m_ids: 'Extra objects for secondary screening (NORAD IDs, comma or newline separated; TLEs from the server database)', m_run: 'Search avoidance options',
  m_note: 'Single along-track impulse. The primary state at the start of the maneuver window seeds a no-burn reference trajectory, and every candidate branches from it. A linear STM pre-screens the whole grid; candidates are then verified by nonlinear propagation, TCA re-search, Pc recomputation and secondary screening.',
  st_feasible_solution_found: 'Feasible solution found', st_no_solution_found: 'No solution found on the specified grid',
  st_infeasible_constraints: 'Constraints conflict (infeasible)', st_no_maneuver_required: 'No maneuver required',
  st_target_not_found: 'Target conjunction not found', st_invalid_scenario: 'Scenario validation failed',
  rs_notice_window_conflict: 'No legal burn time remains after the minimum notice (earliest allowed time is after the window end)',
  rs_window_before_data_start: 'The maneuver window lies before the analysis start; no ephemeris is available',
  rs_no_along_track_thrust: 'The primary has no along-track (±T) thrust direction',
  rs_dv_budget_below_min_dv: 'The Δv budget is below the minimum searched Δv',
  rs_no_linear_candidate_met_targets: 'No grid point met the targets in the linear pre-screen; below are the best candidates at maximum Δv, verified. This does not mean no feasible maneuver exists, only that none was found with this grid, budget and method',
  rs_verified_candidates_failed: 'Candidates that met the targets linearly all failed nonlinear verification; relax the targets or raise the verify limit or grid density',
  rs_reference_meets_targets: 'The conjunction on the no-burn reference trajectory already meets the targets',
  rs_no_event_near_conjunction_tca: 'No event below the threshold near the specified TCA (±¼ period)',
  rs_no_event_below_threshold: 'No event below the threshold in the analysis window', rs_reference_lost: 'Target event not found on the reference trajectory',
  mk_target: 'Target event (reference)', mk_best: 'Recommended option', mk_after: 'After maneuver', mk_fuel: 'Propellant', mk_verified: 'Verified / passed', mk_elapsed: 'Compute time',
  mc_burn: 'Burn time (UTC)', mc_rel: 'Before TCA (min)', mc_dir: 'Dir.', mc_dv: 'Δv m/s', mc_lin: 'Linear miss km', mc_miss: 'Miss after km',
  mc_dmiss: 'Miss gain km', mc_pcb: 'Pc before', mc_pca: 'Pc after', mc_app: 'Applicability', mc_da: 'Δa m', mc_dp: 'Δperiod s', mc_fuel: 'Propellant g',
  mc_new: 'New / closer conj.', mc_checks: 'Checks', mc_pass: 'Result',
  ck_target_found: 'target', ck_miss: 'miss', ck_pc: 'Pc', ck_no_new_conjunction: 'no new conj.',
  pass: 'Pass', fail: 'Fail', best_tag: 'best',
  md_crit: 'Criteria and coverage', md_dvmap: 'Minimum Δv meeting the targets per burn time (linear pre-screen)', md_series: 'Range history: reference vs recommended (log scale)',
  md_bplane: 'Encounter plane: before vs after', md_3d: '3D geometry (drag to rotate, wheel to zoom)', v_local: 'Near TCA', v_global: 'Global orbits',
  kv_target_tca: 'Target TCA', kv_window: 'Usable window (UTC)', kv_earliest: 'Earliest allowed', kv_dvs: 'Δv search range', kv_signs: 'Thrust directions',
  kv_min_miss: 'Miss target', kv_pc_target: 'Pc target', kv_pc_used: 'Pc target used', kv_crit_note: 'Note', kv_coverage: 'Secondary screening coverage',
  kv_ref_model: 'Reference model', kv_handover: 'Handover time', kv_grid: 'Search grid', kv_ref_event: 'Reference event',
  kv_unresolved: 'NORAD IDs without TLE', yes: 'yes', no: 'no',
  grid_txt: '{t} times × {d} levels × {s} directions = {c} cells; grid spacing {g} s; {p} times pass linearly; {v} verified (limit {m})',
  dv_lbl_p: '+T (prograde, raises orbit)', dv_lbl_m: '−T (retrograde, lowers orbit)', leg_ref: 'Reference (no burn)', leg_best: 'Recommended',
  leg_sec: 'Secondary', leg_burn: 'Burn point', min_miss_line: 'miss target', tca_lbl: 'TCA', x_rel_tca_min: 'Relative to TCA (min)', x_rel_tca_h: 'Relative to TCA (h)',
  bp_note2: 'Each in its own encounter plane, origin at the primary. Blue: before; green: after. Ellipses: combined covariance at 1σ/3σ; dots: secondary.',
  local_note: 'Axes: RTN of the reference primary at the reference TCA (T right, N into the screen, R up; km). Orange: secondary relative path before; green: after.',
  global_note: 'GCRF, half a period either side of TCA. Before and after orbits overlap at this scale; switch to “Near TCA”.',
  pc_cmp_no: ' (assumptions differ; not directly comparable)', m_ids_bad: 'No TLE for: {ids}',
  case_base_feasible: 'Base: feasible', case_notice_window_conflict: 'Notice conflict', case_window_before_data_start: 'Window before data start',
  case_dv_budget_below_min: 'Δv budget too small', case_no_along_track_thrust: 'No along-track thrust', case_no_solution_small_dv: 'Δv too small: no solution on grid',
  case_no_maneuver_required: 'Already meets targets', case_target_not_found: 'Target event not found', case_demo_covariance_miss_only: 'Demo covariance: miss only',
  case_new_conjunction_rejects_best: 'Secondary screening rejects cheapest'
});
Object.assign(I18N.ja, {
  tab_maneuver: '衝突回避の判断', m_case: 'デモケース', m_win_a: '実施窓の開始（TCA 前・分）', m_win_b: '実施窓の終了（TCA 前・分）',
  m_notice: '最短通知時間（分）', m_dv: 'Δv 範囲（m/s、最小, 最大）', m_budget: 'Δv 予算（m/s）',
  m_pc: 'Pc 目標（伝播モード共分散の場合のみ採用）', m_miss: '最小距離目標（km）', m_grid: 'グリッド（実施時刻数, Δv 段階数, 検証上限）',
  m_ids: '二次スクリーニング追加物体（NORAD 番号、カンマまたは改行区切り。TLE はサーバーのデータベースから取得）', m_run: '回避案を探索',
  m_note: '軌道方向の単一インパルス。実施窓の開始時刻の主衛星状態から無マヌーバの参照軌道を作り、すべての候補はそこから分岐する。線形 STM でグリッド全体を予備判定し、非線形伝播による検証、TCA 再探索、Pc 再計算、二次スクリーニングを行う。',
  st_feasible_solution_found: '実行可能な案あり', st_no_solution_found: '指定グリッド内で案が見つからない',
  st_infeasible_constraints: '制約が矛盾（実行不能）', st_no_maneuver_required: 'マヌーバ不要',
  st_target_not_found: '対象の会合イベントが見つからない', st_invalid_scenario: 'シナリオ検証に失敗',
  rs_notice_window_conflict: '最短通知時間の後に有効な実施時刻がない（最早実施可能時刻が実施窓の終了より後）',
  rs_window_before_data_start: '実施窓が解析開始より前にあり、軌道暦がない',
  rs_no_along_track_thrust: '主衛星に軌道方向（±T）の推力方向がない',
  rs_dv_budget_below_min_dv: 'Δv 予算が探索の最小 Δv より小さい',
  rs_no_linear_candidate_met_targets: '線形予備判定で目標を満たすグリッド点がない。以下は最大 Δv での最良候補の検証結果。実行可能な案が存在しないことを意味せず、このグリッド・予算・手法では見つからなかったことを示す',
  rs_verified_candidates_failed: '線形で目標を満たした候補はすべて非線形検証で不合格。目標の緩和、検証上限やグリッド密度の引き上げを検討',
  rs_reference_meets_targets: '参照軌道（無マヌーバ）の会合がすでに目標を満たしている',
  rs_no_event_near_conjunction_tca: '指定 TCA 付近（±¼ 周期）に閾値内のイベントがない',
  rs_no_event_below_threshold: '解析期間内に閾値内のイベントがない', rs_reference_lost: '参照軌道上で対象イベントが見つからない',
  mk_target: '対象イベント（参照軌道）', mk_best: '推奨案', mk_after: 'マヌーバ後', mk_fuel: '推進剤', mk_verified: '検証／合格', mk_elapsed: '計算時間',
  mc_burn: '実施時刻（UTC）', mc_rel: 'TCA まで（分）', mc_dir: '方向', mc_dv: 'Δv m/s', mc_lin: '線形予測距離 km', mc_miss: 'マヌーバ後距離 km',
  mc_dmiss: '距離改善 km', mc_pcb: 'Pc 前', mc_pca: 'Pc 後', mc_app: '適用性', mc_da: 'Δa m', mc_dp: 'Δ周期 s', mc_fuel: '推進剤 g',
  mc_new: '新規／接近した会合', mc_checks: '検査', mc_pass: '結果',
  ck_target_found: '対象', ck_miss: '距離', ck_pc: 'Pc', ck_no_new_conjunction: '新規会合なし',
  pass: '合格', fail: '不合格', best_tag: '推奨',
  md_crit: '判定条件と対象範囲', md_dvmap: '各実施時刻で目標を満たす最小 Δv（線形予備判定）', md_series: '距離の推移：参照と推奨案（対数）',
  md_bplane: '会合平面：マヌーバ前後', md_3d: '3D 幾何（ドラッグで回転、ホイールで拡大縮小）', v_local: 'TCA 付近', v_global: '全体軌道',
  kv_target_tca: '対象 TCA', kv_window: '利用可能な実施窓（UTC）', kv_earliest: '最早実施可能', kv_dvs: 'Δv 探索範囲', kv_signs: '推力方向',
  kv_min_miss: '距離目標', kv_pc_target: 'Pc 目標', kv_pc_used: 'Pc 目標の採用', kv_crit_note: '説明', kv_coverage: '二次スクリーニングの対象範囲',
  kv_ref_model: '参照軌道モデル', kv_handover: '引き継ぎ時刻', kv_grid: '探索グリッド', kv_ref_event: '参照イベント',
  kv_unresolved: 'TLE のない NORAD 番号', yes: 'はい', no: 'いいえ',
  grid_txt: '{t} 時刻 × {d} 段階 × {s} 方向 = {c} 点；間隔 {g} 秒；線形で達成 {p} 時刻；検証 {v} 件（上限 {m}）',
  dv_lbl_p: '+T（加速、軌道上昇）', dv_lbl_m: '−T（減速、軌道下降）', leg_ref: '参照（無マヌーバ）', leg_best: '推奨案',
  leg_sec: '副衛星', leg_burn: '実施点', min_miss_line: '距離目標', tca_lbl: 'TCA', x_rel_tca_min: 'TCA 基準（分）', x_rel_tca_h: 'TCA 基準（時）',
  bp_note2: 'それぞれの会合平面で原点は主衛星。青はマヌーバ前、緑はマヌーバ後の合成共分散 1σ／3σ と副衛星位置。',
  local_note: '座標は参照 TCA 時の参照主衛星 RTN 軸（T 右、N 奥、R 上、km）。橙はマヌーバ前の副衛星相対軌跡、緑はマヌーバ後。',
  global_note: 'GCRF、TCA の前後半周期。この縮尺ではマヌーバ前後の軌道はほぼ重なるため「TCA 付近」に切り替えること。',
  pc_cmp_no: '（仮定が異なり直接比較できない）', m_ids_bad: 'TLE なし：{ids}',
  case_base_feasible: '基準：実行可能', case_notice_window_conflict: '通知時間の矛盾', case_window_before_data_start: '実施窓がデータ開始前',
  case_dv_budget_below_min: 'Δv 予算不足', case_no_along_track_thrust: '軌道方向の推力なし', case_no_solution_small_dv: 'Δv 不足：グリッド内に解なし',
  case_no_maneuver_required: '達成済み：マヌーバ不要', case_target_not_found: '対象イベントなし', case_demo_covariance_miss_only: 'デモ共分散：距離のみで判定',
  case_new_conjunction_rejects_best: '二次スクリーニングが最省案を棄却'
});

let MSTATE = null;   // {data, view: 'local'|'global', yaw, pitch, zoom}
let MDEMOS = [];

const mNum = v => { const x = parseFloat(v); return isFinite(x) ? x : null; };
const mList = v => String(v || '').split(/[,\s;]+/).filter(Boolean).map(Number);

function mFillFields(sc) {
  const ms = sc.maneuver_search || {}, p = (sc.objects || []).find(o => o.role === 'primary') || {};
  const prop = p.propulsion || {}, w = ms.window_rel_tca_s || [null, null];
  $('m-wa').value = w[0] !== null ? -w[0] / 60 : '';
  $('m-wb').value = w[1] !== null ? -w[1] / 60 : '';
  $('m-notice').value = prop.min_notice_s !== undefined ? prop.min_notice_s / 60 : '';
  $('m-dv').value = (ms.dv_ms || []).join(', ');
  $('m-budget').value = prop.dv_budget_ms !== undefined ? prop.dv_budget_ms : '';
  $('m-pc').value = ms.pc_target !== undefined ? ms.pc_target : '';
  $('m-miss').value = ms.min_miss_km !== undefined ? ms.min_miss_km : '';
  $('m-grid').value = [ms.n_times, ms.n_dv, ms.max_verify].map(x => x === undefined ? '' : x).join(', ');
}

function mApplyFields(sc) {
  const ms = sc.maneuver_search = sc.maneuver_search || {};
  const p = (sc.objects || []).find(o => o.role === 'primary');
  const wa = mNum($('m-wa').value), wb = mNum($('m-wb').value);
  if (wa !== null && wb !== null) ms.window_rel_tca_s = [-wa * 60, -wb * 60];
  const dv = mList($('m-dv').value);
  if (dv.length === 2 && dv.every(isFinite)) ms.dv_ms = dv;
  const setOpt = (obj, k, v) => { if (v === null) delete obj[k]; else obj[k] = v; };
  setOpt(ms, 'pc_target', mNum($('m-pc').value));
  setOpt(ms, 'min_miss_km', mNum($('m-miss').value));
  const g = String($('m-grid').value).split(',').map(s => parseInt(s, 10));
  ['n_times', 'n_dv', 'max_verify'].forEach((k, i) => setOpt(ms, k, isFinite(g[i]) ? g[i] : null));
  if (p) {
    p.propulsion = p.propulsion || {};
    const n = mNum($('m-notice').value);
    setOpt(p.propulsion, 'min_notice_s', n === null ? null : n * 60);
    setOpt(p.propulsion, 'dv_budget_ms', mNum($('m-budget').value));
  }
  return sc;
}

async function mLoadDemos() {
  try {
    const j = await (await fetch('/api/lab/maneuver/demo')).json();
    MDEMOS = j.scenarios;
    const sel = $('m-case');
    const fill = () => {
      const cur = sel.value || '0';
      sel.innerHTML = MDEMOS.map((s, i) => `<option value="${i}">${t('case_' + s.id)}</option>`).join('');
      sel.value = cur;
    };
    fill();
    sel.onchange = () => { const s = MDEMOS[+sel.value]; $('m-json').value = JSON.stringify(s.scenario, null, 1); mFillFields(s.scenario); $('m-msg').textContent = j.description; };
    sel.onchange();
    mLoadDemos.refill = fill;
  } catch (e) { /* 示範案例載入失敗不影響其他分頁 */ }
}

async function mRun() {
  const btn = $('m-run');
  let sc;
  try { sc = JSON.parse($('m-json').value); } catch (e) { $('m-msg').innerHTML = `<span class="err">JSON: ${e.message}</span>`; return; }
  mApplyFields(sc);
  $('m-json').value = JSON.stringify(sc, null, 1);
  const ids = mList($('m-ids').value).filter(isFinite);
  btn.disabled = true;
  status(t('running'));
  const t0 = performance.now();
  try {
    const j = await postJson('/api/lab/maneuver', { scenario: sc, screening_norad_ids: ids });
    if (j.status === 'error') { status(tpl('failed', { e: j.error }), true); return; }
    if (j.status === 'invalid_scenario') {
      $('m-msg').innerHTML = `<span class="err">${tpl('s_invalid', { codes: j.validation.codes.join(', ') })}</span>` +
        (j.validation.messages || []).map(m => `<div class="err">${m}</div>`).join('');
      status(''); return;
    }
    $('m-msg').innerHTML = (j.screening_unresolved || []).length ? `<span class="err">${tpl('m_ids_bad', { ids: j.screening_unresolved.join(', ') })}</span>` : '';
    MSTATE = { data: j, view: 'local', yaw: -0.6, pitch: 0.35, zoom: 1 };
    status(tpl('done', { n: (j.candidates || []).length, s: ((performance.now() - t0) / 1000).toFixed(2) }));
    labManeuverRender();
  } catch (e) {
    status(tpl('failed', { e: e.message }), true);
  } finally { btn.disabled = false; }
}

const stClass = s => s === 'feasible_solution_found' || s === 'no_maneuver_required' ? 'ok'
  : s === 'no_solution_found' ? 'warn' : 'crit';
const minutes = s => fmt(s / 60, 1);
const utc = s => s ? s.replace('T', ' ').replace(/\.\d+Z$/, 'Z') : '—';

function labManeuverRender() {
  if (mLoadDemos.refill) mLoadDemos.refill();
  if (!MSTATE || document.body.dataset.pane !== 'maneuver') return;
  const d = MSTATE.data;
  $('m-results').style.display = 'block';
  const reason = d.reason ? t('rs_' + d.reason) : '';
  $('m-banner').className = 'banner ' + stClass(d.status);
  $('m-banner').innerHTML = `<b>${t('st_' + d.status)}</b> <span class="hint">${d.status}${d.reason ? ' · ' + d.reason : ''}</span>` +
    (reason ? `<div>${reason}</div>` : '');
  const ref = (d.reference || {}).event || d.target, b = d.best, be = b && b.event;
  const pcOf = e => e && e.pc ? e.pc.foster : null;
  const kp = [];
  if (ref) kp.push([`${fmt(ref.miss_km, 3)} km · ${fmtPc(pcOf(ref))}`, `${t('mk_target')}<br>${utc(ref.tca_utc)}`]);
  if (b) {
    kp.push([`${b.direction} ${fmt(b.dv_ms, 3)} m/s`, `${t('mk_best')}<br>${utc(b.burn_utc)}（${minutes(b.burn_rel_tca_s)} min）`]);
    if (be) kp.push([`${fmt(be.miss_km, 3)} km · ${fmtPc(pcOf(be))}`, t('mk_after') + (b.pc_comparable ? '' : t('pc_cmp_no'))]);
    kp.push([b.propellant_kg !== null ? fmt(b.propellant_kg * 1000, 1) + ' g' : '—', t('mk_fuel')]);
  }
  if (d.searched) kp.push([`${d.searched.verified} / ${d.searched.passed}`, t('mk_verified')]);
  if (d.timing) kp.push([fmt(d.timing.elapsed_s, 2) + ' s', t('mk_elapsed')]);
  $('m-kpis').innerHTML = kp.map(([v, l]) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div></div>`).join('');
  const s = d.searched;
  $('m-meta').textContent = s ? tpl('grid_txt', { t: s.times, d: s.dv_levels, s: s.signs.length, c: s.grid_cells, g: s.grid_step_s,
    p: s.linear_pass_times, v: s.verified, m: s.max_verify }) : '';
  mRenderTable(d);
  mRenderDetail(d);
}
window.labManeuverRender = labManeuverRender;

function mRenderTable(d) {
  const cands = d.candidates || [];
  const wrap = $('m-thead').closest('.tblwrap');
  wrap.style.display = cands.length ? '' : 'none';
  const cols = ['', 'mc_burn', 'mc_rel', 'mc_dir', 'mc_dv', 'mc_lin', 'mc_miss', 'mc_dmiss', 'mc_pcb', 'mc_pca', 'mc_app', 'mc_da', 'mc_dp', 'mc_fuel', 'mc_new', 'mc_checks', 'mc_pass'];
  $('m-thead').innerHTML = cols.map((c, i) => `<th class="${i === 1 || i >= 14 ? 'l' : ''}">${c ? t(c) : ''}</th>`).join('');
  $('m-tbody').innerHTML = cands.map((c, i) => {
    const e = c.event || {};
    const nc = c.new_conjunctions || [];
    const ncTxt = nc.length ? `${nc.length}（min ${fmt(Math.min(...nc.map(x => x.miss_km)), 2)} km）` : '0';
    const ck = Object.entries(c.checks || {}).map(([k, v]) => `<span class="chk ${v ? 'y' : 'n'}">${v ? '✓' : '✗'}${t('ck_' + k)}</span>`).join(' ');
    return `<tr class="${c === d.best ? 'sel' : ''}">` + [
      c === d.best ? `<span class="badge b-pass">${t('best_tag')}</span>` : i + 1,
      `<td class="l">${utc(c.burn_utc)}</td>`, minutes(c.burn_rel_tca_s), c.direction, fmt(c.dv_ms, 3),
      fmt(c.linear.miss_km, 3), fmt(e.miss_km, 3), fmt(c.d_miss_km, 3), fmtPc(c.pc_before), fmtPc(c.pc_after),
      e.applicability ? appBadge(e.applicability.status) : '—', fmt(c.delta_a_km * 1000, 1), fmt(c.delta_period_s, 2),
      c.propellant_kg !== null ? fmt(c.propellant_kg * 1000, 1) : '—',
      `<td class="l">${ncTxt}</td>`, `<td class="l">${ck}</td>`,
      `<td class="l"><span class="badge ${c.passed ? 'b-pass' : 'b-fail'}">${c.passed ? t('pass') : t('fail')}</span></td>`
    ].map(x => String(x).startsWith('<td') ? x : `<td>${x}</td>`).join('') + '</tr>';
  }).join('');
}

function mRenderDetail(d) {
  const box = $('m-detail');
  const f = d.feasibility || {}, cr = d.criteria || {}, ss = d.secondary_screening || {}, rf = d.reference || {};
  const kv = [];
  if (f.target_tca_utc) kv.push([t('kv_target_tca'), utc(f.target_tca_utc)]);
  if (f.window_utc) kv.push([t('kv_window'), f.window_utc.map(utc).join(' → ')]);
  if (f.earliest_allowed_utc) kv.push([t('kv_earliest'), utc(f.earliest_allowed_utc)]);
  if (f.dv_search_ms || f.dv_range_ms) kv.push([t('kv_dvs'), (f.dv_search_ms || f.dv_range_ms).map(x => fmt(x, 3)).join(' – ') + ' m/s' + (f.dv_budget_ms !== undefined && f.dv_budget_ms !== null ? `（${t('m_budget')} ${f.dv_budget_ms}）` : '')]);
  if (f.along_track_signs) kv.push([t('kv_signs'), f.along_track_signs.join(', ') || '—']);
  if (cr.min_miss_km !== undefined) kv.push([t('kv_min_miss'), cr.min_miss_km === null ? '—' : cr.min_miss_km + ' km']);
  if (cr.pc_target !== undefined) kv.push([t('kv_pc_target'), cr.pc_target === null ? '—' : fmtPc(cr.pc_target)]);
  if (cr.pc_target_used !== undefined) kv.push([t('kv_pc_used'), cr.pc_target_used ? t('yes') : t('no')]);
  if (cr.note) kv.push([t('kv_crit_note'), cr.note]);
  if (rf.model) {
    const fmd = rf.model.force_model || {};
    const forces = ['two-body', fmd.zonal ? fmd.zonal : null, fmd.drag ? 'drag ' + JSON.stringify(fmd.drag) : null].filter(Boolean).join(' + ');
    kv.push([t('kv_ref_model'), `${rf.model.integrator} ${rf.model.step_s} s · ${forces}`], [t('kv_handover'), utc(rf.handover_utc)]);
  }
  if (rf.event) kv.push([t('kv_ref_event'), `${utc(rf.event.tca_utc)} · ${fmt(rf.event.miss_km, 3)} km · Pc ${fmtPc((rf.event.pc || {}).foster)}`]);
  if (ss.coverage_note) kv.push([t('kv_coverage'), `${ss.coverage_note}（${(ss.window_utc || []).map(utc).join(' → ')}）`]);
  if ((d.screening_unresolved || []).length) kv.push([t('kv_unresolved'), d.screening_unresolved.join(', ')]);
  let html = `<div class="card"><h3>${t('md_crit')}</h3><dl class="kv">${kv.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join('')}</dl></div>`;
  if (d.linear_map) html += `<div class="card"><h3>${t('md_dvmap')}</h3><canvas id="mc-dv" height="260"></canvas></div>`;
  if (d.plot) {
    html += `<div class="card"><h3>${t('md_series')}</h3><canvas id="mc-series" height="260"></canvas></div>`;
    const be = d.best && d.best.event;
    if ((rf.event || {}).bplane && be && be.bplane) html += `<div class="card"><h3>${t('md_bplane')}</h3><canvas id="mc-bp" height="300"></canvas><p class="hint">${t('bp_note2')}</p></div>`;
    html += `<div class="card"><h3>${t('md_3d')}<span class="seg"><button type="button" data-v="local">${t('v_local')}</button><button type="button" data-v="global">${t('v_global')}</button></span></h3>
      <canvas id="mc-3d" class="drag" height="340"></canvas><p class="hint" id="mc-3d-note"></p></div>`;
  }
  box.innerHTML = html;
  if (d.linear_map) mDrawDvMap(d);
  if (d.plot) {
    mDrawSeries(d);
    if ($('mc-bp')) mDrawBplanes(d);
    document.querySelectorAll('.seg button').forEach(bt => {
      bt.classList.toggle('on', bt.dataset.v === MSTATE.view);
      bt.onclick = () => { MSTATE.view = bt.dataset.v; MSTATE.zoom = 1; document.querySelectorAll('.seg button').forEach(x => x.classList.toggle('on', x === bt)); mDraw3d(d); };
    });
    mSetup3dEvents(d);
    mDraw3d(d);
  }
}

function mAxes(ctx, w, h, L, R, T, B) {
  ctx.strokeStyle = '#30363d'; ctx.lineWidth = 1; ctx.strokeRect(L, T, w - L - R, h - T - B);
  ctx.font = '11px Segoe UI, sans-serif'; ctx.fillStyle = '#8b949e';
}

function mLegend(ctx, items, x, y, right) {
  ctx.font = '11px Segoe UI, sans-serif';
  const wmax = Math.max(...items.map(([, lab]) => ctx.measureText(lab).width)) + 24;
  if (right) x -= wmax;
  ctx.fillStyle = 'rgba(13,17,23,0.85)'; ctx.fillRect(x - 4, y - 13, wmax + 4, items.length * 15 + 4);
  items.forEach(([col, lab], i) => {
    ctx.fillStyle = col; ctx.fillRect(x, y + i * 15 - 7, 12, 3);
    ctx.fillStyle = '#c9d1d9'; ctx.fillText(lab, x + 17, y + i * 15 - 3);
  });
}

function mDrawDvMap(d) {
  const cv = $('mc-dv'); if (!cv) return;
  const { ctx, w, h } = setupCanvas(cv);
  const L = 50, R = 12, T = 12, B = 30;
  const tca = d.target.tca_tau_s, rows = d.linear_map;
  const xs = rows.map(r => (r.burn_tau_s - tca) / 60);
  const x0 = Math.min(...xs), x1 = Math.max(...xs, x0 + 1);
  const dvMax = d.searched.dv_search_ms[1] * 1.05;
  const X = v => L + (w - L - R) * (v - x0) / (x1 - x0 || 1), Y = v => T + (h - T - B) * (1 - v / dvMax);
  mAxes(ctx, w, h, L, R, T, B);
  for (let i = 0; i <= 4; i++) { const v = dvMax * i / 4; ctx.fillText(v.toFixed(2), 6, Y(v) + 4); }
  for (let i = 0; i <= 5; i++) { const v = x0 + (x1 - x0) * i / 5; ctx.fillText(v.toFixed(0), X(v) - 10, h - 14); }
  ctx.fillText(t('x_rel_tca_min'), L + 4, h - 2);
  ctx.fillText('m/s', 6, T + 2);
  [['+T', '#58a6ff'], ['-T', '#bc8cff']].forEach(([k, col]) => {
    ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.beginPath(); let pen = false;
    rows.forEach(r => {
      const v = r.min_dv_ms[k];
      if (v === null || v === undefined) { pen = false; return; }
      const x = X((r.burn_tau_s - tca) / 60), y = Y(v);
      if (pen) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      pen = true;
    });
    ctx.stroke();
  });
  (d.candidates || []).forEach(c => {
    const x = X(c.burn_rel_tca_s / 60), y = Y(c.dv_ms);
    if (c.passed) { ctx.fillStyle = c === d.best ? '#3fb950' : '#2ea043'; ctx.beginPath(); ctx.arc(x, y, c === d.best ? 5.5 : 3.5, 0, 2 * Math.PI); ctx.fill(); }
    else { ctx.strokeStyle = '#d29922'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x - 4, y - 4); ctx.lineTo(x + 4, y + 4); ctx.moveTo(x + 4, y - 4); ctx.lineTo(x - 4, y + 4); ctx.stroke(); }
  });
  ctx.font = '11px Segoe UI, sans-serif';
  mLegend(ctx, [['#58a6ff', t('dv_lbl_p')], ['#bc8cff', t('dv_lbl_m')], ['#3fb950', t('pass')], ['#d29922', t('fail')]], w - R - 6, h - B - 58, true);
}

function mDrawSeries(d) {
  const cv = $('mc-series'); if (!cv) return;
  const { ctx, w, h } = setupCanvas(cv);
  const L = 54, R = 12, T = 12, B = 30, P = d.plot.series, tca = d.target.tca_tau_s;
  const n = P.d_ref_km.length, tau = i => P.tau0_s + i * P.step_s;
  const rf = d.reference.event, be = d.best && d.best.event;
  const all = P.d_ref_km.concat(P.d_best_km || [], [rf.miss_km], be ? [be.miss_km] : []);
  const lo = Math.max(1e-3, Math.min(...all) * 0.5), hi = Math.max(...all, d.threshold_km) * 1.2;
  const ly0 = Math.log10(lo), ly1 = Math.log10(hi);
  const xh0 = (tau(0) - tca) / 3600, xh1 = (tau(n - 1) - tca) / 3600;
  const X = s => L + (w - L - R) * ((s - tca) / 3600 - xh0) / (xh1 - xh0 || 1);
  const Y = v => T + (h - T - B) * (1 - (Math.log10(Math.max(v, lo)) - ly0) / (ly1 - ly0));
  mAxes(ctx, w, h, L, R, T, B);
  for (let p = Math.ceil(ly0); p <= Math.floor(ly1); p++) {
    const y = Y(10 ** p); ctx.strokeStyle = '#21262d'; ctx.beginPath(); ctx.moveTo(L, y); ctx.lineTo(w - R, y); ctx.stroke();
    ctx.fillText(p >= 0 ? String(10 ** p) : (10 ** p).toFixed(-p), 4, y + 4);
  }
  for (let i = 0; i <= 5; i++) { const v = xh0 + (xh1 - xh0) * i / 5; ctx.fillText(v.toFixed(1), L + (w - L - R) * i / 5 - 8, h - 14); }
  ctx.fillText(t('x_rel_tca_h'), L + 4, h - 2);
  const mm = (d.criteria || {}).min_miss_km;
  if (mm) { ctx.strokeStyle = '#f85149'; ctx.setLineDash([4, 3]); ctx.beginPath(); ctx.moveTo(L, Y(mm)); ctx.lineTo(w - R, Y(mm)); ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = '#f85149'; ctx.fillText(t('min_miss_line'), w - R - 60, Y(mm) - 4); }
  const line = (arr, extra, col) => {
    const pts = arr.map((v, i) => [tau(i), v]).concat(extra).sort((a, b) => a[0] - b[0]);
    ctx.strokeStyle = col; ctx.lineWidth = 1.4; ctx.beginPath();
    pts.forEach(([s, v], i) => { const x = X(s), y = Y(v); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }); ctx.stroke();
  };
  line(P.d_ref_km, [[rf.tca_tau_s, rf.miss_km]], '#8b949e');
  if (P.d_best_km && be) line(P.d_best_km, [[be.tca_tau_s, be.miss_km]], '#3fb950');
  ctx.fillStyle = '#e6edf3'; ctx.beginPath(); ctx.arc(X(rf.tca_tau_s), Y(rf.miss_km), 3, 0, 2 * Math.PI); ctx.fill();
  if (be) { ctx.fillStyle = '#3fb950'; ctx.beginPath(); ctx.arc(X(be.tca_tau_s), Y(be.miss_km), 3.5, 0, 2 * Math.PI); ctx.fill(); }
  if (d.best) { const x = X(d.best.burn_tau_s); ctx.strokeStyle = '#bc8cff'; ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(x, T); ctx.lineTo(x, h - B); ctx.stroke(); ctx.setLineDash([]); }
  mLegend(ctx, [['#8b949e', t('leg_ref')], ['#3fb950', t('leg_best')], ['#bc8cff', t('leg_burn')]], L + 8, T + 14);
}

function mEllipse(C) {
  const a = C[0][0], b = C[0][1], c = C[1][1];
  const md = 0.5 * (a + c), dd = Math.sqrt(0.25 * (a - c) ** 2 + b * b);
  return { l1: md + dd, l2: Math.max(md - dd, 0), th: 0.5 * Math.atan2(2 * b, a - c) };
}

function mDrawBplanes(d) {
  const cv = $('mc-bp');
  const { ctx, w, h } = setupCanvas(cv);
  const A = d.reference.event.bplane, Bp = d.best.event.bplane;
  const eA = mEllipse(A.cov_km2), eB = mEllipse(Bp.cov_km2);
  const ext = Math.max(3 * Math.sqrt(eA.l1), 3 * Math.sqrt(eB.l1), ...A.miss_km.map(Math.abs), ...Bp.miss_km.map(Math.abs)) * 1.15;
  const cx = w / 2, cy = h / 2, k = Math.min(w, h) / 2 / ext;
  ctx.strokeStyle = '#21262d'; ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(w, cy); ctx.moveTo(cx, 0); ctx.lineTo(cx, h); ctx.stroke();
  ctx.fillStyle = '#8b949e'; ctx.font = '11px Segoe UI, sans-serif'; ctx.fillText(`±${ext.toPrecision(3)} km`, 6, 14);
  [[eA, A, '88,166,255'], [eB, Bp, '63,185,80']].forEach(([e, bp, rgb]) => {
    [1, 3].forEach(s => { ctx.strokeStyle = `rgba(${rgb},${s === 1 ? 0.9 : 0.45})`; ctx.beginPath(); ctx.ellipse(cx, cy, s * Math.sqrt(e.l1) * k, s * Math.sqrt(e.l2) * k, -e.th, 0, 2 * Math.PI); ctx.stroke(); });
    ctx.fillStyle = `rgb(${rgb})`; ctx.beginPath(); ctx.arc(cx + bp.miss_km[0] * k, cy - bp.miss_km[1] * k, 3.5, 0, 2 * Math.PI); ctx.fill();
  });
  ctx.fillStyle = '#e6edf3'; ctx.beginPath(); ctx.arc(cx, cy, 2.5, 0, 2 * Math.PI); ctx.fill();
  mLegend(ctx, [['#58a6ff', t('leg_ref')], ['#3fb950', t('leg_best')]], 8, 30);
}

function mSetup3dEvents(d) {
  const cv = $('mc-3d'); if (!cv) return;
  let drag = null;
  cv.onpointerdown = e => { drag = { x: e.clientX, y: e.clientY }; cv.setPointerCapture(e.pointerId); };
  cv.onpointermove = e => {
    if (!drag) return;
    MSTATE.yaw += (e.clientX - drag.x) * 0.01; MSTATE.pitch = Math.max(-1.5, Math.min(1.5, MSTATE.pitch + (e.clientY - drag.y) * 0.01));
    drag = { x: e.clientX, y: e.clientY }; mDraw3d(d);
  };
  cv.onpointerup = () => { drag = null; };
  cv.onwheel = e => { e.preventDefault(); MSTATE.zoom = Math.max(0.2, Math.min(20, MSTATE.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15))); mDraw3d(d); };
}

function mDraw3d(d) {
  const cv = $('mc-3d'); if (!cv) return;
  const { ctx, w, h } = setupCanvas(cv);
  const S = MSTATE, cy_ = Math.cos(S.yaw), sy = Math.sin(S.yaw), cp = Math.cos(S.pitch), sp = Math.sin(S.pitch);
  const rot = ([x, y, z]) => { const x1 = cy_ * x - sy * y, y1 = sy * x + cy_ * y; return [x1, cp * y1 - sp * z, sp * y1 + cp * z]; };
  ctx.font = '11px Segoe UI, sans-serif';
  if (S.view === 'local') {
    const L = d.plot.local;
    // RTN → 繪圖座標：x = T、y = N、z = R
    const map = p => [p[1], p[2], p[0]];
    const sets = [[L.rel_ref, '#d29922'], [L.rel_best, '#3fb950']].filter(s => s[0]);
    const ext = Math.max(1e-3, ...sets.flatMap(([a]) => a.flatMap(p => p.map(Math.abs))));
    const k = Math.min(w, h) / 2 / ext * 0.85 * S.zoom, cx = w / 2, cyc = h / 2;
    const P = p => { const q = rot(map(p)); return [cx + k * q[0], cyc - k * q[2]]; };
    [['T', [ext, 0, 0]], ['N', [0, ext, 0]], ['R', [0, 0, ext]]].forEach(([lab, v]) => {
      const a = P([0, 0, 0]), q = rot(v), b = [cx + k * q[0] * 0.6, cyc - k * q[2] * 0.6];
      ctx.strokeStyle = '#484f58'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
      ctx.fillStyle = '#8b949e'; ctx.fillText(lab, b[0] + 3, b[1] - 3);
    });
    sets.forEach(([arr, col]) => {
      ctx.strokeStyle = col; ctx.lineWidth = 1.8; ctx.beginPath();
      arr.forEach((p, i) => { const [x, y] = P(p); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      ctx.stroke();
      const mid = arr.reduce((m, p) => (Math.hypot(...p) < Math.hypot(...m) ? p : m), arr[0]);
      const [x, y] = P(mid);
      ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, y, 3.5, 0, 2 * Math.PI); ctx.fill();
      ctx.setLineDash([2, 3]); const o = P([0, 0, 0]); ctx.beginPath(); ctx.moveTo(o[0], o[1]); ctx.lineTo(x, y); ctx.stroke(); ctx.setLineDash([]);
      ctx.fillText(fmt(Math.hypot(...mid), 3) + ' km', x + 5, y - 5);
    });
    const o = P([0, 0, 0]); ctx.fillStyle = '#e6edf3'; ctx.beginPath(); ctx.arc(o[0], o[1], 3, 0, 2 * Math.PI); ctx.fill();
    ctx.fillText(`±${(ext / S.zoom).toPrecision(3)} km`, 6, 14);
    mLegend(ctx, [['#d29922', t('leg_ref')], ['#3fb950', t('leg_best')]], 8, 30);
    $('mc-3d-note').textContent = t('local_note');
    return;
  }
  const G = d.plot.global, RE = 6378.137;
  const ext = Math.max(RE, ...G.primary_ref.flatMap(p => p.map(Math.abs)), ...G.secondary.flatMap(p => p.map(Math.abs)));
  const k = Math.min(w, h) / 2 / ext * 0.9 * S.zoom, cx = w / 2, cyc = h / 2;
  const grd = ctx.createRadialGradient(cx - RE * k * 0.3, cyc - RE * k * 0.3, RE * k * 0.1, cx, cyc, RE * k);
  grd.addColorStop(0, '#1f4a7a'); grd.addColorStop(1, '#0b1d33');
  ctx.fillStyle = grd; ctx.beginPath(); ctx.arc(cx, cyc, RE * k, 0, 2 * Math.PI); ctx.fill();
  ctx.strokeStyle = 'rgba(88,166,255,0.35)'; ctx.lineWidth = 1; ctx.beginPath();
  for (let i = 0; i <= 72; i++) { const a = i / 72 * 2 * Math.PI, q = rot([RE * Math.cos(a), RE * Math.sin(a), 0]); const x = cx + k * q[0], y = cyc - k * q[2]; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); }
  ctx.stroke();
  const drawPath = (arr, col, width) => {
    for (let i = 1; i < arr.length; i++) {
      const a = rot(arr[i - 1]), b = rot(arr[i]);
      const hidden = b[1] > 0 && Math.hypot(b[0], b[2]) < RE;
      ctx.strokeStyle = col; ctx.globalAlpha = hidden ? 0.25 : 1; ctx.lineWidth = width;
      ctx.beginPath(); ctx.moveTo(cx + k * a[0], cyc - k * a[2]); ctx.lineTo(cx + k * b[0], cyc - k * b[2]); ctx.stroke();
    }
    ctx.globalAlpha = 1;
  };
  drawPath(G.secondary, '#d29922', 1.5);
  drawPath(G.primary_ref, '#8b949e', 1.5);
  if (G.primary_best) drawPath(G.primary_best, '#3fb950', 1.2);
  const tcaIdx = G.tau_s.reduce((bi, v, i) => (Math.abs(v - d.target.tca_tau_s) < Math.abs(G.tau_s[bi] - d.target.tca_tau_s) ? i : bi), 0);
  const q = rot(G.primary_ref[tcaIdx]); ctx.fillStyle = '#f85149'; ctx.beginPath(); ctx.arc(cx + k * q[0], cyc - k * q[2], 4, 0, 2 * Math.PI); ctx.fill();
  ctx.fillText(t('tca_lbl'), cx + k * q[0] + 6, cyc - k * q[2] - 4);
  if (G.burn_km) { const b = rot(G.burn_km); ctx.fillStyle = '#bc8cff'; ctx.beginPath(); ctx.arc(cx + k * b[0], cyc - k * b[2], 4, 0, 2 * Math.PI); ctx.fill(); }
  mLegend(ctx, [['#8b949e', t('leg_ref')], ['#3fb950', t('leg_best')], ['#d29922', t('leg_sec')], ['#bc8cff', t('leg_burn')]], 8, 18);
  $('mc-3d-note').textContent = t('global_note');
}

document.addEventListener('DOMContentLoaded', () => {
  $('m-run').onclick = mRun;
  $('m-load').onclick = () => $('m-file').click();
  $('m-file').onchange = async ev => { const f = ev.target.files[0]; if (f) { $('m-json').value = await f.text(); try { mFillFields(JSON.parse($('m-json').value)); } catch (e) { /* ignore */ } } };
  $('m-dl').onclick = () => MSTATE && download('maneuver_result.json', JSON.stringify(MSTATE.data, null, 1), 'application/json');
  window.addEventListener('resize', () => { if (MSTATE && document.body.dataset.pane === 'maneuver') mRenderDetail(MSTATE.data); });
  mLoadDemos();
});
