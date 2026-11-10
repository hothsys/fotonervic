// Scan Directory: SSE streaming, results rendering, filtering, CSV export.

let eventSource = null;
let currentFilter = 'all';

// { folderPath: { issues: [], total: 0 } }
const folderData = {};

// ── Scan ─────────────────────────────────────────────────────────────────────
// The directory box reopens on the last folder any scan was started on
function rememberScanDir(dir) {
  try { localStorage.setItem('lastScanDir', dir); } catch(e) {}
}

function startScan() {
  stopDirCount();
  const dir = document.getElementById('dir-input').value.trim();
  if (!dir) {
    alert('Please enter a directory path.');
    return;
  }

  // Reset state
  Object.keys(folderData).forEach(k => delete folderData[k]);
  document.getElementById('folder-list').innerHTML = '';
  document.getElementById('s-total').textContent       = '0';
  document.getElementById('s-exif').textContent        = '0';
  document.getElementById('s-partial').textContent     = '0';
  document.getElementById('s-corrupt').textContent     = '0';
  document.getElementById('s-unsupported').textContent = '0';
  document.getElementById('s-other').textContent       = '0';
  document.getElementById('s-scanned').textContent     = '0';
  hideScanResults();
  hideExifResults();
  hideBlurResults();

  setBusy('scan');
  document.getElementById('progress-section').style.display = 'block';
  document.getElementById('p-bar').style.width   = '0%';
  document.getElementById('p-scanned').textContent = '0';
  document.getElementById('p-total').textContent   = '?';
  document.getElementById('p-issues').textContent  = '0';
  document.getElementById('p-eta').textContent      = '';
  document.getElementById('p-current').textContent  = 'Starting\u2026';

  rememberScanDir(dir);

  if (eventSource) eventSource.close();
  eventSource = new EventSource('/api/scan?dir=' + encodeURIComponent(dir));

  eventSource.onmessage = e => {
    const ev = JSON.parse(e.data);
    handleEvent(ev);
  };

  eventSource.onerror = () => {
    scanDone();
  };
}

function handleEvent(ev) {
  switch(ev.type) {

    case 'total':
      document.getElementById('p-total').textContent = ev.total.toLocaleString();
      break;

    case 'scanning': {
      const pct = ev.total > 0 ? (ev.scanned / ev.total * 100).toFixed(1) : 0;
      document.getElementById('p-bar').style.width    = pct + '%';
      document.getElementById('p-scanned').textContent = ev.scanned.toLocaleString();
      document.getElementById('p-issues').textContent  = ev.issues.toLocaleString();
      document.getElementById('p-current').textContent = ev.dir + '  /  ' + ev.file;
      if (ev.total > 0) {
        document.getElementById('p-eta').textContent =
          pct + '% complete';
      }
      break;
    }

    case 'issue':
      addIssue(ev);
      updateSummary();
      break;

    case 'error':
      alert('Scanner error: ' + ev.message);
      scanDone();
      break;

    case 'cancelled':
    case 'complete':
      document.getElementById('p-bar').style.width = '100%';
      document.getElementById('p-current').textContent =
        ev.type === 'complete'
          ? `\u2713 Done: scanned ${(ev.scanned||0).toLocaleString()} files in ${ev.elapsed}s`
          : `Cancelled after ${(ev.scanned||0).toLocaleString()} files`;
      document.getElementById('p-current').classList.remove('scanning-pulse');
      document.getElementById('s-scanned').textContent = (ev.scanned||0).toLocaleString();
      updateSummary();
      scanDone(ev.scanned, ev.issues);
      break;
  }
}

function addIssue(ev) {
  if (!folderData[ev.dir]) {
    folderData[ev.dir] = { issues: [], total: 0 };
  }
  folderData[ev.dir].issues.push(ev);
  folderData[ev.dir].total++;

  upsertFolderGroup(ev.dir);
  appendIssueRow(ev);
}

