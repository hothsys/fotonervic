// Blur Check: SSE streaming, cards, threshold slider, AI model status and download, CSV export.

// ── Blur check ───────────────────────────────────────────────────────────────
// Scores come from the server (measure_blur in backend/blur/score.py); the threshold slider
// only re-filters in the browser, so moving it never needs a rescan.
// Matches BLUR_DEFAULT_THRESHOLD in backend/blur/calibration.py. The saved setting is versioned
// because the score's scale changed when the AI quality model was added.
const BLUR_DEFAULT_THRESHOLD = 50;
const BLUR_THRESHOLD_KEY = 'blurThreshold.v3';   // v3: recalibrated to the owner's verdicts
let blurThreshold = BLUR_DEFAULT_THRESHOLD;
try {
  const saved = parseInt(localStorage.getItem(BLUR_THRESHOLD_KEY), 10);
  if (saved >= 0 && saved <= 100) blurThreshold = saved;
} catch(e) {}

let blurEventSource = null;
let blurResults = [];
const blurGroups = new Map();  // dir -> { group, grid, badge, total, blurry }
// Running counts, so each streamed result costs O(1); recounted on threshold changes
let blurCounts = { blurry: 0, low: 0, damaged: 0 };

// Compared as displayed (whole numbers), so a card showing 50 counts at threshold 50
function isBlurry(r) {
  return r.blur_score != null && Math.round(r.blur_score) >= blurThreshold;
}


function startBlurScan() {
  stopDirCount();
  const dir = document.getElementById('dir-input').value.trim();
  if (!dir) { alert('Please enter a directory path.'); return; }
  rememberScanDir(dir);

  blurResults = [];
  blurGroups.clear();
  blurCounts = { blurry: 0, low: 0, damaged: 0 };
  document.getElementById('blur-folder-list').innerHTML = '';
  document.getElementById('blur-summary-label').textContent = '';
  document.getElementById('blur-empty').style.display = 'none';
  hideScanResults();
  hideExifResults();
  syncBlurSlider();
  document.getElementById('blur-section').style.display = 'block';
  refreshQualityModelStatus();

  setBusy('blur');
  document.getElementById('progress-section').style.display = 'block';
  document.getElementById('p-bar').style.width     = '0%';
  document.getElementById('p-scanned').textContent = '0';
  document.getElementById('p-total').textContent   = '?';
  document.getElementById('p-issues').textContent  = '0';
  document.getElementById('p-eta').textContent     = '';
  document.getElementById('p-current').textContent = 'Checking focus\u2026';
  document.getElementById('p-current').classList.add('scanning-pulse');

  if (blurEventSource) blurEventSource.close();
  blurEventSource = new EventSource('/api/blur-scan?dir=' + encodeURIComponent(dir));
  blurEventSource.onmessage = e => handleBlurEvent(JSON.parse(e.data));
  blurEventSource.onerror   = () => blurDone();
}

function handleBlurEvent(ev) {
  switch (ev.type) {
    case 'total':
      document.getElementById('p-total').textContent = ev.total.toLocaleString();
      break;
    case 'scanning': {
      const pct = ev.total > 0 ? (ev.scanned / ev.total * 100).toFixed(1) : 0;
      document.getElementById('p-bar').style.width     = pct + '%';
      document.getElementById('p-scanned').textContent = ev.scanned.toLocaleString();
      document.getElementById('p-eta').textContent     = pct + '% complete';
      document.getElementById('p-current').textContent = ev.dir + '  /  ' + ev.file;
      break;
    }
    case 'blur_result':
      addBlurCard(ev);
      document.getElementById('p-issues').textContent = blurCounts.blurry.toLocaleString();
      break;
    case 'error':
      alert('Blur check error: ' + ev.message);
      blurDone();
      break;
    case 'cancelled':
    case 'complete':
      document.getElementById('p-current').textContent = ev.type === 'complete'
        ? `\u2713 Done: ${(ev.scanned||0).toLocaleString()} photos in ${ev.elapsed}s`
        : `Cancelled after ${(ev.scanned||0).toLocaleString()} photos`;
      document.getElementById('p-current').classList.remove('scanning-pulse');
      document.getElementById('p-bar').style.width = '100%';
      sortBlurCards();
      blurDone();
      break;
  }
}

