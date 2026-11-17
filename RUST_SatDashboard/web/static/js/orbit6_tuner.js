'use strict';
// ═══════════════════════════════════════════════════════════════════════════════
// 軌道六參數互動調整器（仿 AGI Orbit Tuner）
// 純前端二體克卜勒數學（非 SGP4），純為展示理想軌道形狀與 STK Connect 指令對應關係，
// 不涉及攝動精度。疊加繪製於既有 globe.js 建立的 Cesium viewer（window.__cesiumViewer）。
// ═══════════════════════════════════════════════════════════════════════════════
(function(){
  const MU_EARTH = 398600.4418; // km^3/s^2
  const R_EARTH = 6378.137; // km

  const PRESETS = {
    iss:     {a:6798,  e:0.0006, i:51.6, raan:0, argp:0,   nu:0},
    gps:     {a:26560, e:0.01,   i:55,   raan:0, argp:0,   nu:0},
    geo:     {a:42164, e:0.0002, i:0.05, raan:0, argp:0,   nu:0},
    molniya: {a:26600, e:0.74,   i:63.4, raan:0, argp:270, nu:0},
  };

  let state = Object.assign({}, PRESETS.iss);
  let showOnGlobe = true;
  let satName = 'OrbitTunerSat';
  let panelBodyEl = null;
  let orbitEntity = null, satEntity = null;

  function T(key){ return window.t ? window.t(key) : key; }
  function deg2rad(d){ return d*Math.PI/180; }

  // 古典軌道六要素 → ECI(近似)直角座標，單位 km
  function keplerToECI(a,e,iDeg,raanDeg,argpDeg,nuDeg){
    const i=deg2rad(iDeg), raan=deg2rad(raanDeg), argp=deg2rad(argpDeg), nu=deg2rad(nuDeg);
    const p = a*(1-e*e);
    const r = p/(1+e*Math.cos(nu));
    const xOrb = r*Math.cos(nu), yOrb = r*Math.sin(nu);
    const cosO=Math.cos(raan), sinO=Math.sin(raan);
    const cosW=Math.cos(argp), sinW=Math.sin(argp);
    const cosI=Math.cos(i), sinI=Math.sin(i);
    return {
      x:(cosO*cosW - sinO*sinW*cosI)*xOrb + (-cosO*sinW - sinO*cosW*cosI)*yOrb,
      y:(sinO*cosW + cosO*sinW*cosI)*xOrb + (-sinO*sinW + cosO*cosW*cosI)*yOrb,
      z:(sinW*sinI)*xOrb + (cosW*sinI)*yOrb,
    };
  }

  function orbitPeriodMin(a){ return 2*Math.PI*Math.sqrt(Math.pow(a,3)/MU_EARTH)/60; }

  function computeStats(s){
    return {
      apogeeAlt: s.a*(1+s.e) - R_EARTH,
      perigeeAlt: s.a*(1-s.e) - R_EARTH,
      periodMin: orbitPeriodMin(s.a),
    };
  }

  function orbitSamplePoints(s,n){
    n = n||180;
    const pts=[];
    for(let k=0;k<=n;k++) pts.push(keplerToECI(s.a,s.e,s.i,s.raan,s.argp,k*360/n));
    return pts;
  }

  // TEME(近似慣性座標)→地球固定框架：僅套用地球自轉，離線可用、不需額外資料
  function eciKmToFixedCartesian(pKm, jd){
    const posMeters = new Cesium.Cartesian3(pKm.x*1000, pKm.y*1000, pKm.z*1000);
    const mtx = Cesium.Transforms.computeTemeToPseudoFixedMatrix(jd);
    if(!mtx) return posMeters;
    return Cesium.Matrix3.multiplyByVector(mtx, posMeters, new Cesium.Cartesian3());
  }

  function clearEntities(){
    const viewer = window.__cesiumViewer;
    if(!viewer) return;
    if(orbitEntity){ viewer.entities.remove(orbitEntity); orbitEntity=null; }
    if(satEntity){ viewer.entities.remove(satEntity); satEntity=null; }
  }

  function updateGlobeEntities(){
    const viewer = window.__cesiumViewer;
    if(!viewer || typeof Cesium==='undefined') return;
    clearEntities();
    if(!showOnGlobe) return;
    const jd = (viewer.clock && viewer.clock.currentTime) ? viewer.clock.currentTime : Cesium.JulianDate.now();
    const positions = orbitSamplePoints(state,180).map(p=>eciKmToFixedCartesian(p,jd));
    orbitEntity = viewer.entities.add({
      polyline:{ positions, width:2, material:Cesium.Color.fromCssColorString('#64DD17').withAlpha(0.9) },
    });
    const satPos = eciKmToFixedCartesian(keplerToECI(state.a,state.e,state.i,state.raan,state.argp,state.nu), jd);
    satEntity = viewer.entities.add({
      position: satPos,
      point:{ pixelSize:9, color:Cesium.Color.fromCssColorString('#FFEB3B'), outlineColor:Cesium.Color.BLACK, outlineWidth:1 },
    });
  }

  function focusOnOrbit(){
    const viewer = window.__cesiumViewer;
    if(!viewer || !orbitEntity) return;
    viewer.flyTo(orbitEntity, {duration:1.2});
  }

  // ── STK Connect 指令 ──────────────────────────────────────────────────────
  function pad(n){ return String(n).padStart(2,'0'); }
  function nowUtcSTKEpoch(){
    const d=new Date();
    const months=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${d.getUTCDate()} ${months[d.getUTCMonth()]} ${d.getUTCFullYear()} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}.000`;
  }
  let connectEpoch = nowUtcSTKEpoch();

  function buildConnectCommand(){
    const s=state;
    return `SetState */Satellite/${satName} Classical TwoBody "${connectEpoch}" J2000 `
      + `${s.a.toFixed(3)} ${s.e.toFixed(6)} ${s.i.toFixed(4)} ${s.raan.toFixed(4)} ${s.argp.toFixed(4)} ${s.nu.toFixed(4)}`;
  }

  // ── UI ────────────────────────────────────────────────────────────────────
  const FIELDS = [
    {key:'a',    labelKey:'o6_lbl_a',    helpKey:'o6_help_a',    min:6578, max:45000, step:1,     unit:'km'},
    {key:'e',    labelKey:'o6_lbl_e',    helpKey:'o6_help_e',    min:0,    max:0.95,  step:0.001, unit:''},
    {key:'i',    labelKey:'o6_lbl_i',    helpKey:'o6_help_i',    min:0,    max:180,   step:0.1,   unit:'°'},
    {key:'raan', labelKey:'o6_lbl_raan', helpKey:'o6_help_raan', min:0,    max:360,   step:0.1,   unit:'°'},
    {key:'argp', labelKey:'o6_lbl_argp', helpKey:'o6_help_argp', min:0,    max:360,   step:0.1,   unit:'°'},
    {key:'nu',   labelKey:'o6_lbl_nu',   helpKey:'o6_help_nu',   min:0,    max:360,   step:0.1,   unit:'°'},
  ];

  function statBlockHtml(labelKey,id){
    return `<div class="o6-stat"><div class="k" data-i18n="${labelKey}">${T(labelKey)}</div><div class="v" id="${id}">—</div></div>`;
  }

  function buildFieldRow(f){
    const row=document.createElement('div');
    row.className='o6-row'; row.dataset.key=f.key;

    const head=document.createElement('div');
    head.className='o6-row-head';
    const label=document.createElement('label');
    label.setAttribute('data-i18n',f.labelKey); label.textContent=T(f.labelKey);
    const helpBtn=document.createElement('div');
    helpBtn.className='o6-help-btn'; helpBtn.textContent='?';
    head.appendChild(label); head.appendChild(helpBtn);
    row.appendChild(head);

    const helpText=document.createElement('div');
    helpText.className='o6-help-text';
    helpText.setAttribute('data-i18n',f.helpKey); helpText.textContent=T(f.helpKey);
    helpBtn.addEventListener('click',()=>helpText.classList.toggle('open'));
    row.appendChild(helpText);

    const sliderLine=document.createElement('div');
    sliderLine.className='o6-slider-line';
    const range=document.createElement('input');
    range.type='range'; range.min=f.min; range.max=f.max; range.step=f.step; range.value=state[f.key];
    const num=document.createElement('input');
    num.type='number'; num.min=f.min; num.max=f.max; num.step=f.step; num.value=state[f.key];
    const unit=document.createElement('span');
    unit.className='o6-unit'; unit.textContent=f.unit;

    function onInput(v){
      let val=parseFloat(v);
      if(isNaN(val)) return;
      val=Math.min(f.max,Math.max(f.min,val));
      state[f.key]=val; range.value=val; num.value=val;
      refreshAll();
    }
    range.addEventListener('input',e=>onInput(e.target.value));
    num.addEventListener('input',e=>onInput(e.target.value));

    sliderLine.appendChild(range); sliderLine.appendChild(num); sliderLine.appendChild(unit);
    row.appendChild(sliderLine);
    row._inputs = {range,num};
    return row;
  }

  const fieldRows = {};

  function render(bodyEl){
    panelBodyEl = bodyEl;
    bodyEl.innerHTML = '';
    const root=document.createElement('div');
    root.className='o6-panel';

    const titleRow=document.createElement('div');
    titleRow.style.cssText='display:flex;align-items:center;justify-content:space-between;gap:8px';
    const title=document.createElement('div');
    title.className='o6-title'; title.setAttribute('data-i18n','o6_title'); title.textContent=T('o6_title');
    const aboutLink=document.createElement('a');
    aboutLink.href='/orbit-tuner'; aboutLink.target='_blank'; aboutLink.rel='noopener';
    aboutLink.style.cssText='font-size:9px;color:#8b949e;text-decoration:none;white-space:nowrap';
    aboutLink.setAttribute('data-i18n','o6_about'); aboutLink.textContent=T('o6_about');
    titleRow.appendChild(title); titleRow.appendChild(aboutLink);
    root.appendChild(titleRow);

    const presetsWrap=document.createElement('div');
    presetsWrap.className='o6-presets';
    [['iss','o6_preset_iss'],['gps','o6_preset_gps'],['geo','o6_preset_geo'],['molniya','o6_preset_molniya']]
      .forEach(([key,labelKey])=>{
        const b=document.createElement('button');
        b.type='button'; b.className='o6-preset-btn';
        b.setAttribute('data-i18n',labelKey); b.textContent=T(labelKey);
        b.addEventListener('click',()=>applyPreset(key));
        presetsWrap.appendChild(b);
      });
    root.appendChild(presetsWrap);

    FIELDS.forEach(f=>{
      const row=buildFieldRow(f);
      fieldRows[f.key]=row;
      root.appendChild(row);
    });

    const stats=document.createElement('div');
    stats.className='o6-stats';
    stats.innerHTML = statBlockHtml('o6_stat_apogee','o6-stat-apogee')
      + statBlockHtml('o6_stat_perigee','o6-stat-perigee')
      + statBlockHtml('o6_stat_period','o6-stat-period');
    root.appendChild(stats);

    const actions=document.createElement('div');
    actions.className='o6-actions';
    actions.innerHTML = `<label><input type="checkbox" id="o6-show-chk" ${showOnGlobe?'checked':''}/> `
      + `<span data-i18n="o6_show">${T('o6_show')}</span></label>`
      + `<button type="button" id="o6-focus-btn" data-i18n="o6_focus">${T('o6_focus')}</button>`;
    root.appendChild(actions);

    const connect=document.createElement('div');
    connect.className='o6-connect';
    connect.innerHTML = `
      <div class="o6-title" data-i18n="o6_connect_title">${T('o6_connect_title')}</div>
      <div class="o6-connect-hint" data-i18n="o6_connect_hint">${T('o6_connect_hint')}</div>
      <input type="text" id="o6-sat-name" value="${satName}" data-i18n-placeholder="o6_connect_sat" placeholder="${T('o6_connect_sat')}"/>
      <textarea id="o6-connect-cmd" readonly spellcheck="false"></textarea>
      <div class="o6-connect-btns">
        <button type="button" id="o6-copy-btn" data-i18n="o6_connect_copy">${T('o6_connect_copy')}</button>
        <button type="button" id="o6-now-btn" data-i18n="o6_connect_now">${T('o6_connect_now')}</button>
      </div>`;
    root.appendChild(connect);

    bodyEl.appendChild(root);

    root.querySelector('#o6-show-chk').addEventListener('change',e=>{
      showOnGlobe=e.target.checked;
      updateGlobeEntities();
    });
    root.querySelector('#o6-focus-btn').addEventListener('click',focusOnOrbit);
    root.querySelector('#o6-sat-name').addEventListener('input',e=>{
      satName = e.target.value.trim() || 'OrbitTunerSat';
      refreshConnectCmd();
    });
    root.querySelector('#o6-now-btn').addEventListener('click',()=>{
      connectEpoch = nowUtcSTKEpoch();
      refreshConnectCmd();
    });
    root.querySelector('#o6-copy-btn').addEventListener('click',copyConnectCmd);

    refreshAll();
  }

  function applyPreset(key){
    const p=PRESETS[key];
    if(!p) return;
    state = Object.assign({},p);
    FIELDS.forEach(f=>{
      const row=fieldRows[f.key];
      if(!row||!row._inputs) return;
      row._inputs.range.value=state[f.key];
      row._inputs.num.value=state[f.key];
    });
    refreshAll();
  }

  function refreshConnectCmd(){
    if(!panelBodyEl) return;
    const ta=panelBodyEl.querySelector('#o6-connect-cmd');
    if(ta) ta.value=buildConnectCommand();
  }

  function refreshStats(){
    if(!panelBodyEl) return;
    const st=computeStats(state);
    const apoEl=panelBodyEl.querySelector('#o6-stat-apogee');
    const periEl=panelBodyEl.querySelector('#o6-stat-perigee');
    const perEl=panelBodyEl.querySelector('#o6-stat-period');
    if(apoEl) apoEl.textContent=st.apogeeAlt.toFixed(1)+' km';
    if(periEl) periEl.textContent=st.perigeeAlt.toFixed(1)+' km';
    if(perEl) perEl.textContent=st.periodMin.toFixed(1)+' '+T('o6_min');
  }

  function refreshAll(){
    refreshStats();
    refreshConnectCmd();
    updateGlobeEntities();
  }

  function copyConnectCmd(){
    if(!panelBodyEl) return;
    const ta=panelBodyEl.querySelector('#o6-connect-cmd');
    const btn=panelBodyEl.querySelector('#o6-copy-btn');
    if(!ta) return;
    const text=ta.value;
    const done=()=>{
      if(!btn) return;
      const orig=T('o6_connect_copy');
      btn.textContent=T('o6_connect_copied');
      btn.classList.add('copied');
      setTimeout(()=>{ btn.textContent=orig; btn.classList.remove('copied'); },1500);
    };
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(text).then(done).catch(()=>{ ta.select(); document.execCommand('copy'); done(); });
    } else {
      ta.select(); document.execCommand('copy'); done();
    }
  }

  window.OrbitTuner = { render, clear: clearEntities };
})();
