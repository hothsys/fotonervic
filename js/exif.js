// Exif Info: SSE streaming, cards with lazy-loaded thumbnails, CSV export.

// ── EXIF thumbnail lazy loader ────────────────────────────────────────────────
const _thumbObserver = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (!entry.isIntersecting) return;
    const img = entry.target;
    const src = img.dataset.src;
    if (!src) return;
    img.src = src;
    img.removeAttribute('data-src');
    _thumbObserver.unobserve(img);
  });
}, { rootMargin: '300px' });  // start loading 300px before entering viewport

// ── EXIF scan ─────────────────────────────────────────────────────────────────
let exifEventSource = null;
let exifDamagedTotal = 0;
const exifData = {};       // { dir: { files: [], count: 0 } }
const exifGrids = new Map();  // dir → { grid: Element, badge: Element }

function startExifScan() {
  stopDirCount();
  const dir = document.getElementById('dir-input').value.trim();
  if (!dir) { alert('Please enter a directory path.'); return; }
  rememberScanDir(dir);

  Object.keys(exifData).forEach(k => delete exifData[k]);
  exifGrids.clear();
  document.getElementById('exif-folder-list').innerHTML = '';
  hideExifResults();
  hideScanResults();
  hideBlurResults();
  document.getElementById('exif-summary-label').textContent = '';
  exifDamagedTotal = 0;

  setBusy('exif');
  document.getElementById('progress-section').style.display = 'block';
  document.getElementById('p-bar').style.width     = '0%';
  document.getElementById('p-scanned').textContent = '0';
  document.getElementById('p-total').textContent   = '?';
  document.getElementById('p-issues').textContent  = '0';
  document.getElementById('p-eta').textContent     = '';
  document.getElementById('p-current').textContent = 'Reading EXIF…';
  document.getElementById('p-current').classList.add('scanning-pulse');

  if (exifEventSource) exifEventSource.close();
  exifEventSource = new EventSource('/api/exif-scan?dir=' + encodeURIComponent(dir));
  exifEventSource.onmessage = e => handleExifEvent(JSON.parse(e.data));
  exifEventSource.onerror   = () => exifDone();
}

function handleExifEvent(ev) {
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
    case 'exif_result':
      addExifCard(ev);
      break;
    case 'error':
      alert('EXIF scan error: ' + ev.message);
      exifDone();
      break;
    case 'cancelled':
    case 'complete': {
      const label = ev.type === 'complete'
        ? `✓ Done: ${(ev.scanned||0).toLocaleString()} files in ${ev.elapsed}s`
        : `Cancelled after ${(ev.scanned||0).toLocaleString()} files`;
      document.getElementById('p-current').textContent = label;
      document.getElementById('p-current').classList.remove('scanning-pulse');
      document.getElementById('p-bar').style.width = '100%';
      const total = Object.values(exifData).reduce((s, d) => s + d.count, 0);
      document.getElementById('exif-summary-label').textContent =
        total.toLocaleString() + ' file' + (total !== 1 ? 's' : '')
        + (exifDamagedTotal ? ` \u00b7 ${exifDamagedTotal.toLocaleString()} damaged` : '');
      exifDone();
      break;
    }
  }
}