function addBlurCard(ev) {
  blurResults.push(ev);
  const refs = upsertBlurFolderGroup(ev.dir);

  const card = document.createElement('div');
  card.className = 'exif-card blur-card';
  const parts = [ev.filepath];
  if (ev.sharpness != null) parts.push('Sharpness measure: ' + ev.sharpness);
  if (ev.quality != null)   parts.push('AI quality: ' + Math.round(ev.quality * 100) + '%');
  if (ev.scored_from)       parts.push('Scored from ' + ev.scored_from);
  if (ev.fine_detail_flag)  parts.push('Very little fine detail (smeared or soft), so flagged');
  card.title = parts.join('\n');
  card.blurResult = ev;

  const tags = [];
  if (isDamaged(ev))    tags.push(integrityTagHtml(ev));
  if (ev.low_detail)    tags.push('<span class="blur-tag" title="Too little detail (fog, sky, plain surfaces) to judge focus. Never counted as blurry.">Low detail</span>');
  if (ev.error)         tags.push(`<span class="blur-tag" title="${escHtml(ev.error)}">Unreadable</span>`);

  card.innerHTML = `
    <div class="exif-card-thumb" data-lightbox="${escHtml(ev.filepath)}" title="Preview"><img class="exif-card-img" data-path="${escHtml(ev.filepath)}" data-src="${escHtml(thumbnailUrl(ev.filepath))}" alt="" onerror="this.parentElement.classList.add('exif-thumb-error')"></div>
    <div class="exif-card-meta">
      <a class="exif-card-filename card-filename-link" href="#" data-reveal="${escHtml(ev.filepath)}" title="Reveal in file manager">${escHtml(ev.filename)}</a>
      <div class="blur-card-tags">
        ${ev.blur_score != null ? `<span class="blur-badge ${blurBadgeClass(ev.blur_score)}">Blur ${Math.round(ev.blur_score)}</span>` : ''}
        ${tags.join('')}
      </div>
      <div class="exif-card-size">${formatSize(ev.file_size || 0)}</div>
    </div>
  `;
  _thumbObserver.observe(card.querySelector('.exif-card-img'));
  refs.grid.appendChild(card);

  const blurry = isBlurry(ev);
  refs.total++;
  if (blurry) { refs.blurry++; blurCounts.blurry++; }
  if (isDamaged(ev)) { refs.damaged++; blurCounts.damaged++; }
  if (ev.low_detail) blurCounts.low++;
  if (styleBlurCard(card)) refs.group.style.display = '';
  renderBlurGroupBadge(refs);
  updateBlurSummary();
}

function upsertBlurFolderGroup(dir) {
  if (blurGroups.has(dir)) return blurGroups.get(dir);
  document.getElementById('blur-section').style.display = 'block';

  const group = document.createElement('div');
  group.className = 'folder-group open';
  const header = document.createElement('div');
  header.className = 'folder-header';
  header.onclick = () => toggleFolder(group);
  header.innerHTML = `
    <svg class="folder-chevron" viewBox="0 0 16 16" fill="currentColor">
      <path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <svg class="folder-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
      <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>
    </svg>
    <span class="folder-path" title="${escHtml(dir)}">${escHtml(dir)}</span>
    <div class="folder-counts"><span class="fc fc-issue"></span></div>
  `;
  group.style.display = 'none';  // shown once it has a visible card
  const body = document.createElement('div');
  body.className = 'folder-body';
  body.style.display = 'block';
  const grid = document.createElement('div');
  grid.className = 'exif-grid';
  body.appendChild(grid);
  group.appendChild(header);
  group.appendChild(body);
  document.getElementById('blur-folder-list').appendChild(group);

  const refs = { group, grid, badge: header.querySelector('.fc-issue'), total: 0, blurry: 0, damaged: 0 };
  blurGroups.set(dir, refs);
  return refs;
}

