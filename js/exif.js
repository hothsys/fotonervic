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
  refreshExiftoolStatus();
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

// ── ⓘ bubbles with a pop-out: Exif Info's metadata notes and Blur Check's scores ──
// One shared pop-out, positioned next to the clicked bubble (a pop-out inside
// the card would be clipped by it). Opens on click or Enter/Space; closes on
// a click elsewhere, Escape, or scroll.
const METADATA_NOTE_HELP = {
  no_camera: `
    <strong>Why there are no camera details</strong>
    <p>This file doesn't record which camera or phone took it, so there is no make, model, lens, or exposure to show. Common reasons:</p>
    <ul>
      <li><b>Saved from a messaging or social app</b> (WhatsApp, Messenger, Instagram, and others): they remove camera details and location when a photo is shared, and usually shrink it.</li>
      <li><b>Downloaded</b> from a website or some cloud and photo services, which strip metadata from downloads.</li>
      <li><b>A screenshot</b> or screen recording.</li>
      <li><b>A scan</b>, or a photo of a print.</li>
      <li><b>An edited or converted copy</b> from an app that doesn't carry metadata over.</li>
      <li><b>An old camera or phone</b> that didn't record a make and model.</li>
    </ul>
    <p>Exif Info shows everything the file contains. The original photo, if you have it, may still have these details.</p>`,
  low_detail: `
    <strong>Too little detail to judge focus</strong>
    <p>Most of this photo is smooth sky, silhouette, haze, or plain surfaces. Blur Check judges focus from fine detail and edges, so a frame with very little of either can score as blurry even when it's perfectly sharp (a moon, a sunrise over a ridge, fog, a clear sky).</p>
    <p>Photos like this are tagged <b>Low detail</b> and never counted as blurry; their score is shown in grey for reference only. Check focus yourself: open the photo and click it to zoom to 100%.</p>`,
  export: `
    <strong>Why the camera details were removed</strong>
    <p>This file was exported by Lightroom or Photoshop with its camera metadata left out: only the editor's signature remains, so there is no camera, lens, capture date, exposure, or location.</p>
    <p>In Lightroom Classic's Export dialog, the <b>Metadata</b> section's <b>Include</b> setting controls this. <i>Copyright Only</i> or <i>Copyright &amp; Contact Info Only</i> remove it; <i>All Metadata</i> keeps it. Turning on <i>Remove Location Info</i> drops GPS only.</p>
    <p>Re-export with <i>All Metadata</i>, or run Exif Info on the originals.</p>`,
};

function metadataNoteHelp(bubble) {
  let html = METADATA_NOTE_HELP[bubble.dataset.noteKind] || '';
  const w = +bubble.dataset.w, h = +bubble.dataset.h;
  // Blur Check cards: built from the card's result (blurScoreHelp in js/blur.js)
  const blurResult = bubble.closest('.blur-card')?.blurResult;
  if (blurResult && bubble.dataset.noteKind === 'blur_score') html = blurScoreHelp(blurResult, true);
  if (blurResult && bubble.dataset.noteKind === 'low_detail') html += blurScoreHelp(blurResult, false);
  if (bubble.dataset.noteKind === 'no_camera' && w && h && Math.max(w, h) <= 2048) {
    html += `<p class="info-pop-detail">This copy is ${w} × ${h}, smaller than a modern camera or phone original, which points to a shared or downloaded copy.</p>`;
  }
  return html;
}

function closeInfoPop() {
  const pop = document.getElementById('info-pop');
  if (pop) pop.hidden = true;
  document.querySelectorAll('.info-bubble[aria-expanded="true"]').forEach(b => b.setAttribute('aria-expanded', 'false'));
}

function toggleInfoPop(bubble) {
  let pop = document.getElementById('info-pop');
  const wasOpenHere = pop && !pop.hidden && bubble.getAttribute('aria-expanded') === 'true';
  closeInfoPop();
  if (wasOpenHere) return;
  if (!pop) {
    pop = document.createElement('div');
    pop.id = 'info-pop';
    pop.setAttribute('role', 'dialog');
    document.body.appendChild(pop);
  }
  pop.innerHTML = metadataNoteHelp(bubble);
  pop.style.maxHeight = '';
  pop.hidden = false;
  bubble.setAttribute('aria-expanded', 'true');
  // Below the bubble if it fits, else on the roomier side, never covering the
  // bubble (it scrolls if there isn't room for all of it); kept inside the window
  const r = bubble.getBoundingClientRect(), pr = pop.getBoundingClientRect(), gap = 8;
  const roomBelow = window.innerHeight - r.bottom - 2 * gap, roomAbove = r.top - 2 * gap;
  const below = pr.height <= roomBelow || roomBelow >= roomAbove;
  const height = Math.min(pr.height, below ? roomBelow : roomAbove);
  if (height < pr.height) pop.style.maxHeight = height + 'px';
  pop.style.left = Math.min(Math.max(gap, r.left + r.width / 2 - pr.width / 2), window.innerWidth - pr.width - gap) + 'px';
  pop.style.top = (below ? r.bottom + gap : r.top - gap - height) + 'px';
}

