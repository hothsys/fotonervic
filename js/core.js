// Shared constants and helpers, the busy lock, thumbnail URLs, and the settings menu.

const RAW_EXTS = new Set(['.nef','.nrw','.arw','.srf','.sr2','.cr2','.cr3',
                          '.dng','.raf','.rw2','.orf','.pef','.srw']);
const JPEG_EXTS = new Set(['.jpg','.jpeg','.jpe','.jfif']);

// ── Library check ────────────────────────────────────────────────────────────
async function checkLibs() {
  try {
    const r = await fetch('/api/libs');
    const d = await r.json();
    const el = document.getElementById('lib-status');
    if (d.pillow && d.rawpy && d.pillow_heif) {
      el.textContent = '\u2713 all libraries ready';
      el.style.color = 'var(--green)';
    } else {
      const missing = [];
      if (!d.pillow)      missing.push('Pillow');
      if (!d.rawpy)       missing.push('rawpy');
      if (!d.pillow_heif) missing.push('pillow-heif');
      el.textContent = '\u26a0 missing: ' + missing.join(', ');
      el.style.color = 'var(--amber)';
    }
  } catch(e) {
    document.getElementById('lib-status').textContent = 'library check failed';
  }
}

// ── Reveal file/folder in OS file manager ───────────────────────────────────
function revealFile(path) {
  fetch('/api/reveal', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: path})
  });
}

// Scan results and EXIF results share the page; starting one hides the other's
// output so stale panes (e.g. "No results") don't linger above the new results.
function hideScanResults() {
  ['summary-bar', 'export-bar', 'results-section', 'empty-results']
    .forEach(id => { document.getElementById(id).style.display = 'none'; });
}

function hideExifResults() {
  document.getElementById('exif-section').style.display = 'none';
}

function hideBlurResults() {
  document.getElementById('blur-section').style.display = 'none';
}

// ── Busy lock ────────────────────────────────────────────────────────────────
// While a scan or EXIF scan runs, every button except Cancel is disabled (plus
// the path input and previous-scans dropdown), so nothing can start overlapping
// work or change the directory/results out from under the running scan.
let busyMode = null;  // null | 'scan' | 'exif' | 'blur'

const LOCKED_CONTROLS = '#scan-btn, #browse-btn, #exif-btn, #blur-btn, #dir-input, '
  + '#prev-scans-select, #clear-scans-btn, button:not(.btn-danger)';

function setBusy(mode) {
  busyMode = mode;
  document.querySelectorAll(LOCKED_CONTROLS)
    .forEach(el => { el.disabled = mode !== null; });
  // One Cancel (in the sticky scan bar) stops whichever scan is running
  document.getElementById('cancel-btn').disabled = mode === null;
}

// For result-row buttons rendered while a scan is still running
function busyAttr() {
  return busyMode ? ' disabled' : '';
}

function cancelActive() {
  if (busyMode === 'exif') cancelExifScan();
  else if (busyMode === 'blur') cancelBlurScan();
  else cancelScan();
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatSize(bytes) {
  if (bytes === 0)    return '0 B';
  if (bytes < 1024)   return bytes + ' B';
  if (bytes < 1048576) return (bytes/1024).toFixed(1) + ' KB';
  return (bytes/1048576).toFixed(1) + ' MB';
}

function formatEta(sec) {
  if (sec < 60)  return sec + 's';
  if (sec < 3600) return Math.floor(sec/60) + 'm ' + (sec%60) + 's';
  return Math.floor(sec/3600) + 'h ' + Math.floor((sec%3600)/60) + 'm';
}

function statusLabel(s) {
  return { exif_only:'EXIF Only', partial:'Partial', corrupt:'Corrupt',
           empty:'Empty', error:'Error', unsupported:'Unsupported' }[s] || s;
}

// ── Integrity (shared by Exif Info and Blur Check) ──
// Results carry integrity / integrity_reason from check_integrity() in backend/integrity.
// 'unsupported' means it couldn't be checked, not that it's damaged.
function isDamaged(r) {
  return !!r.integrity && r.integrity !== 'ok' && r.integrity !== 'unsupported';
}

function integrityTagHtml(r) {
  return isDamaged(r)
    ? `<span class="integrity-tag" title="${escHtml(r.integrity_reason || '')}">Damaged: ${escHtml(statusLabel(r.integrity))}</span>`
    : '';
}

function integrityCsvCells(r) {
  return [r.integrity === 'ok' ? 'OK' : (r.integrity ? statusLabel(r.integrity) : ''), r.integrity_reason || ''];
}

function escHtml(s) {
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Thumbnail URLs + Clear Cache ─────────────────────────────────────────────
// Thumbnails are browser-cached for a day, so their URL carries a version:
//   THUMB_FORMAT_VERSION  bump when thumbnail output changes
//                         (2: EXIF Orientation; 3: HEIC orientation)
//   thumbCacheToken       changed by Clear Cache, for browsers that ignore the
//                         server's Clear-Site-Data header
const THUMB_FORMAT_VERSION = 3;
let thumbCacheToken = '';
try { thumbCacheToken = localStorage.getItem('thumbCacheToken') || ''; } catch(e) {}

function thumbnailUrl(path) {
  const v = THUMB_FORMAT_VERSION + (thumbCacheToken ? '.' + thumbCacheToken : '');
  return '/api/thumbnail?v=' + v + '&path=' + encodeURIComponent(path);
}

// ── Sticky scan bar: style it as a floating bar once it's pinned ──
new IntersectionObserver(([entry]) => {
  const pinned = !entry.isIntersecting && entry.boundingClientRect.top < 0;
  document.getElementById('scan-bar').classList.toggle('stuck', pinned);
}).observe(document.getElementById('scan-bar-sentinel'));

// ── Settings menu (cogwheel) ──
function toggleSettingsMenu(force) {
  const menu = document.getElementById('settings-dropdown');
  const open = force !== undefined ? force : menu.hidden;
  menu.hidden = !open;
  document.getElementById('settings-btn').setAttribute('aria-expanded', String(open));
}
document.addEventListener('click', e => {
  if (!e.target.closest('.settings-menu')) toggleSettingsMenu(false);
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') toggleSettingsMenu(false);
});

// Clears the browser's HTTP cache and the server's thumbnail cache. Saved
// scans (IndexedDB) and the remembered directory (localStorage) are kept.
async function clearCache() {
  const btn = document.getElementById('clear-cache-btn');
  btn.disabled = true;
  btn.textContent = 'Clearing\u2026';
  try {
    const r = await fetch('/api/clear-cache', { method: 'POST' });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    thumbCacheToken = String(Date.now());
    try { localStorage.setItem('thumbCacheToken', thumbCacheToken); } catch(e) {}
    // Re-fetch thumbnails already on screen; lazy ones pick up the new URL later
    document.querySelectorAll('img.exif-card-img[data-path]').forEach(img => {
      const url = thumbnailUrl(img.dataset.path);
      if (img.dataset.src) img.dataset.src = url;
      else img.src = url;
    });
    btn.textContent = 'Cache cleared';
  } catch(e) {
    btn.textContent = 'Clear failed';
  }
  setTimeout(() => {
    btn.textContent = 'Clear Cache';
    btn.disabled = busyMode !== null;  // stay locked if a scan started meanwhile
    toggleSettingsMenu(false);
  }, 1500);
}