// Badge colour by fixed score bands, independent of the threshold slider
const BLUR_SHARP_BELOW = 15;
function blurBadgeClass(score) {
  score = Math.round(score);     // colour matches the number shown
  if (score < BLUR_SHARP_BELOW) return 'sharp';
  return score < BLUR_DEFAULT_THRESHOLD ? 'soft' : 'blurry';
}

// Highlight and show/hide one card for the current threshold; returns whether it's visible
function styleBlurCard(card) {
  const blurry = isBlurry(card.blurResult);
  const damaged = isDamaged(card.blurResult);
  const visible = blurry || damaged || document.getElementById('blur-show-all').checked;
  card.classList.toggle('is-blurry', blurry);
  card.classList.toggle('is-damaged', damaged);
  card.style.display = visible ? '' : 'none';
  return visible;
}

function renderBlurGroupBadge(refs) {
  refs.badge.textContent = `${refs.blurry} blurry` + (refs.damaged ? `, ${refs.damaged} damaged` : '') + ` of ${refs.total}`;
}

function updateBlurSummary() {
  const { blurry, low, damaged } = blurCounts;
  const parts = [`${blurry.toLocaleString()} of ${blurResults.length.toLocaleString()} photos blurry`];
  if (damaged) parts.push(`${damaged.toLocaleString()} damaged`);
  // Unreadable or damaged files never reach the model, so check every result, not just the first
  if (blurResults.length) parts.push(blurResults.some(r => r.method === 'ai') ? 'AI-assisted' : 'basic scoring');
  if (low)     parts.push(`${low} low detail`);
  document.getElementById('blur-summary-label').textContent = parts.join(' \u00b7 ');
  document.getElementById('blur-empty').style.display =
    (blurResults.length && !blurry && !damaged && !document.getElementById('blur-show-all').checked) ? 'block' : 'none';
}

// Full recount: after the threshold or "Show all" changes
function applyBlurThreshold() {
  blurCounts = { blurry: 0, low: 0, damaged: 0 };
  for (const r of blurResults) {
    const blurry = isBlurry(r);
    if (blurry) blurCounts.blurry++;
    if (r.low_detail) blurCounts.low++;
    if (isDamaged(r)) blurCounts.damaged++;
  }
  for (const refs of blurGroups.values()) {
    let visible = false;
    refs.blurry = 0;
    refs.damaged = 0;
    for (const card of refs.grid.children) {
      if (styleBlurCard(card)) visible = true;
      if (isBlurry(card.blurResult)) refs.blurry++;
      if (isDamaged(card.blurResult)) refs.damaged++;
    }
    renderBlurGroupBadge(refs);
    refs.group.style.display = visible ? '' : 'none';
  }
  updateBlurSummary();
}

function syncBlurSlider() {
  document.getElementById('blur-threshold').value = blurThreshold;
  document.getElementById('blur-threshold-value').textContent = blurThreshold;
}

function setBlurThreshold(value) {
  blurThreshold = Math.max(0, Math.min(100, parseInt(value, 10) || 0));
  try { localStorage.setItem(BLUR_THRESHOLD_KEY, String(blurThreshold)); } catch(e) {}
  syncBlurSlider();
  applyBlurThreshold();
}

// Blurriest first within each folder; unscored photos (low detail, unreadable) last
function sortBlurCards() {
  const key = c => c.blurResult.blur_score == null ? -1 : c.blurResult.blur_score;
  for (const refs of blurGroups.values()) {
    [...refs.grid.children].sort((a, b) => key(b) - key(a)).forEach(c => refs.grid.appendChild(c));
  }
}

// ── AI quality model status / download ──
let qualityPollTimer = null;