function upsertFolderGroup(dir) {
  let group = document.getElementById('fg-' + CSS.escape(dir));
  if (group) {
    // Update count badge
    const cnt = folderData[dir].total;
    group.querySelector('.fc-issue').textContent = cnt + ' issue' + (cnt!==1?'s':'');
    return;
  }

  group = document.createElement('div');
  group.className = 'folder-group open';
  group.id = 'fg-' + CSS.escape(dir);

  group.innerHTML = `
    <div class="folder-header" onclick="toggleFolder(this.parentElement)">
      <svg class="folder-chevron" viewBox="0 0 16 16" fill="currentColor">
        <path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
      <svg class="folder-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round">
        <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>
      </svg>
      <span class="folder-path" title="${escHtml(dir)}">${escHtml(dir)}</span>
      <span class="folder-path-link" title="Copy path" data-copy="${escHtml(dir)}">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
      </span>
      <span class="folder-path-link" title="Reveal in file manager" data-reveal="${escHtml(dir)}">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
      </span>
      <div class="folder-counts">
        <span class="fc fc-issue">1 issue</span>
      </div>
    </div>
    <div class="folder-body" id="fb-${CSS.escape(dir)}"></div>
  `;

  const list = document.getElementById('folder-list');
  list.appendChild(group);
  document.getElementById('results-section').style.display = 'block';
}

function appendIssueRow(ev) {
  const body = document.getElementById('fb-' + CSS.escape(ev.dir));
  if (!body) return;

  if (!matchesFilter(ev.status)) return;

  const size = ev.file_size > 0
    ? formatSize(ev.file_size)
    : '0 B';

  const pctStr = ev.corrupt_pct != null ? ev.corrupt_pct + '%' : '';
  // Only when there's a preview to export (has_preview is missing from scans
  // saved before it existed, so those keep the button)
  const previewBtn = (RAW_EXTS.has(ev.ext) && ev.has_preview !== false)
    ? `<button class="export-preview-btn"${busyAttr()} data-extract-preview="${escHtml(ev.filepath)}">Export Preview</button>`
    : '';
  const repairBtn = (JPEG_EXTS.has(ev.ext) && ev.status === 'partial')
    ? `<button class="repair-jpeg-btn"${busyAttr()} data-repair-jpeg="${escHtml(ev.filepath)}">Repair JPG</button>`
    : '';
  const salvageBtn = (JPEG_EXTS.has(ev.ext) && ev.status === 'corrupt'
      && (ev.reason || '').includes('Missing JPEG SOI marker'))
    ? `<button class="salvage-image-btn"${busyAttr()} data-salvage-image="${escHtml(ev.filepath)}">Salvage Image</button>`
    : '';

  const row = document.createElement('div');
  row.className = 'issue-row';
  row.dataset.status = ev.status;
  row.innerHTML = `
    <div class="status-dot dot-${ev.status}"></div>
    <div class="issue-info">
      <a class="issue-filename" href="#" data-reveal="${escHtml(ev.filepath)}" title="Reveal in file manager">${escHtml(ev.filename)}</a>
      <div class="issue-reason">${escHtml(ev.reason || '')}</div>
    </div>
    <button class="copy-path-btn"${busyAttr()} data-copy="${escHtml(ev.filepath)}" title="Copy path: ${escHtml(ev.filepath)}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
    ${previewBtn}
    ${repairBtn}
    ${salvageBtn}
    <div class="issue-corrupt-pct">${pctStr}</div>
    <div class="issue-meta">${size}</div>
    <span class="status-badge badge-${ev.status}">${statusLabel(ev.status)}</span>
  `;
  body.appendChild(row);
}

function updateSummary() {
  let total = 0, exif = 0, partial = 0, corrupt = 0, unsupported = 0, other = 0;
  Object.values(folderData).forEach(fd => {
    fd.issues.forEach(i => {
      total++;
      if      (i.status === 'exif_only')    exif++;
      else if (i.status === 'partial')      partial++;
      else if (i.status === 'corrupt')      corrupt++;
      else if (i.status === 'unsupported')  unsupported++;
      else                                  other++;
    });
  });
  document.getElementById('s-total').textContent       = total.toLocaleString();
  document.getElementById('s-exif').textContent        = exif.toLocaleString();
  document.getElementById('s-partial').textContent     = partial.toLocaleString();
  document.getElementById('s-corrupt').textContent     = corrupt.toLocaleString();
  document.getElementById('s-unsupported').textContent = unsupported.toLocaleString();
  document.getElementById('s-other').textContent       = other.toLocaleString();
  document.getElementById('summary-bar').style.display = 'flex';
}

function scanDone(scanned, issues) {
  if (eventSource) { eventSource.close(); eventSource = null; }
  setBusy(null);
  document.getElementById('results-section').style.display = 'block';

  const hasIssues = Object.keys(folderData).length > 0;
  if (hasIssues) {
    const total = Object.values(folderData).reduce((s,f) => s+f.total, 0);
    document.getElementById('export-bar').style.display = 'flex';
    document.getElementById('export-label').textContent =
      total + ' issue' + (total!==1?'s':'') + ' found across '
      + Object.keys(folderData).length + ' folder'
      + (Object.keys(folderData).length!==1?'s':'');
    saveScan();
  }
  applyFilter();
}