document.addEventListener('click', e => {
  const bubble = e.target.closest('.info-bubble');
  if (bubble) { e.preventDefault(); e.stopPropagation(); toggleInfoPop(bubble); return; }
  if (!e.target.closest('#info-pop')) closeInfoPop();
});
document.addEventListener('keydown', e => {
  const bubble = e.target.closest && e.target.closest('.info-bubble');
  if (bubble && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); toggleInfoPop(bubble); }
  else if (e.key === 'Escape') closeInfoPop();
});
window.addEventListener('scroll', e => {          // the page scrolled, not the pop-out's own text
  if (!(e.target.closest && e.target.closest('#info-pop'))) closeInfoPop();
}, true);
window.addEventListener('resize', closeInfoPop);

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
  // Skip the make when the model already names the brand ("Canon EOS R5", "NIKON D810")
  const brand    = (ev.make || '').split(' ')[0].toLowerCase();
  const camera   = (brand && ev.model && ev.model.toLowerCase().startsWith(brand))
    ? ev.model : [ev.make, ev.model].filter(Boolean).join(' ') || null;
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
      ${ev.lens  ? `<div class="exif-card-lens" title="${escHtml(ev.lens)}">${escHtml(ev.lens)}</div>` : ''}
      ${ev.date  ? `<div class="exif-card-date"><span class="exif-card-label">Capture Time</span> ${escHtml(ev.date)}</div>` : ''}
      ${settings ? `<div class="exif-card-settings">${escHtml(settings)}</div>` : ''}
      ${dims     ? `<div class="exif-card-dims">${escHtml(dims)}</div>` : ''}
      <div class="exif-card-size">${formatSize(ev.file_size || 0)}</div>
      ${(ev.gps_lat != null && ev.gps_lng != null) ? `<a class="exif-card-gps" href="https://maps.google.com/?q=${ev.gps_lat},${ev.gps_lng}" target="_blank" rel="noopener">◎ ${ev.gps_lat.toFixed(4)}, ${ev.gps_lng.toFixed(4)}</a>` : ''}
      ${ev.metadata_note
        ? `<div class="exif-card-note ${ev.metadata_note_kind === 'export' ? 'note-export' : ''}">${escHtml(ev.metadata_note)}`
          + ` <span class="info-bubble" role="button" tabindex="0" aria-label="Why?" aria-expanded="false" aria-controls="info-pop"`
          + ` data-note-kind="${escHtml(ev.metadata_note_kind || '')}" data-w="${ev.width || ''}" data-h="${ev.height || ''}">i</span></div>`
        : '<div class="exif-card-no-exif">No EXIF</div>'}
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
  refreshExiftoolStatus();   // re-enable its buttons
}

function exportExifData() {
  const header = ['Filename','Directory','Extension','File Size (bytes)',
                  'Camera Make','Camera Model','Lens','Date',
                  'ISO','Aperture','Shutter','Focal Length','Width','Height','GPS Lat','GPS Lng','Has EXIF','Metadata Note',
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
        r.metadata_note || '',
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

// ── ExifTool status / download ──
// Exif Info reads metadata with the app's own ExifTool, which the server
// downloads at launch when it's missing or too old. This box appears only when
// something needs attention: a download in progress or failed, an update, or
// metadata limited to the built-in reader.
let exiftoolPollTimer = null;

async function refreshExiftoolStatus() {
  let st;
  try { st = await (await fetch('/api/exiftool')).json(); } catch(e) { return; }
  const el = document.getElementById('exif-meta-status');
  const dl = st.download || {};
  const link = '<a href="https://exiftool.org" target="_blank" rel="noopener">ExifTool</a>';
  el.className = 'blur-model-status';
  el.hidden = false;
  clearTimeout(exiftoolPollTimer);
  // Without the app's copy, an ExifTool installed some other way stands in
  const fallback = when => st.available ? ` Using the ExifTool installed on this Mac ${when}.`
                                        : ` ${when === 'until then' ? 'Until then' : 'For now'}, Exif Info uses its basic built-in reader.`;

  if (dl.state === 'downloading' || dl.state === 'verifying') {
    el.textContent = (dl.state === 'verifying' ? 'Verifying ExifTool\u2026' : 'Downloading ExifTool from exiftool.org\u2026') + fallback('until then');
    exiftoolPollTimer = setTimeout(refreshExiftoolStatus, 1000);
  } else if (!st.wrapper_installed) {
    el.textContent = 'Exif Info is using its basic built-in reader: the PyExifTool package didn\u2019t install. Restart the app to retry.';
  } else if (dl.state === 'error') {
    el.classList.add('error');
    el.innerHTML = `<span title="${escHtml(dl.detail || '')}"><strong>ExifTool download failed.</strong> ${escHtml(dl.error || 'Unknown error.')}${escHtml(fallback('for now'))}</span>`
      + ' <button class="btn-outline" onclick="downloadExiftool()">Try again</button>';
  } else if (!st.available) {
    el.innerHTML = `<span>Exif Info is using its basic built-in reader, which misses RAW metadata and lens names. ${link} adds them.</span>`
      + (st.can_download ? ' <button class="btn-outline" onclick="downloadExiftool()">Download ExifTool</button>'
                         : ' <span>Downloading it needs Perl and curl.</span>');
  } else if (st.update_available) {
    el.innerHTML = `<span>${link} ${escHtml(st.latest)} is available (this app uses ${escHtml(st.version || '')}).</span>`
      + ' <button class="btn-outline" onclick="downloadExiftool()">Update</button>';
  } else {
    el.hidden = true;   // nothing needs attention
    el.innerHTML = '';
  }
  el.querySelectorAll('button').forEach(b => { b.disabled = busyMode !== null; });
}

async function downloadExiftool() {
  try { await fetch('/api/exiftool/download', { method: 'POST' }); } catch(e) {}
  refreshExiftoolStatus();
}
