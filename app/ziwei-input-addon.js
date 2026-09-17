/* Zi Wei input add-on for Mahjong Luck Calendar v7.6.
   Adds birth context without changing the existing score or claiming Zi Wei calculation. */
(() => {
  const byId = (id) => document.getElementById(id);
  const manual = byId('manual');
  const save = byId('save');
  if (!manual || !save) return;

  const style = document.createElement('style');
  style.textContent = `
    .ziwei-row{display:grid;grid-template-columns:1fr 1fr;gap:9px}
    .ziwei-advanced{margin-top:12px;border:1px solid #eadfc9;border-radius:11px;padding:10px;background:#faf4ea}
    .ziwei-advanced summary{font-weight:700;cursor:pointer}
    .ziwei-status{margin-top:9px;padding:9px 11px;border-radius:10px;background:#f3ead9;color:#741925;font-size:12px;font-weight:700}
    .ziwei-fields select{width:100%;padding:12px;border:1px solid #eadfc9;border-radius:11px;background:#fff}
  `;
  document.head.appendChild(style);

  const fields = document.createElement('div');
  fields.className = 'ziwei-fields';
  const baziLabel = manual.querySelector('label:last-of-type');
  const baziInput = byId('bazi');
  fields.innerHTML = `
    <div class="ziwei-row">
      <div><label>出生日期</label><input id="birthDate" type="date"></div>
      <div><label>出生時間</label><input id="birthTime" type="time"></div>
    </div>
    <label>出生地點</label>
    <input id="birthPlace" placeholder="例如：香港">
    <details class="ziwei-advanced">
      <summary>排盤設定</summary>
      <label>排盤類型</label>
      <select id="chartConvention">
        <option value="neutral">中性模式</option>
        <option value="qianzao">乾造規則</option>
        <option value="kunzao">坤造規則</option>
      </select>
      <label>時間方式</label>
      <select id="timeConvention">
        <option value="civil">當地民用時間</option>
        <option value="true-solar">真太陽時修正</option>
      </select>
      <label>子時換日</label>
      <select id="ziHourRule">
        <option value="next-day-23">23:00 後屬次日</option>
        <option value="same-day-late-zi">晚子時屬當日</option>
      </select>
      <label>閏月規則</label>
      <select id="leapMonthRule"><option value="standard-v1">標準規則 v1</option></select>
    </details>
    <div class="ziwei-status" id="ziweiStatus">輸入日期、時間及地點後，紫微排盤資料會一併保存。</div>
  `;
  if (baziLabel) manual.insertBefore(fields, baziLabel);
  else if (baziInput) manual.insertBefore(fields, baziInput);
  else manual.appendChild(fields);

  function loadProfile() {
    try { return JSON.parse(localStorage.getItem('mahjongProfile') || 'null'); }
    catch { return null; }
  }
  function fill(profile) {
    if (!profile) return;
    byId('birthDate').value = profile.birthDate || '';
    byId('birthTime').value = profile.birthTime || '';
    byId('birthPlace').value = profile.birthPlace || '';
    byId('chartConvention').value = profile.chartConvention || 'neutral';
    byId('timeConvention').value = profile.timeConvention || 'civil';
    byId('ziHourRule').value = profile.ziHourRule || 'next-day-23';
    byId('leapMonthRule').value = profile.leapMonthRule || 'standard-v1';
  }
  fill(loadProfile());

  const originalSave = save.onclick;
  save.onclick = (event) => {
    const result = originalSave ? originalSave.call(save, event) : undefined;
    const profile = loadProfile();
    if (!profile) return result;
    const pasteMode = byId('paste') && !byId('paste').classList.contains('hide');
    const report = byId('report')?.value || '';
    const solar = report.match(/西曆\s*[：:]\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{1,2}:\d{2}))?/);
    const chart = report.match(/姓名\s*[：:][^\r\n]*?[　 ]+([陰陽]\s*(?:乾造|坤造))/);
    profile.birthDate = pasteMode ? (solar?.[1] || profile.birthDate || '') : byId('birthDate').value;
    profile.birthTime = pasteMode ? (solar?.[2] || profile.birthTime || '') : byId('birthTime').value;
    profile.birthPlace = pasteMode ? (profile.birthPlace || '') : byId('birthPlace').value.trim();
    profile.chartConvention = pasteMode
      ? (chart?.[1]?.includes('乾造') ? 'qianzao' : chart?.[1]?.includes('坤造') ? 'kunzao' : profile.chartConvention || 'neutral')
      : byId('chartConvention').value;
    profile.timeConvention = byId('timeConvention').value;
    profile.ziHourRule = byId('ziHourRule').value;
    profile.leapMonthRule = byId('leapMonthRule').value;
    localStorage.setItem('mahjongProfile', JSON.stringify(profile));
    const pb = byId('pb');
    if (pb && profile.birthDate && profile.birthTime && profile.birthPlace && !pb.textContent.includes('紫微資料已備妥')) {
      pb.textContent += ' · 紫微資料已備妥';
    }
    return result;
  };

  if (typeof window.ctx === 'function') {
    const originalCtx = window.ctx;
    window.ctx = (date) => {
      const base = originalCtx(date);
      const profile = loadProfile() || {};
      return {
        ...base,
        birthDate: profile.birthDate || '',
        birthTime: profile.birthTime || '',
        birthPlace: profile.birthPlace || '',
        chartConvention: profile.chartConvention || 'neutral',
        timeConvention: profile.timeConvention || 'civil',
        ziHourRule: profile.ziHourRule || 'next-day-23',
        leapMonthRule: profile.leapMonthRule || 'standard-v1'
      };
    };
  }
})();