function addExifCard(ev) {
  upsertExifFolderGroup(ev.dir);
  if (!exifData[ev.dir]) exifData[ev.dir] = { files: [], count: 0 };
  exifData[ev.dir].files.push(ev);
  exifData[ev.dir].count++;

  const refs = exifGrids.get(ev.dir);
  const grid = refs && refs.grid;
  if (!grid) return;

  const hasExif  = ev.has_exif;
  const isVideo  = ['.mp4','.m4v','.mov','.avi','.mpg','.mpeg'].includes(ev.ext);
  const camera   = [ev.make, ev.model].filter(Boolean).join(' ') || null;
  const settings = [ev.aperture, ev.shutter, ev.iso ? 'ISO ' + ev.iso : null, ev.focal_length]
    .filter(Boolean).join(' · ');
  const dims     = (ev.width && ev.height) ? ev.width + ' × ' + ev.height : null;
  const thumbUrl = thumbnailUrl(ev.filepath);

  const damaged = isDamaged(ev);
  if (damaged) { exifData[ev.dir].damaged = (exifData[ev.dir].damaged || 0) + 1; exifDamagedTotal++; }
  const card = document.createElement('div');
  card.className = 'exif-card' + (hasExif ? '' : ' no-exif') + (damaged ? ' is-damaged' : '');
  card.title = ev.filepath;

  const thumbHtml = isVideo
    ? `<div class="exif-card-thumb exif-card-thumb-video" data-reveal="${escHtml(ev.filepath)}" title="Reveal in file manager"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><polygon points="5 3 19 12 5 21 5 3"/></svg><span class="exif-card-vidext">${escHtml(ev.ext.replace('.','').toUpperCase())}</span></div>`
    : `<div class="exif-card-thumb" data-lightbox="${escHtml(ev.filepath)}" title="Preview"><img class="exif-card-img" data-path="${escHtml(ev.filepath)}" data-src="${escHtml(thumbUrl)}" alt="" onerror="this.parentElement.classList.add('exif-thumb-error')"></div>`;

  card.innerHTML = `
    ${thumbHtml}
    <div class="exif-card-meta">
      <a class="exif-card-filename card-filename-link" href="#" data-reveal="${escHtml(ev.filepath)}" title="Reveal in file manager">${escHtml(ev.filename)}</a>
      ${camera   ? `<div class="exif-card-camera">${escHtml(camera)}</div>` : ''}
      ${ev.date  ? `<div class="exif-card-date"><span class="exif-card-label">Capture Time</span> ${escHtml(ev.date)}</div>` : ''}
      ${settings ? `<div class="exif-card-settings">${escHtml(settings)}</div>` : ''}
      ${dims     ? `<div class="exif-card-dims">${escHtml(dims)}</div>` : ''}
      <div class="exif-card-size">${formatSize(ev.file_size || 0)}</div>
      ${(ev.gps_lat != null && ev.gps_lng != null) ? `<a class="exif-card-gps" href="https://maps.google.com/?q=${ev.gps_lat},${ev.gps_lng}" target="_blank" rel="noopener">◎ ${ev.gps_lat.toFixed(4)}, ${ev.gps_lng.toFixed(4)}</a>` : ''}
      <div class="exif-card-no-exif">No EXIF</div>
      ${damaged ? `<div class="card-tags">${integrityTagHtml(ev)}</div>` : ''}
    </div>
  `;

  const img = card.querySelector('.exif-card-img');
  if (img) _thumbObserver.observe(img);

  grid.appendChild(card);

  // Update folder file count
  const badge = refs && refs.badge;
  if (badge) {
    const d = exifData[ev.dir];
    badge.textContent = d.count + ' file' + (d.count !== 1 ? 's' : '') + (d.damaged ? `, ${d.damaged} damaged` : '');
  }
}

function upsertExifFolderGroup(dir) {
  if (exifGrids.has(dir)) return;

  document.getElementById('exif-section').style.display = 'block';

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
    <span class="folder-path-link" title="Copy path" data-copy="${escHtml(dir)}">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
    </span>
    <div class="folder-counts"></div>
  `;

  const badge = document.createElement('span');
  badge.className = 'fc fc-total';
  badge.textContent = '0 files';
  header.querySelector('.folder-counts').appendChild(badge);

  const body = document.createElement('div');
  body.className = 'folder-body';
  body.style.display = 'block';

  const grid = document.createElement('div');
  grid.className = 'exif-grid';
  body.appendChild(grid);

  group.appendChild(header);
  group.appendChild(body);
  document.getElementById('exif-folder-list').appendChild(group);

  exifGrids.set(dir, { grid, badge });
}

// Same as cancelScan(): wait for the server's 'cancelled' event.
function cancelExifScan() {
  document.getElementById('cancel-btn').disabled = true;
  document.getElementById('p-current').textContent = 'Cancelling\u2026';
  fetch('/api/exif-cancel', { method: 'POST' }).catch(() => exifDone());
}

function exifDone() {
  if (exifEventSource) { exifEventSource.close(); exifEventSource = null; }
  setBusy(null);
}

function exportExifData() {
  const header = ['Filename','Directory','Extension','File Size (bytes)',
                  'Camera Make','Camera Model','Lens','Date',
                  'ISO','Aperture','Shutter','Focal Length','Width','Height','GPS Lat','GPS Lng','Has EXIF',
                  'Integrity','Integrity Issue'];
  const rows = [header];
  for (const fd of Object.values(exifData)) {
    for (const r of fd.files) {
      rows.push([
        r.filename    || '',
        r.dir         || '',
        r.ext         || '',
        r.file_size   || '',
        r.make        || '',
        r.model       || '',
        r.lens        || '',
        r.date        || '',
        r.iso         || '',
        r.aperture    || '',
        r.shutter     || '',
        r.focal_length|| '',
        r.width       || '',
        r.height      || '',
        r.gps_lat != null ? r.gps_lat : '',
        r.gps_lng != null ? r.gps_lng : '',
        r.has_exif ? 'Yes' : 'No',
        ...integrityCsvCells(r),
      ]);
    }
  }
  const csv  = '﻿' + rows.map(row =>
    row.map(cell => '"' + String(cell).replace(/"/g, '""') + '"').join(',')
  ).join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = 'exif_info.csv';
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