async function refreshQualityModelStatus() {
  let st;
  try { st = await (await fetch('/api/quality-model')).json(); } catch(e) { return; }
  const el = document.getElementById('blur-model-status');
  const dl = st.download || {};
  const mb = n => (n / 1048576).toFixed(0);
  el.className = 'blur-model-status';
  clearTimeout(qualityPollTimer);

  if (dl.state === 'downloading' || dl.state === 'verifying') {
    const pct = st.model_bytes ? Math.min(100, Math.round(dl.received / st.model_bytes * 100)) : 0;
    el.textContent = dl.state === 'verifying'
      ? 'Verifying the AI quality model\u2026'
      : `Downloading the AI quality model\u2026 ${pct}% (${mb(dl.received)} of ${mb(st.model_bytes)} MB)`;
    qualityPollTimer = setTimeout(refreshQualityModelStatus, 500);
  } else if (st.available) {
    el.classList.add('ai');
    el.textContent = dl.state === 'done'
      ? 'AI quality model installed. Run Blur Check again to use it.'
      : 'AI-assisted scoring: a trained image-quality model (CLIP-IQA+) combined with the sharpness measure.';
  } else if (!st.runtime_installed) {
    el.textContent = 'Basic scoring. The AI quality model needs onnxruntime (pip install onnxruntime); restart the app after installing it.';
  } else {
    const canDownload = !!st.download_url;
    const failed = dl.state === 'error';
    if (failed) {
      // Plain explanation, the technical cause on hover, and a way around the
      // app's download (a browser may get through where curl can't)
      el.innerHTML = `<span title="${escHtml(dl.detail || '')}"><strong>Download failed.</strong> ${escHtml(dl.error || 'Unknown error.')}</span>`
        + (canDownload ? ' <button class="btn-outline" onclick="downloadQualityModel()">Try again</button>'
            + `<span class="blur-model-alt">Or <a href="${escHtml(st.download_url)}" target="_blank" rel="noopener">download it in your browser</a>`
            + ' and put it in the app\'s <code>models</code> folder, then run Blur Check again. Until then, it uses basic scoring.</span>'
          : '');
      el.classList.add('error');
    } else {
      el.innerHTML = `<span>Basic scoring. For more reliable results across cameras and scenes, add the AI quality model (${mb(st.model_bytes)} MB, one-time download).</span>`
        + (canDownload ? ' <button class="btn-outline" onclick="downloadQualityModel()">Download model</button>'
                       : ' <span>Set QUALITY_MODEL_URL in app.conf to enable the download.</span>');
    }
    el.querySelectorAll('button').forEach(b => { b.disabled = busyMode !== null; });
  }
}

// Re-check when the user comes back to the page (e.g. after copying or renaming
// the model file in Finder), so the panel doesn't wait for the next Blur Check
// (focus: switching back from Finder; visibilitychange: back from another tab).
function recheckQualityModel() {
  if (document.visibilityState === 'visible'
      && document.getElementById('blur-section').style.display !== 'none') {
    refreshQualityModelStatus();
  }
}
window.addEventListener('focus', recheckQualityModel);
document.addEventListener('visibilitychange', recheckQualityModel);

async function downloadQualityModel() {
  try { await fetch('/api/quality-model/download', { method: 'POST' }); } catch(e) {}
  refreshQualityModelStatus();
}

function cancelBlurScan() {
  document.getElementById('cancel-btn').disabled = true;
  document.getElementById('p-current').textContent = 'Cancelling\u2026';
  fetch('/api/blur-cancel', { method: 'POST' }).catch(() => blurDone());
}

function blurDone() {
  if (blurEventSource) { blurEventSource.close(); blurEventSource = null; }
  setBusy(null);
  applyBlurThreshold();
}

function exportBlurData() {
  const header = ['Filename', 'Directory', 'Full Path', 'Blur Score', 'Sharpness', 'AI Quality', 'Method',
                  `Blurry (threshold ${blurThreshold})`, 'Low Detail', 'Integrity', 'Integrity Issue', 'Error'];
  const rows = [header];
  for (const r of blurResults) {
    rows.push([
      r.filename, r.dir, r.filepath,
      r.blur_score != null ? r.blur_score : '',
      r.sharpness  != null ? r.sharpness  : '',
      r.quality    != null ? r.quality    : '',
      r.method === 'ai' ? 'AI-assisted' : 'Basic',
      isBlurry(r) ? 'Yes' : 'No',
      r.low_detail ? 'Yes' : 'No',
      ...integrityCsvCells(r),
      r.error || '',
    ]);
  }
  const csv  = '\ufeff' + rows.map(row =>
    row.map(cell => '"' + String(cell).replace(/"/g, '""') + '"').join(',')
  ).join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = 'blur_check.csv';
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