// Keep the stream open after cancelling: the server replies with a
// 'cancelled' event, and handleEvent() then shows and saves partial results.
function cancelScan() {
  document.getElementById('cancel-btn').disabled = true;
  document.getElementById('p-current').textContent = 'Cancelling\u2026';
  fetch('/api/cancel', { method: 'POST' }).catch(() => scanDone());
}

// ── Filter ───────────────────────────────────────────────────────────────────
function setFilter(btn, filter) {
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilter();
}

function matchesFilter(status) {
  if (currentFilter === 'all') return true;
  return status === currentFilter;
}

function applyFilter() {
  let visibleCount = 0;
  document.querySelectorAll('.folder-group').forEach(group => {
    const dir = group.id.replace(/^fg-/, '');
    // Rebuild folder body with filtered rows
    const body = group.querySelector('.folder-body');
    body.innerHTML = '';

    let fdir = null;
    for (const [k,v] of Object.entries(folderData)) {
      if ('fg-' + CSS.escape(k) === group.id) { fdir = k; break; }
    }
    if (!fdir) return;

    const issues = folderData[fdir].issues;
    const visible = issues.filter(i => matchesFilter(i.status));

    visible.forEach(ev => {
      const size = ev.file_size > 0 ? formatSize(ev.file_size) : '0 B';
      const pctStr = ev.corrupt_pct != null ? ev.corrupt_pct + '%' : '';
      const previewBtn = (RAW_EXTS.has(ev.ext) && ev.has_preview !== false)
        ? `<button class="export-preview-btn"${busyAttr()} data-extract-preview="${escHtml(ev.filepath)}">Export Preview</button>`
        : '';
      const repairBtn = (JPEG_EXTS.has(ev.ext) && ev.status === 'partial')
        ? `<button class="repair-jpeg-btn"${busyAttr()} data-repair-jpeg="${escHtml(ev.filepath)}">Repair JPG</button>`
        : '';
      const salvageBtn = (JPEG_EXTS.has(ev.ext) && ev.status === 'corrupt'
          && (ev.reason || '').includes('Missing JPEG SOI marker'))
        ? `<button class="salvage-image-btn"${busyAttr()} data-salvage-image="${escHtml(ev.filepath)}">Salvage Image</button>`
        : '';
      const row = document.createElement('div');
      row.className = 'issue-row';
      row.dataset.status = ev.status;
      row.innerHTML = `
        <div class="status-dot dot-${ev.status}"></div>
        <div class="issue-info">
          <a class="issue-filename" href="#" data-reveal="${escHtml(ev.filepath)}" title="Reveal in file manager">${escHtml(ev.filename)}</a>
          <div class="issue-reason">${escHtml(ev.reason || '')}</div>
        </div>
        <button class="copy-path-btn"${busyAttr()} data-copy="${escHtml(ev.filepath)}" title="Copy path: ${escHtml(ev.filepath)}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
        ${previewBtn}
        ${repairBtn}
        ${salvageBtn}
        <div class="issue-corrupt-pct">${pctStr}</div>
        <div class="issue-meta">${size}</div>
        <span class="status-badge badge-${ev.status}">${statusLabel(ev.status)}</span>
      `;
      body.appendChild(row);
    });

    group.style.display = visible.length > 0 ? '' : 'none';
    visibleCount += visible.length;
  });

  document.getElementById('empty-results').style.display =
    visibleCount === 0 ? 'block' : 'none';
}

// ── Folder toggle ─────────────────────────────────────────────────────────────
function toggleFolder(group) {
  group.classList.toggle('open');
  const body = group.querySelector('.folder-body');
  body.style.display = group.classList.contains('open') ? 'block' : 'none';
}

// ── Export ────────────────────────────────────────────────────────────────────
function exportData() {
  const header = ['Status', 'Filename', 'Extension', 'Directory',
                  'Full Path', 'File Size (bytes)', 'Corruption %', 'Issue'];
  const rows = [header];

  for (const fd of Object.values(folderData)) {
    for (const r of fd.issues) {
      rows.push([
        r.status      || '',
        r.filename    || '',
        r.ext         || '',
        r.dir         || '',
        r.filepath    || '',
        r.file_size   || '',
        r.corrupt_pct || '',
        r.reason      || '',
      ]);
    }
  }

  const csv = '﻿' + rows.map(row =>
    row.map(cell => '"' + String(cell).replace(/"/g, '""') + '"').join(',')
  ).join('\r\n');

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = 'photo_scan_results.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
