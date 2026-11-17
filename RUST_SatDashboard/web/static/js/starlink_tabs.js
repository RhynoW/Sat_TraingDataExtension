'use strict';
/* /starlink 分頁：台灣服務分析（starlink.js）＋ 顆數普查 ＋ V3 佈署 ＋ 離軌名單。
   原 /starlink-census、/starlink-v3、/starlink-deorbit 三頁併入；舊網址由後端 302 轉址到 ?tab=。
   語言沿用 starlink.js 的 LANG／setLang；各分頁首次開啟時才抓資料。 */
(function () {
  const TAB_NAMES = ['analysis', 'census', 'v3', 'deorbit'];
  const TAB_LABELS = {
    zh: { analysis: '台灣服務分析', census: '顆數普查', v3: 'V3 佈署', deorbit: '離軌名單' },
    en: { analysis: 'Taiwan Service', census: 'Count Audit', v3: 'V3 Deployment', deorbit: 'Deorbiting' },
    ja: { analysis: '台湾サービス分析', census: '機数調査', v3: 'V3 展開', deorbit: '離軌リスト' },
  };

  function curLang() { try { return LANG; } catch (e) { return 'zh'; } }   // starlink.js 的全域 LANG
  function tr(dict, key, vars) {
    const d = dict[curLang()] || dict.zh;
    let s = (key in d) ? d[key] : (dict.zh[key] !== undefined ? dict.zh[key] : key);
    if (vars) Object.keys(vars).forEach(k => { s = s.split('{' + k + '}').join(String(vars[k])); });
    return s;
  }
  const fmtN = n => (n === null || n === undefined) ? '—' : Number(n).toLocaleString();
  const fmtT = iso => iso ? iso.replace('T', ' ').replace('Z', '').slice(0, 16) : '—';
  const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const head = (dict, icon) => `<h2 class="sl-h">${icon} ${tr(dict, 'page_title')}</h2><p class="sl-sub">${tr(dict, 'page_sub')}</p>`;

  // ═══ 顆數普查 ═══════════════════════════════════════════════════════════════
  const CENSUS = {
    zh: {
      page_title: 'Starlink 顆數普查', loading: '載入中…',
      page_sub: '即時比對 keeptrack.space 公開的 Starlink 在軌顆數，與本系統依不同統計口徑算出的實際數字，說明差異的成因。',
      kt_title: 'keeptrack.space 公開數字', ours_title: '本系統依不同口徑算出的數字', explain_title: '為什麼數字會不一樣？',
      kt_in_orbit: '在軌（In Orbit）', kt_working: '運作中（Working）', kt_launched: '累計發射（Launched）',
      kt_as_of: '資料時間：{d}', kt_source: '資料來源：keeptrack.space（自動抓取，快取 6 小時）',
      kt_error: '無法即時取得 keeptrack.space 資料：{err}（對方網站可能暫時無法連線或改版，之後可重新整理再試）',
      ours_cumulative: '累計曾出現過（不篩新鮮度）', ours_30d: '近 30 天有 TLE', ours_14d: '近 14 天有 TLE', ours_7d: '近 7 天有 TLE',
      ours_epoch: '本系統資料庫最新 TLE 時刻：{d}',
      th_metric: '統計方式', th_count: '顆數', th_vs_kt: '對照 keeptrack「在軌」', match: '接近', gap: '偏高',
      explain_p1: 'keeptrack.space 的「在軌（In Orbit）」= 累計發射 − 已確認再入者，也就是「目前扣除掉已離軌的」。',
      explain_p2: '本系統若不做任何新鮮度篩選、單純數「資料庫裡曾經出現過名稱含 STARLINK 的相異 NORAD 數」，會偏高，因為這個口徑還留著一批「近一個月已無新 TLE、依最後已知高度判斷極可能已經再入大氣層」的舊衛星。',
      explain_p3: '一旦改用「近 30 天內仍有 TLE 更新」這個口徑，本系統的數字會非常接近 keeptrack 的「在軌」數字——殘餘的個位數/十位數差距，來自兩邊資料快照時間點不同、以及新鮮度門檻定義的些微差異，屬正常範圍。',
      explain_p4: '「離軌名單」分頁使用即時查詢，可以看到那些高度快速下降的候選衛星。', go_deorbit: '前往離軌名單 →',
    },
    en: {
      page_title: 'Starlink Satellite Count Audit', loading: 'Loading…',
      page_sub: "Live comparison of keeptrack.space's public Starlink in-orbit count against this system's own counts under different methodologies, explaining the gap.",
      kt_title: 'keeptrack.space Public Numbers', ours_title: "This System's Counts Under Different Methodologies", explain_title: 'Why Do the Numbers Differ?',
      kt_in_orbit: 'In Orbit', kt_working: 'Working', kt_launched: 'Launched (Total)',
      kt_as_of: 'As of: {d}', kt_source: 'Source: keeptrack.space (auto-fetched, cached 6 h)',
      kt_error: 'Could not fetch live data from keeptrack.space: {err} (the site may be temporarily unreachable or redesigned; try refreshing later)',
      ours_cumulative: 'Ever seen (no freshness filter)', ours_30d: 'TLE within last 30 days', ours_14d: 'TLE within last 14 days', ours_7d: 'TLE within last 7 days',
      ours_epoch: "This system's latest TLE timestamp: {d}",
      th_metric: 'Method', th_count: 'Count', th_vs_kt: 'vs. keeptrack "In Orbit"', match: 'Close match', gap: 'Overcounts',
      explain_p1: 'keeptrack.space\'s "In Orbit" = total launched minus confirmed reentries — i.e., "currently minus those already deorbited."',
      explain_p2: 'If this system counts, with no freshness filter, every distinct NORAD ID whose name has ever contained STARLINK in the database, the result runs high because it still includes older satellites with no new TLE in roughly the last month, whose last-known altitude strongly suggests they have already reentered.',
      explain_p3: 'Once filtered to "TLE updated within the last 30 days," this system\'s number comes very close to keeptrack\'s "In Orbit" figure — the small residual gap is normal, arising from different snapshot times and slightly different freshness thresholds.',
      explain_p4: 'The "Deorbiting" tab is a live query showing candidate satellites with rapidly dropping altitude.', go_deorbit: 'Go to the deorbit list →',
    },
    ja: {
      page_title: 'Starlink 機数調査', loading: '読み込み中…',
      page_sub: 'keeptrack.space が公開しているStarlinkの在軌機数と、本システムが異なる集計方法で算出した実際の数値をリアルタイムで比較し、差異の原因を説明します。',
      kt_title: 'keeptrack.space の公開数値', ours_title: '本システムによる異なる集計方法での数値', explain_title: 'なぜ数値が異なるのか？',
      kt_in_orbit: '在軌（In Orbit）', kt_working: '稼働中（Working）', kt_launched: '累計打ち上げ数（Launched）',
      kt_as_of: 'データ時点：{d}', kt_source: 'データ出典：keeptrack.space（自動取得、6時間キャッシュ）',
      kt_error: 'keeptrack.space からのリアルタイムデータ取得に失敗しました：{err}（相手サイトが一時的に接続不能か、構成変更の可能性があります。後ほど再読み込みしてください）',
      ours_cumulative: '累計で出現（鮮度フィルタなし）', ours_30d: '直近30日以内にTLEあり', ours_14d: '直近14日以内にTLEあり', ours_7d: '直近7日以内にTLEあり',
      ours_epoch: '本システムのデータベース最新TLE時刻：{d}',
      th_metric: '集計方法', th_count: '機数', th_vs_kt: 'keeptrack「在軌」との比較', match: '近い', gap: '多め',
      explain_p1: 'keeptrack.space の「在軌（In Orbit）」＝ 累計打ち上げ数 − 再突入確認済み機数、つまり「現在から既に離軌したものを除いた数」です。',
      explain_p2: '本システムが鮮度フィルタなしに、名称にSTARLINKを含む相異なるNORAD IDを単純に数えると数値が多くなります。直近1か月ほど新しいTLEがなく、最後の高度から見て再突入した可能性が高い旧衛星がまだ含まれているためです。',
      explain_p3: '「直近30日以内にTLE更新あり」でフィルタすると、keeptrack の「在軌」数値に非常に近くなります。残る若干の差は、データ取得タイミングや鮮度しきい値の違いによるもので、正常な範囲内です。',
      explain_p4: '「離軌リスト」タブはリアルタイムクエリで、高度が急速に低下している候補衛星を表示します。', go_deorbit: '離軌リストへ →',
    },
  };
  const census = {
    data: null, err: null,
    load() {
      fetch('/api/starlink/census').then(r => r.json()).then(d => { this.data = d; this.render(); })
        .catch(e => { this.err = String(e); this.render(); });
    },
    render() {
      const T = (k, v) => tr(CENSUS, k, v), el = document.getElementById('panel-census');
      let kt = `<div class="sl-loading">${T('loading')}</div>`, ours = kt;
      if (this.err) kt = `<div class="sl-err">${esc(this.err)}</div>`, ours = '';
      if (this.data) {
        const k = this.data.keeptrack || {}, o = this.data.ours || {};
        kt = k.error ? `<div class="sl-err">${T('kt_error', { err: esc(k.error) })}</div>` : `
          <div class="sl-stat-row">
            <div class="sl-stat"><div class="n">${fmtN(k.in_orbit)}</div><div class="l">${T('kt_in_orbit')}</div></div>
            <div class="sl-stat"><div class="n">${fmtN(k.working)}</div><div class="l">${T('kt_working')}</div></div>
            <div class="sl-stat"><div class="n">${fmtN(k.launched_total)}</div><div class="l">${T('kt_launched')}</div></div>
          </div>
          <div class="sl-note">${k.as_of ? T('kt_as_of', { d: esc(k.as_of) }) + '　·　' : ''}${T('kt_source')}
            　·　<a href="${esc(k.source_url)}" target="_blank" rel="noopener">${esc(k.source_url)}</a></div>`;
        if (o.error) ours = `<div class="sl-err">${esc(o.error)}</div>`;
        else {
          const rows = [['ours_cumulative', o.cumulative_all_time], ['ours_30d', o.fresh_30d], ['ours_14d', o.fresh_14d], ['ours_7d', o.fresh_7d]]
            .map(([key, v]) => {
              let badge = '';
              if (typeof k.in_orbit === 'number' && typeof v === 'number') {
                const diff = Math.abs(v - k.in_orbit);
                badge = diff <= 50 ? `<span class="sl-badge match">${T('match')} (Δ${diff})</span>`
                                   : `<span class="sl-badge gap">${T('gap')} (+${v - k.in_orbit})</span>`;
              }
              return `<tr><td>${T(key)}</td><td class="num">${fmtN(v)}</td><td>${badge}</td></tr>`;
            }).join('');
          ours = `<table class="sl-table"><thead><tr><th>${T('th_metric')}</th><th>${T('th_count')}</th><th>${T('th_vs_kt')}</th></tr></thead>
            <tbody>${rows}</tbody></table>
            <div class="sl-note">${T('ours_epoch', { d: (o.db_latest_epoch || '—').replace('T', ' ').slice(0, 19) })}</div>`;
        }
      }
      el.innerHTML = head(CENSUS, '🛰') + `
        <div class="sl-card"><h3>${T('kt_title')}</h3>${kt}</div>
        <div class="sl-card"><h3>${T('ours_title')}</h3>${ours}</div>
        <div class="sl-card"><h3>${T('explain_title')}</h3>
          <p>${T('explain_p1')}</p><p>${T('explain_p2')}</p><p>${T('explain_p3')}</p><p>${T('explain_p4')}</p>
          <a class="sl-btn" href="?tab=deorbit" onclick="slShowTab('deorbit');return false">${T('go_deorbit')}</a></div>`;
    },
  };

  // ═══ V3 佈署 ════════════════════════════════════════════════════════════════
  const V3 = {
    zh: {
      page_title: 'Starlink V3 佈署數量統計', loading: '載入中…',
      page_sub: '追蹤 Starlink V3（新一代營運衛星）的部署進度：以 TLE 國際編號精確比對已知的 Starship 部署批次，並列出 CelesTrak 補充檔中尚未正式編目的暫定名單。',
      stat_label: '本系統已編目的 V3 衛星數', schedule_title: '已知的 V3 部署批次',
      schedule_note: 'Starship Flight 14 於 2026-09-28 12:46 UTC 自 Starbase 發射，首度進入軌道並部署 26 顆 Starlink V3，SpaceX 確認全數建立聯繫。V3 單顆約 2,000 kg（報導引述之標稱值；V2 Mini 約 800 kg）；26 顆合計約 52 公噸為換算值，非官方實測。首批入軌高度約 270 km（低傾角停泊軌道），遠低於原先估計的工作殼層，之後仍會變軌抬升。',
      list_title: '已編目的 V3 衛星清單', method_title: '判定方法與限制',
      meta_line: '已知批次（{launches}）中，{n} 顆已完成 Space-Track 正式編目並進入本系統；資料庫最新 TLE 時刻：{t}',
      th_name: '衛星', th_norad: 'NORAD', th_first: '首次見於', th_alt: '高度 (km)',
      method_p1: '每次 Starship 部署一批 V3 都有固定的國際編號前綴（發射年＋當年度發射序號，例如 2026-225）。本頁直接解析 TLE 中的國際編號欄位、比對已知的部署批次清單，這是精確比對，不是猜測；清單見上方「已知的 V3 部署批次」。',
      method_p2: '衛星從發射到 Space-Track 正式編目、TLE 進入本系統每日管線，通常需要 1–2 天空窗期。這段期間本頁改顯示下方 CelesTrak 補充檔的暫定名單（來自 SpaceX 自行提供的軌道根數），待正式編目後會自動轉入上方已編目清單並換成真正的 NORAD 編號。',
      method_p3: '本頁為即時查詢，不需要手動更新；新增部署批次時需由本系統維護者將其國際編號前綴加入追蹤清單。',
      provisional_title: 'CelesTrak 補充檔暫定名單（尚未正式編目）',
      provisional_note: '以下資料來自 CelesTrak 補充檔（SpaceX 自行提供的軌道根數，非 Space-Track 官方編目）。NORAD 編號為 CelesTrak 暫用碼、非正式 SATCAT 號碼，不會寫入本系統資料庫；一旦正式編目即會改列入上方清單。',
      provisional_zero: 'CelesTrak 補充檔目前查無暫定資料——可能是本批衛星已全數完成正式編目（請看上方清單），也可能是查詢暫時失敗。',
      provisional_error: 'CelesTrak 暫定名單查詢失敗：{err}',
      th_oid: '國際編號', th_incl: '傾角 (°)', th_epoch: 'Epoch (UTC)',
    },
    en: {
      page_title: 'Starlink V3 Deployment Count', loading: 'Loading…',
      page_sub: 'Tracks Starlink V3 (next-generation) deployment progress: matches known Starship launch batches precisely via the TLE international designator, and lists provisional (not yet officially cataloged) satellites from the CelesTrak supplemental file.',
      stat_label: 'V3 satellites cataloged in this system', schedule_title: 'Known V3 launch batches',
      schedule_note: 'Starship Flight 14 launched from Starbase at 12:46 UTC on 2026-09-28, reached orbit for the first time and deployed 26 Starlink V3 satellites; SpaceX confirmed contact with all 26. Each V3 is about 2,000 kg (nominal figure quoted in reports; V2 Mini about 800 kg); the 26-satellite total of about 52 t is a derived figure, not an official measurement. The first batch reached an initial altitude of roughly 270 km (a low-inclination parking orbit), well below the previously assumed working shells, and will still raise orbit.',
      list_title: 'Cataloged V3 satellites', method_title: 'Method and limitations',
      meta_line: 'Of the known batches ({launches}), {n} satellites have been officially cataloged by Space-Track and are in this system; latest TLE timestamp in this database: {t}',
      th_name: 'Satellite', th_norad: 'NORAD', th_first: 'First seen', th_alt: 'Altitude (km)',
      method_p1: 'Each Starship V3 deployment batch has a fixed international-designator prefix (launch year + launch number of the year, e.g. 2026-225). This page parses that field directly from the TLE and matches it against a maintained list of known batches — an exact match, not a guess; see "Known V3 launch batches" above.',
      method_p2: 'It usually takes 1–2 days from launch to official Space-Track cataloging and the TLE entering this system\'s daily pipeline. During that gap this page instead shows the provisional roster below, sourced from CelesTrak\'s supplemental file (orbital elements supplied by SpaceX itself); once officially cataloged, satellites move up to the cataloged list above under their real NORAD number.',
      method_p3: "This page is a live query and needs no manual update; adding a new launch batch requires this system's maintainer to add its designator prefix to the tracked list.",
      provisional_title: 'Provisional roster from CelesTrak supplemental file (not yet officially cataloged)',
      provisional_note: 'The data below comes from the CelesTrak supplemental file (orbital elements supplied by SpaceX itself, not an official Space-Track catalog entry). NORAD numbers here are CelesTrak placeholder IDs, not official SATCAT numbers, and are not stored in this system\'s database; once officially cataloged, a satellite moves to the list above.',
      provisional_zero: 'No provisional data found in the CelesTrak supplemental file — this batch may already be fully cataloged (see the list above), or the lookup may have failed temporarily.',
      provisional_error: 'CelesTrak provisional roster lookup failed: {err}',
      th_oid: 'Int\'l designator', th_incl: 'Inclination (°)', th_epoch: 'Epoch (UTC)',
    },
    ja: {
      page_title: 'Starlink V3 展開機数統計', loading: '読み込み中…',
      page_sub: 'Starlink V3（新世代運用衛星）の展開状況を追跡します。TLEの国際標識でStarshipの既知の打ち上げバッチを正確に照合し、CelesTrak補足ファイルに掲載されている未登録の暫定機体も一覧表示します。',
      stat_label: '本システムに登録済みのV3機数', schedule_title: '既知のV3打ち上げバッチ',
      schedule_note: 'Starship Flight 14 は 2026-09-28 12:46 UTC に Starbase から打ち上げられ、初めて軌道に到達して Starlink V3 を26機展開し、SpaceX は全機との通信確立を確認しました。V3 は1機約 2,000 kg（報道で引用された公称値；V2 Mini は約 800 kg）で、26機合計約52トンは換算値であり公式の実測値ではありません。初期投入高度は約270 km（低傾斜角のパーキング軌道）で、想定していた運用殻層より大幅に低く、その後も軌道上昇を続けます。',
      list_title: '登録済みのV3衛星一覧', method_title: '判定方法と限界',
      meta_line: '既知のバッチ（{launches}）のうち、{n} 機が Space-Track に正式登録され本システムに反映済み。本システムの最新TLE時刻：{t}',
      th_name: '衛星', th_norad: 'NORAD', th_first: '初検出', th_alt: '高度 (km)',
      method_p1: 'Starship によるV3展開バッチにはそれぞれ固定の国際標識プレフィックス（打ち上げ年＋その年の打ち上げ通し番号、例：2026-225）があります。本ページはTLEのこのフィールドを直接解析し、追跡中の既知バッチ一覧と照合します——推測ではなく正確な照合です。一覧は上記「既知のV3打ち上げバッチ」を参照。',
      method_p2: '打ち上げから Space-Track への正式登録、TLEが本システムの日次パイプラインに入るまで、通常1〜2日の空白期間があります。この間は下記のCelesTrak補足ファイルによる暫定機体一覧（SpaceX自身が提供する軌道要素）を表示します。正式登録後は自動的に上記の登録済み一覧に移り、正式なNORAD番号に置き換わります。',
      method_p3: '本ページはリアルタイムクエリのため手動更新は不要です。新しい打ち上げバッチを追加する場合は、本システムの管理者が国際標識プレフィックスを追跡リストに追加する必要があります。',
      provisional_title: 'CelesTrak補足ファイルによる暫定機体一覧（未登録）',
      provisional_note: '以下のデータはCelesTrak補足ファイル（SpaceX自身が提供する軌道要素で、Space-Trackの正式登録ではありません）によるものです。ここに表示されるNORAD番号はCelesTrakの仮番号であり正式なSATCAT番号ではなく、本システムのデータベースには保存されません。正式登録され次第、上記の一覧に移動します。',
      provisional_zero: 'CelesTrak補足ファイルに暫定データが見つかりませんでした——このバッチはすでに正式登録が完了している（上記の一覧を参照）か、取得が一時的に失敗した可能性があります。',
      provisional_error: 'CelesTrak暫定機体一覧の取得に失敗しました：{err}',
      th_oid: '国際標識', th_incl: '傾斜角 (°)', th_epoch: 'Epoch (UTC)',
    },
  };

  const v3 = {
    data: null, err: null,
    load() {
      fetch('/api/starlink/v3_census').then(r => r.json()).then(d => { this.data = d; this.render(); })
        .catch(e => { this.err = String(e); this.render(); });
    },
    render() {
      const T = (k, v) => tr(V3, k, v), el = document.getElementById('panel-v3'), d = this.data;
      let statN = '—', meta = this.err ? `<span class="sl-err">${esc(this.err)}</span>` : T('loading');
      let list = '', provBlock = '';
      if (d && d.error) {
        meta = `<span class="sl-err">${esc(d.error)}</span>`;
      } else if (d) {
        statN = fmtN(d.candidate_count);
        meta = T('meta_line', {
          launches: (d.intl_launches || []).join('、'), n: d.candidate_count,
          t: (d.db_latest_epoch || '').replace('T', ' ').slice(0, 19) + ' UTC',
        });
        if (d.items && d.items.length) {
          list = `<div class="sl-card"><h3>${T('list_title')}</h3><table class="sl-table"><thead><tr><th>${T('th_name')}</th>
            <th>${T('th_norad')}</th><th>${T('th_first')}</th><th>${T('th_alt')}</th></tr></thead><tbody>${
            d.items.map(it => `<tr><td>${esc(it.name)}</td><td class="num">${it.norad_id}</td>
              <td>${fmtT(it.first_epoch)}</td><td class="num">${it.alt_km}</td></tr>`).join('')}</tbody></table></div>`;
        }
        const p = d.provisional || {};
        let provInner;
        if (p.error) {
          provInner = `<div class="sl-err">${esc(T('provisional_error', { err: p.error }))}</div>`;
        } else if (!p.items || !p.items.length) {
          provInner = `<div class="sl-note">${T('provisional_zero')}</div>`;
        } else {
          provInner = `<table class="sl-table"><thead><tr><th>${T('th_oid')}</th><th>${T('th_name')}</th>
            <th>${T('th_alt')}</th><th>${T('th_incl')}</th><th>${T('th_epoch')}</th></tr></thead><tbody>${
            p.items.map(it => `<tr><td>${esc(it.object_id || '—')}</td><td>${esc(it.name || '—')}</td>
              <td class="num">${it.alt_km ?? '—'}</td>
              <td class="num">${it.inclination_deg != null ? Number(it.inclination_deg).toFixed(1) : '—'}</td>
              <td>${fmtT(it.epoch)}</td></tr>`).join('')}</tbody></table>`;
        }
        provBlock = `<div class="sl-card"><h3>${T('provisional_title')}</h3><p class="sl-note">${T('provisional_note')}</p>${provInner}</div>`;
      }
      el.innerHTML = head(V3, '🚀') + `
        <div class="sl-card"><div class="sl-stat-big"><div class="n">${statN}</div><div class="l">${T('stat_label')}</div></div>
          <div class="sl-note">${meta}</div></div>
        <div class="sl-card"><h3>${T('schedule_title')}</h3><div class="sl-warn">${T('schedule_note')}</div></div>
        ${list}
        ${provBlock}
        <div class="sl-card"><h3>${T('method_title')}</h3><p>${T('method_p1')}</p><p>${T('method_p2')}</p><p>${T('method_p3')}</p></div>`;
    },
  };

  // ═══ 離軌名單 ═══════════════════════════════════════════════════════════════
  const DEORBIT = {
    zh: {
      page_title: '正在離軌的 Starlink', loading: '載入中…',
      page_sub: '即時查詢：近 5 天仍有 TLE、近 30 天半長軸下降逾 40 km、且高度低於 480 km 的 Starlink 衛星（離軌候選）。「預測再入」為分段等效面積校準（Remis 2026）之數值積分預測，背景每 6 小時更新；點「詳細」可即時重算並對照 SGP4 外推。',
      meta_line: '符合條件共 {total} 顆，顯示前 {shown} 顆　·　更新時間 {t}', forecast_meta: '　·　再入預測批次 {t} UTC（{n} 顆）',
      th_name: '衛星', th_norad: 'NORAD', th_launch: '發射日', th_alt: '目前高度 (km)', th_da30: '30 天 Δ高度 (km)', th_da7: '7 天 Δ高度 (km)',
      th_seg: '預測再入 (UTC)', th_est: '線性粗估天數', th_detail: '詳細', btn_detail: '詳細 ▾', btn_hide: '收合 ▴',
      seg_pending: '計算中', seg_beyond: '10 天內未再入', seg_thrust: '疑似推進', seg_past: '應已再入',
      detail_loading: '計算中（分段等效面積校準＋SGP4 對照，約 5–15 秒）…',
      detail_seg: '分段校準預測再入：{t} UTC　區間 {e} ～ {l}（距最後 TLE {h} 小時）',
      detail_seg_beyond: '分段校準：10 天積分範圍內未降到 80 km', detail_seg_err: '分段校準失敗：{err}',
      detail_thrust: '⚠ 最近一段等效面積跳升或半長軸上升，疑似推進器點火，此預測不可靠（點火期間無法由 TLE 預測）。',
      detail_B: '逐段彈道係數 B（紅點＝疑似推進段）', detail_sw: '太空天氣：{d} 之後以最後觀測值持平', detail_sgp4: '對照｜SGP4 逐圈外推：',
      detail_reentered: '預估再入圈次：{t}　·　次衛星點 {lat}°, {lon}°　·　高度 {alt} km',
      detail_not_found: '在 {days} 天外推範圍內未找到再入圈次（可能衰減較慢，或已超出模型可靠範圍）', detail_error: '計算失敗：{err}',
      note_line: '「預測再入」以相鄰 TLE 對分段校準等效彈道係數，再以兩體＋J2–J4＋NRLMSISE-00 阻力數值積分至 80 km；區間取「彈道係數範圍」與「±25%×剩餘時數」較寬者。以 2026 年 38 顆 Starlink 自然再入對照官方 TIP 回測：再入前 24 小時中位誤差 +1.3 小時、12 小時 +0.5 小時、6 小時 +0.6 小時，全面優於 SGP4 外推；推進中的衛星在點火前任何 TLE 方法都無法預測。「線性粗估天數」為近 7 天平均下降率外推至 80 km，未計入阻力指數增強，會高估剩餘時間，僅供排序。資料：本系統 space_db（Space-Track GP）＋CelesTrak 太空天氣。',
    },
    en: {
      page_title: 'Deorbiting Starlink Satellites', loading: 'Loading…',
      page_sub: 'Live query: Starlink satellites with a TLE within the last 5 days, a semi-major-axis drop of more than 40 km over the last 30 days, and an altitude below 480 km (deorbit candidates). "Predicted reentry" is a numerical forecast using segmented effective-area calibration (Remis 2026), refreshed in the background every 6 hours; click "Detail" to recompute live and compare with SGP4 extrapolation.',
      meta_line: '{total} satellites match, showing top {shown}　·　updated {t}', forecast_meta: '   ·   reentry batch {t} UTC ({n} satellites)',
      th_name: 'Satellite', th_norad: 'NORAD', th_launch: 'Launch Date', th_alt: 'Current Altitude (km)', th_da30: '30-day ΔAltitude (km)', th_da7: '7-day ΔAltitude (km)',
      th_seg: 'Predicted Reentry (UTC)', th_est: 'Linear Rough Days', th_detail: 'Detail', btn_detail: 'Detail ▾', btn_hide: 'Hide ▴',
      seg_pending: 'computing', seg_beyond: 'not within 10 days', seg_thrust: 'thrusting?', seg_past: 'likely reentered',
      detail_loading: 'Computing (segmented effective-area calibration + SGP4 comparison, about 5–15 s)…',
      detail_seg: 'Segmented calibration reentry: {t} UTC   window {e} – {l} ({h} h after last TLE)',
      detail_seg_beyond: 'Segmented calibration: does not reach 80 km within the 10-day integration', detail_seg_err: 'Segmented calibration failed: {err}',
      detail_thrust: '⚠ The latest segment shows an effective-area jump or a semi-major-axis rise, suggesting thruster firing; this forecast is unreliable (reentry cannot be predicted from TLEs while thrusting).',
      detail_B: 'Ballistic coefficient B per segment (red = suspected thrust)', detail_sw: 'Space weather held at last observed values after {d}', detail_sgp4: 'Comparison | SGP4 orbit-by-orbit extrapolation:',
      detail_reentered: 'Estimated reentry pass: {t}   ·   Subsatellite point {lat}°, {lon}°   ·   Altitude {alt} km',
      detail_not_found: "No reentry pass found within the {days}-day propagation window (decay may be slower, or beyond the model's reliable range)", detail_error: 'Computation failed: {err}',
      note_line: '"Predicted reentry" calibrates an effective ballistic coefficient over successive TLE pairs, then integrates two-body + J2–J4 + NRLMSISE-00 drag down to 80 km; the window is the wider of the ballistic-coefficient range and ±25% of the remaining hours. Backtested against official TIP messages for 38 natural Starlink reentries in 2026: median error +1.3 h at 24 h before reentry, +0.5 h at 12 h and +0.6 h at 6 h, better than SGP4 extrapolation in every case; satellites that are still thrusting cannot be predicted from TLEs before the burn. "Linear rough days" extrapolates the 7-day mean descent rate to 80 km, ignores the exponential growth of drag and therefore overestimates the remaining time; for sorting only. Data: this system\'s space_db (Space-Track GP) + CelesTrak space weather.',
    },
    ja: {
      page_title: '離軌中のStarlink衛星', loading: '読み込み中…',
      page_sub: 'リアルタイムクエリ：直近5日以内にTLEがあり、直近30日間で軌道長半径が40km以上低下し、高度が480km未満のStarlink衛星（離軌候補）。「予測再突入」は区間別の等価面積較正（Remis 2026）による数値積分予測で、バックグラウンドで6時間ごとに更新されます。「詳細」で即時再計算し、SGP4外挿と比較できます。',
      meta_line: '該当 {total} 機、上位 {shown} 機を表示　·　更新時刻 {t}', forecast_meta: '　·　再突入予測バッチ {t} UTC（{n} 機）',
      th_name: '衛星', th_norad: 'NORAD', th_launch: '打ち上げ日', th_alt: '現在高度 (km)', th_da30: '30日間 Δ高度 (km)', th_da7: '7日間 Δ高度 (km)',
      th_seg: '予測再突入 (UTC)', th_est: '線形概算日数', th_detail: '詳細', btn_detail: '詳細 ▾', btn_hide: '閉じる ▴',
      seg_pending: '計算中', seg_beyond: '10日以内に再突入せず', seg_thrust: '推進の疑い', seg_past: '再突入済みの可能性',
      detail_loading: '計算中（区間別等価面積較正＋SGP4比較、約5〜15秒）…',
      detail_seg: '区間較正による再突入予測：{t} UTC　区間 {e} ～ {l}（最終TLEから {h} 時間）',
      detail_seg_beyond: '区間較正：10日間の積分範囲内で80kmに達しません', detail_seg_err: '区間較正に失敗しました：{err}',
      detail_thrust: '⚠ 直近の区間で等価面積の急増または軌道長半径の上昇があり、推進器の噴射が疑われます。この予測は信頼できません（噴射中はTLEから予測できません）。',
      detail_B: '区間ごとの弾道係数 B（赤点＝推進の疑い）', detail_sw: '宇宙天気：{d} 以降は最終観測値で持続と仮定', detail_sgp4: '比較｜SGP4による周回外挿：',
      detail_reentered: '推定再突入周回：{t}　·　直下点 {lat}°, {lon}°　·　高度 {alt} km',
      detail_not_found: '{days}日間の外挿範囲内では再突入周回が見つかりませんでした（減衰が緩やかか、モデルの信頼範囲を超えている可能性があります）', detail_error: '計算に失敗しました：{err}',
      note_line: '「予測再突入」は隣接TLEの区間ごとに等価弾道係数を較正し、二体＋J2–J4＋NRLMSISE-00抵抗で高度80kmまで数値積分します。区間は「弾道係数の範囲」と「残り時間の±25%」の広い方です。2026年のStarlink自然再突入38機を公式TIPと照合した検証では、再突入24時間前の誤差中央値+1.3時間、12時間前+0.5時間、6時間前+0.6時間で、すべてSGP4外挿より優れていました。推進中の衛星は噴射前にはどのTLE手法でも予測できません。「線形概算日数」は直近7日の平均降下速度を80kmまで外挿したもので、抵抗の指数的増大を考慮しないため残り時間を過大評価します（並べ替え用）。データ：本システムの space_db（Space-Track GP）＋CelesTrak宇宙天気。',
    },
  };
  function segCell(sg, T) {
    if (!sg) return `<small>${T('seg_pending')}</small>`;
    if (sg.error) return '<small>—</small>';
    const badge = sg.latest_segment_flag ? `<span class="sl-badge thrust">${T('seg_thrust')}</span>` : '';
    if (sg.beyond_horizon || !sg.reentry_utc) return `<span class="sl-badge far">${T('seg_beyond')}</span>${badge}`;
    const half = sg.window_early_utc && sg.window_late_utc
      ? Math.round((Date.parse(sg.window_late_utc) - Date.parse(sg.window_early_utc)) / 7.2e6) : null;
    const past = Date.parse(sg.reentry_utc) < Date.now() ? `<span class="sl-badge far">${T('seg_past')}</span>` : '';
    return `${fmtT(sg.reentry_utc)}${half != null ? ` <small>±${half} h</small>` : ''}${badge}${past}`;
  }
  function sparkB(segs) {
    const pts = (segs || []).filter(s => s.B && s.B > 0);
    if (pts.length < 2) return '';
    const W = 150, H = 34, bs = pts.map(s => s.B), lo = Math.min(...bs), hi = Math.max(...bs), span = (hi - lo) || hi || 1;
    const xy = pts.map((s, i) => [4 + i * (W - 8) / (pts.length - 1), H - 4 - (s.B - lo) / span * (H - 8)]);
    const line = xy.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
    const dots = xy.map((p, i) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.6" fill="${
      (pts[i].flag || pts[i].thrust_flag) ? '#FF5C4E' : '#35C6F4'}"/>`).join('');
    return `<svg class="sl-spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><path d="${line}" fill="none" stroke="#8b96a8" stroke-width="1.2"/>${dots}</svg>`;
  }
  const deorbit = {
    data: null, err: null, sortKey: 'alt_km', sortDir: 1, timer: null,
    load() {
      fetch('/api/starlink/deorbiting?limit=100').then(r => r.json()).then(d => { this.data = d; this.err = null; this.render(); })
        .catch(e => { this.err = String(e); this.render(); });
      if (!this.timer) this.timer = setInterval(() => this.load(), 5 * 60 * 1000);   // 每 5 分鐘自動更新
    },
    sortBy(key) {
      if (this.sortKey === key) this.sortDir *= -1; else { this.sortKey = key; this.sortDir = 1; }
      this.render();
    },
    render() {
      const T = (k, v) => tr(DEORBIT, k, v), el = document.getElementById('panel-deorbit'), d = this.data;
      let meta = T('loading'), table = '';
      if (this.err) table = `<div class="sl-err">${esc(this.err)}</div>`;
      else if (d && d.error) table = `<div class="sl-err">${esc(d.error)}</div>`;
      else if (d) {
        meta = T('meta_line', { total: d.total_matching, shown: d.shown, t: (d.generated_at || '').replace('T', ' ').slice(0, 19) + ' UTC' })
          + (d.forecast && d.forecast.generated_at ? T('forecast_meta', { t: d.forecast.generated_at.replace('T', ' ').slice(0, 16), n: d.forecast.n }) : '');
        d.items.forEach(it => { it.seg_t = it.seg && it.seg.reentry_utc ? Date.parse(it.seg.reentry_utc) : Number.POSITIVE_INFINITY; });
        const k = this.sortKey, dir = this.sortDir;
        const items = [...d.items].sort((a, b) => {
          const x = a[k], y = b[k];
          if (x === y) return 0;
          if (x === Number.POSITIVE_INFINITY) return 1;
          if (y === Number.POSITIVE_INFINITY) return -1;
          return (typeof x === 'string' ? x.localeCompare(y) : x - y) * dir;
        });
        const cols = [['name', 'th_name'], ['norad_id', 'th_norad'], ['launch_date', 'th_launch'], ['alt_km', 'th_alt'],
          ['da_30d_km', 'th_da30'], ['da_7d_km', 'th_da7'], ['seg_t', 'th_seg'], ['est_days_to_reentry_rough', 'th_est'], [null, 'th_detail']];
        const headRow = cols.map(([c, label]) => `<th ${c ? `class="sortable" onclick="slDeorbit.sortBy('${c}')"` : ''}>${T(label)}${
          c === k ? (dir > 0 ? ' ▲' : ' ▼') : ''}</th>`).join('');
        const rows = items.map(it => `
          <tr><td>${esc(it.name)}</td><td class="num">${it.norad_id}</td><td>${it.launch_date || '—'}</td>
            <td class="num">${it.alt_km}</td><td class="num neg">${it.da_30d_km}</td><td class="num neg">${it.da_7d_km}</td>
            <td class="seg">${segCell(it.seg, T)}</td><td class="num">${it.est_days_to_reentry_rough ?? '—'}</td>
            <td><button class="sl-btn-detail" onclick="slDeorbit.toggleDetail(this, ${it.norad_id})">${T('btn_detail')}</button></td></tr>
          <tr class="sl-detail-row" id="sl-detail-${it.norad_id}" style="display:none"><td colspan="9"></td></tr>`).join('');
        table = `<table class="sl-table"><thead><tr>${headRow}</tr></thead><tbody>${rows}</tbody></table>`;
      }
      el.innerHTML = head(DEORBIT, '⬇') + `<div class="sl-meta">${meta}</div>${table}<div class="sl-note">${T('note_line')}</div>`;
    },
    async toggleDetail(btn, norad) {
      const T = (k, v) => tr(DEORBIT, k, v);
      const row = document.getElementById('sl-detail-' + norad), cell = row.querySelector('td');
      if (row.style.display !== 'none') { row.style.display = 'none'; btn.textContent = T('btn_detail'); return; }
      row.style.display = ''; btn.textContent = T('btn_hide'); cell.textContent = T('detail_loading');
      try {
        const d = await (await fetch(`/api/starlink/reentry_detail?norad=${norad}&days=10`)).json();
        if (d.error) { cell.textContent = T('detail_error', { err: d.error }); return; }
        let html = '';
        const sg = d.segmented;
        if (sg && !sg.error) {
          html += sg.reentry_utc
            ? `<b>${T('detail_seg', { t: fmtT(sg.reentry_utc), e: fmtT(sg.window_early_utc), l: fmtT(sg.window_late_utc), h: sg.hours_from_last_tle })}</b>`
            : `<b>${T('detail_seg_beyond')}</b>`;
          if (sg.latest_segment_flag) html += `<br><span class="sl-crit">${T('detail_thrust')}</span>`;
          html += `<br><span class="sl-muted">${T('detail_B')}</span>${sparkB(sg.segments)}`;
          if (sg.space_weather && sg.space_weather.persisted_from)
            html += `<br><span class="sl-muted">${T('detail_sw', { d: sg.space_weather.persisted_from })}　·　${esc(sg.force_model || '')}</span>`;
        } else if (sg && sg.error) {
          html += T('detail_seg_err', { err: esc(sg.error) });
        }
        const p = d.reentry_pass;
        html += `<br><span class="sl-muted">${T('detail_sgp4')} ${p
          ? T('detail_reentered', { t: p.t, lat: p.lat, lon: p.lon, alt: p.alt_km }) : T('detail_not_found', { days: 10 })}</span>`;
        cell.innerHTML = html;
      } catch (e) { cell.textContent = T('detail_error', { err: e }); }
    },
  };
  window.slDeorbit = { sortBy: k => deorbit.sortBy(k), toggleDetail: (b, n) => deorbit.toggleDetail(b, n) };

  // ═══ 分頁切換 ═══════════════════════════════════════════════════════════════
  const PANELS = { census, v3, deorbit };
  const started = {};
  let current = null;

  function labelTabs() {
    const L = TAB_LABELS[curLang()] || TAB_LABELS.zh;
    document.querySelectorAll('#sl-tabs [data-tab]').forEach(b => { b.textContent = L[b.dataset.tab]; });
  }
  function show(name) {
    if (!TAB_NAMES.includes(name)) name = 'analysis';
    current = name;
    document.querySelectorAll('#sl-tabs [data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
    document.getElementById('panel-analysis').hidden = name !== 'analysis';
    ['census', 'v3', 'deorbit'].forEach(n => { document.getElementById('panel-' + n).hidden = n !== name; });
    try { history.replaceState(null, '', name === 'analysis' ? location.pathname : location.pathname + '?tab=' + name); } catch (e) { /* ignore */ }
    if (name === 'analysis') {
      if (window._slPendingCompute) { window._slPendingCompute = false; triggerCompute(); }
    } else if (!started[name]) {
      started[name] = true; PANELS[name].render(); PANELS[name].load();
    }
  }
  window.slShowTab = show;

  const origSetLang = window.setLang;                // starlink.js 的語言切換 → 一併重繪分頁
  window.setLang = function (lang) {
    origSetLang(lang);
    labelTabs();
    Object.keys(PANELS).forEach(n => { if (started[n]) PANELS[n].render(); });
  };

  document.addEventListener('DOMContentLoaded', () => {
    labelTabs();
    show(window.SL_TAB);
  });
}());
