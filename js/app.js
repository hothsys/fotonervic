let eventSource = null;
let currentFilter = 'all';

const RAW_EXTS = new Set(['.nef','.nrw','.arw','.srf','.sr2','.cr2','.cr3',
                          '.dng','.raf','.rw2','.orf','.pef','.srw']);
const JPEG_EXTS = new Set(['.jpg','.jpeg','.jpe','.jfif']);

// { folderPath: { issues: [], total: 0 } }
const folderData = {};

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

// ── Browse directory modal ───────────────────────────────────────────────────
let browseCurrentPath = '';

function openBrowse() {
  var overlay = document.getElementById('browse-overlay');
  var list = document.getElementById('browse-list');
  var bc = document.getElementById('browse-breadcrumb');
  list.innerHTML = '<div class="browse-empty">Loading\u2026</div>';
  bc.innerHTML = '';
  overlay.classList.add('open');
  var input = document.getElementById('dir-input').value.trim();
  browseTo(input || '');
}

function closeBrowse() {
  document.getElementById('browse-overlay').classList.remove('open');
}

function selectBrowseDir() {
  document.getElementById('dir-input').value = browseCurrentPath;
  closeBrowse();
}

function renderBrowseData(d) {
  var list = document.getElementById('browse-list');
  var bc = document.getElementById('browse-breadcrumb');
  browseCurrentPath = d.current;

  // Build breadcrumb
  bc.innerHTML = '';
  var rootCrumb = document.createElement('span');
  rootCrumb.className = 'browse-crumb';
  rootCrumb.textContent = '/';
  rootCrumb.setAttribute('data-path', '/');
  bc.appendChild(rootCrumb);

  var parts = d.current.split('/').filter(Boolean);
  var accumulated = '';
  for (var i = 0; i < parts.length; i++) {
    accumulated += '/' + parts[i];
    var sep = document.createElement('span');
    sep.className = 'browse-sep';
    sep.textContent = '/';
    bc.appendChild(sep);

    var crumb = document.createElement('span');
    crumb.className = 'browse-crumb' + (i === parts.length - 1 ? ' current' : '');
    crumb.textContent = parts[i];
    if (i < parts.length - 1) {
      crumb.setAttribute('data-path', accumulated);
    }
    bc.appendChild(crumb);
  }

  // Build directory list
  list.innerHTML = '';
  if (d.parent) {
    var up = document.createElement('div');
    up.className = 'browse-item';
    up.setAttribute('data-path', d.parent);
    up.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M15 18l-6-6 6-6"/></svg><span style="color:var(--text2)">..</span>';
    list.appendChild(up);
  }
  if (d.dirs.length === 0 && !d.parent) {
    var empty = document.createElement('div');
    empty.className = 'browse-empty';
    empty.textContent = 'No subdirectories found';
    list.appendChild(empty);
  }
  for (var j = 0; j < d.dirs.length; j++) {
    var item = document.createElement('div');
    item.className = 'browse-item';
    item.setAttribute('data-path', d.current + '/' + d.dirs[j]);
    var icon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/></svg>';
    item.innerHTML = icon + '<span>' + escHtml(d.dirs[j]) + '</span>';
    list.appendChild(item);
  }
}

function fetchBrowse(url, retriesLeft) {
  var list = document.getElementById('browse-list');
  var xhr = new XMLHttpRequest();
  xhr.open('GET', url, true);
  xhr.onload = function() {
    if (xhr.status !== 200) {
      list.innerHTML = '<div class="browse-empty" style="color:var(--red)">Server error (' + xhr.status + ')</div>';
      return;
    }
    try {
      renderBrowseData(JSON.parse(xhr.responseText));
    } catch(e) {
      list.innerHTML = '<div class="browse-empty" style="color:var(--red)">Invalid response from server</div>';
    }
  };
  xhr.onerror = function() {
    if (retriesLeft > 0) {
      list.innerHTML = '<div class="browse-empty">Retrying\u2026</div>';
      setTimeout(function() { fetchBrowse(url, retriesLeft - 1); }, 500);
    } else {
      list.innerHTML = '<div class="browse-empty" style="color:var(--red)">Cannot connect to server \u2014 try closing and re-opening the browser</div>';
    }
  };
  xhr.send();
}

function browseTo(path) {
  fetchBrowse('/api/browse?path=' + encodeURIComponent(path), 2);
}

// Event delegation for browse and reveal clicks (avoids inline onclick quoting issues)
document.addEventListener('click', function(e) {
  // Browse directory navigation
  var browseTarget = e.target.closest('[data-path]');
  if (browseTarget && (browseTarget.closest('#browse-breadcrumb') || browseTarget.closest('#browse-list'))) {
    e.preventDefault();
    browseTo(browseTarget.getAttribute('data-path'));
    return;
  }
  // Copy file path to clipboard
  var copyTarget = e.target.closest('[data-copy]');
  if (copyTarget) {
    e.preventDefault();
    e.stopPropagation();
    var text = copyTarget.getAttribute('data-copy');
    navigator.clipboard.writeText(text).then(function() {
      copyTarget.style.color = 'var(--green)';
      copyTarget.style.borderColor = 'var(--green)';
      setTimeout(function() {
        copyTarget.style.color = '';
        copyTarget.style.borderColor = '';
      }, 1500);
    });
    return;
  }
  // Export embedded preview from RAW file
  var extractTarget = e.target.closest('[data-extract-preview]');
  if (extractTarget) {
    e.preventDefault();
    e.stopPropagation();
    extractPreview(extractTarget);
    return;
  }
  // Repair truncated JPEG
  var repairTarget = e.target.closest('[data-repair-jpeg]');
  if (repairTarget) {
    e.preventDefault();
    e.stopPropagation();
    repairJpeg(repairTarget);
    return;
  }
  // Salvage corrupt JPEG (donor-table grafting)
  var salvageTarget = e.target.closest('[data-salvage-image]');
  if (salvageTarget) {
    e.preventDefault();
    e.stopPropagation();
    salvageImage(salvageTarget);
    return;
  }
  // Reveal file/folder in OS file manager
  var revealTarget = e.target.closest('[data-reveal]');
  if (revealTarget) {
    e.preventDefault();
    e.stopPropagation();
    revealFile(revealTarget.getAttribute('data-reveal'));
  }
});

// ── Reveal file/folder in OS file manager ───────────────────────────────────
function revealFile(path) {
  fetch('/api/reveal', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({path: path})
  });
}

// ── Extract embedded preview from RAW file ──────────────────────────────────
function extractPreview(btn) {
  var filepath = btn.getAttribute('data-extract-preview');
  btn.textContent = 'Exporting\u2026';
  btn.disabled = true;

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/extract-preview');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.responseType = 'blob';

  xhr.onload = function() {
    if (xhr.status === 200) {
      var filename = xhr.getResponseHeader('X-Filename') || 'preview.jpg';
      var url = URL.createObjectURL(xhr.response);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      btn.textContent = 'Exported!';
      btn.style.color = 'var(--green)';
      btn.style.borderColor = 'var(--green)';
      setTimeout(function() {
        btn.textContent = 'Export Preview';
        btn.style.color = '';
        btn.style.borderColor = '';
        btn.disabled = false;
      }, 1500);
    } else {
      btn.textContent = 'No Preview';
      btn.style.color = 'var(--red)';
      btn.style.borderColor = 'rgba(224,82,82,.35)';
      setTimeout(function() {
        btn.textContent = 'Export Preview';
        btn.style.color = '';
        btn.style.borderColor = '';
        btn.disabled = false;
      }, 1500);
    }
  };

  xhr.onerror = function() {
    btn.textContent = 'Failed';
    btn.style.color = 'var(--red)';
    setTimeout(function() {
      btn.textContent = 'Export Preview';
      btn.style.color = '';
      btn.style.borderColor = '';
      btn.disabled = false;
    }, 1500);
  };

  xhr.send(JSON.stringify({filepath: filepath}));
}

// ── Repair JPEG ─────────────────────────────────────────────────────────────
function repairJpeg(btn) {
  var filepath = btn.getAttribute('data-repair-jpeg');
  btn.textContent = 'Repairing\u2026';
  btn.disabled = true;

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/repair-jpeg');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.responseType = 'blob';

  xhr.onload = function() {
    if (xhr.status === 200) {
      var filename = xhr.getResponseHeader('X-Filename') || 'repaired.jpg';
      var url = URL.createObjectURL(xhr.response);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      btn.textContent = 'Repaired!';
      btn.style.color = 'var(--green)';
      btn.style.borderColor = 'var(--green)';
      setTimeout(function() {
        btn.textContent = 'Repair JPG';
        btn.style.color = '';
        btn.style.borderColor = '';
        btn.disabled = false;
      }, 1500);
    } else {
      xhr.response.text().then(function(text) {
        try { var msg = JSON.parse(text).error; } catch(e) { var msg = 'Repair failed'; }
        btn.textContent = msg.length > 30 ? 'Repair Failed' : msg;
        btn.style.color = 'var(--red)';
        btn.style.borderColor = 'rgba(224,82,82,.35)';
        setTimeout(function() {
          btn.textContent = 'Repair JPG';
          btn.style.color = '';
          btn.style.borderColor = '';
          btn.disabled = false;
        }, 2500);
      });
    }
  };

  xhr.onerror = function() {
    btn.textContent = 'Failed';
    btn.style.color = 'var(--red)';
    setTimeout(function() {
      btn.textContent = 'Repair JPG';
      btn.style.color = '';
      btn.style.borderColor = '';
      btn.disabled = false;
    }, 1500);
  };

  xhr.send(JSON.stringify({filepath: filepath}));
}

// ── Salvage corrupt JPEG (donor-table grafting + MCU remap) ─────────────────
function salvageImage(btn) {
  var filepath = btn.getAttribute('data-salvage-image');
  btn.textContent = 'Salvaging\u2026';
  btn.disabled = true;

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/salvage-image');
  xhr.setRequestHeader('Content-Type', 'application/json');
  xhr.responseType = 'blob';

  xhr.onload = function() {
    if (xhr.status === 200) {
      var filename = xhr.getResponseHeader('X-Filename') || 'salvaged.jpg';
      var url = URL.createObjectURL(xhr.response);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      btn.textContent = 'Salvaged!';
      btn.style.color = '#e6b43c';
      btn.style.borderColor = '#e6b43c';
      setTimeout(function() {
        btn.textContent = 'Salvage Image';
        btn.style.color = '';
        btn.style.borderColor = '';
        btn.disabled = false;
      }, 1500);
    } else {
      xhr.response.text().then(function(text) {
        try { var msg = JSON.parse(text).error; } catch(e) { var msg = 'Salvage failed'; }
        btn.textContent = msg.length > 30 ? 'Salvage Failed' : msg;
        btn.style.color = 'var(--red)';
        btn.style.borderColor = 'rgba(224,82,82,.35)';
        setTimeout(function() {
          btn.textContent = 'Salvage Image';
          btn.style.color = '';
          btn.style.borderColor = '';
          btn.disabled = false;
        }, 2500);
      });
    }
  };

  xhr.onerror = function() {
    btn.textContent = 'Failed';
    btn.style.color = 'var(--red)';
    setTimeout(function() {
      btn.textContent = 'Salvage Image';
      btn.style.color = '';
      btn.style.borderColor = '';
      btn.disabled = false;
    }, 1500);
  };

  xhr.send(JSON.stringify({filepath: filepath}));
}

// ── Scan ─────────────────────────────────────────────────────────────────────
function startScan() {
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
  document.getElementById('summary-bar').style.display = 'none';
  document.getElementById('export-bar').style.display  = 'none';
  document.getElementById('results-section').style.display = 'none';
  document.getElementById('empty-results').style.display   = 'none';

  document.getElementById('scan-btn').disabled   = true;
  document.getElementById('cancel-btn').disabled = false;
  document.getElementById('progress-section').style.display = 'block';
  document.getElementById('p-bar').style.width   = '0%';
  document.getElementById('p-scanned').textContent = '0';
  document.getElementById('p-total').textContent   = '?';
  document.getElementById('p-issues').textContent  = '0';
  document.getElementById('p-eta').textContent      = '';
  document.getElementById('p-current').textContent  = 'Starting\u2026';

  try { localStorage.setItem('lastScanDir', dir); } catch(e) {}

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
          ? `\u2713 Done \u2014 scanned ${(ev.scanned||0).toLocaleString()} files in ${ev.elapsed}s`
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
  const previewBtn = RAW_EXTS.has(ev.ext)
    ? `<button class="export-preview-btn" data-extract-preview="${escHtml(ev.filepath)}">Export Preview</button>`
    : '';
  const repairBtn = (JPEG_EXTS.has(ev.ext) && ev.status === 'partial')
    ? `<button class="repair-jpeg-btn" data-repair-jpeg="${escHtml(ev.filepath)}">Repair JPG</button>`
    : '';
  const salvageBtn = (JPEG_EXTS.has(ev.ext) && ev.status === 'corrupt'
      && (ev.reason || '').includes('Missing JPEG SOI marker'))
    ? `<button class="salvage-image-btn" data-salvage-image="${escHtml(ev.filepath)}">Salvage Image</button>`
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
    <button class="copy-path-btn" data-copy="${escHtml(ev.filepath)}" title="Copy path: ${escHtml(ev.filepath)}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
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
  document.getElementById('scan-btn').disabled   = false;
  document.getElementById('cancel-btn').disabled = true;
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

function cancelScan() {
  fetch('/api/cancel', { method: 'POST' });
  if (eventSource) { eventSource.close(); eventSource = null; }
  document.getElementById('scan-btn').disabled   = false;
  document.getElementById('cancel-btn').disabled = true;
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
      const previewBtn = RAW_EXTS.has(ev.ext)
        ? `<button class="export-preview-btn" data-extract-preview="${escHtml(ev.filepath)}">Export Preview</button>`
        : '';
      const repairBtn = (JPEG_EXTS.has(ev.ext) && ev.status === 'partial')
        ? `<button class="repair-jpeg-btn" data-repair-jpeg="${escHtml(ev.filepath)}">Repair JPG</button>`
        : '';
      const salvageBtn = (JPEG_EXTS.has(ev.ext) && ev.status === 'corrupt'
          && (ev.reason || '').includes('Missing JPEG SOI marker'))
        ? `<button class="salvage-image-btn" data-salvage-image="${escHtml(ev.filepath)}">Salvage Image</button>`
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
        <button class="copy-path-btn" data-copy="${escHtml(ev.filepath)}" title="Copy path: ${escHtml(ev.filepath)}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg></button>
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

function escHtml(s) {
  return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Session persistence (IndexedDB) ──────────────────────────────────────────
const DB_NAME  = 'fotonervic';
const DB_STORE = 'scan';
const MAX_SCANS = 10;

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 2);
    req.onupgradeneeded = e => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains(DB_STORE)) {
        db.createObjectStore(DB_STORE);
      } else if (e.oldVersion < 2) {
        // Clear old data stored under string key 'last'; new schema uses numeric ts keys
        e.target.transaction.objectStore(DB_STORE).clear();
      }
    };
    req.onsuccess = e => resolve(e.target.result);
    req.onerror   = e => reject(e.target.error);
  });
}

function idbReq(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = e => resolve(e.target.result);
    req.onerror   = e => reject(e.target.error);
  });
}

async function saveScan() {
  try {
    const db  = await openDB();
    const ts  = Date.now();
    const dir = document.getElementById('dir-input').value.trim();

    const scanned = parseInt(document.getElementById('s-scanned').textContent.replace(/,/g, '')) || 0;

    const tx1 = db.transaction(DB_STORE, 'readwrite');
    await idbReq(tx1.objectStore(DB_STORE).put({ ts, dir, folderData, scanned }, ts));

    // Prune oldest beyond MAX_SCANS
    const tx2   = db.transaction(DB_STORE, 'readwrite');
    const store = tx2.objectStore(DB_STORE);
    const keys  = (await idbReq(store.getAllKeys())).sort((a,b) => a - b);
    while (keys.length > MAX_SCANS) store.delete(keys.shift());

    const scans = await loadSavedScans();
    populateScanDropdown(scans, ts);
  } catch(e) {}
}

async function loadSavedScans() {
  try {
    const db  = await openDB();
    const all = await idbReq(db.transaction(DB_STORE, 'readonly').objectStore(DB_STORE).getAll());
    return all.sort((a,b) => b.ts - a.ts);
  } catch(e) { return []; }
}

async function loadScan(ts) {
  try {
    const db = await openDB();
    return await idbReq(db.transaction(DB_STORE, 'readonly').objectStore(DB_STORE).get(ts));
  } catch(e) { return null; }
}

async function clearAllScans() {
  try {
    const db = await openDB();
    await idbReq(db.transaction(DB_STORE, 'readwrite').objectStore(DB_STORE).clear());
  } catch(e) {}
  document.getElementById('prev-scans-row').style.display = 'none';
  Object.keys(folderData).forEach(k => delete folderData[k]);
  document.getElementById('folder-list').innerHTML = '';
  document.getElementById('summary-bar').style.display    = 'none';
  document.getElementById('export-bar').style.display     = 'none';
  document.getElementById('results-section').style.display = 'none';
  document.getElementById('empty-results').style.display   = 'none';
}

async function loadSelectedScan(sel) {
  const ts = parseInt(sel.value);
  if (!ts) return;
  const saved = await loadScan(ts);
  if (!saved) {
    alert('Could not load this scan — it may have been cleared. Try rescanning.');
    return;
  }
  Object.keys(folderData).forEach(k => delete folderData[k]);
  document.getElementById('folder-list').innerHTML = '';
  document.getElementById('summary-bar').style.display    = 'none';
  document.getElementById('export-bar').style.display     = 'none';
  document.getElementById('results-section').style.display = 'none';
  document.getElementById('empty-results').style.display   = 'none';
  restoreScan(saved);
}

function populateScanDropdown(scans, selectTs) {
  const row = document.getElementById('prev-scans-row');
  const sel = document.getElementById('prev-scans-select');
  if (!scans || scans.length === 0) { row.style.display = 'none'; return; }

  const now = Date.now();
  sel.innerHTML = '';
  scans.forEach(scan => {
    const opt  = document.createElement('option');
    opt.value  = scan.ts;
    const mins = Math.round((now - scan.ts) / 60000);
    const age  = mins < 1 ? 'just now' : mins < 60 ? mins + 'm ago' : Math.round(mins/60) + 'h ago';
    const parts = (scan.dir || '').split('/').filter(Boolean);
    const short = parts.length > 2 ? '…/' + parts.slice(-2).join('/') : scan.dir || '';
    opt.textContent = age + (short ? ' — ' + short : '');
    opt.title = scan.dir || '';
    sel.appendChild(opt);
  });
  if (selectTs) sel.value = selectTs;
  row.style.display = 'flex';
}

function restoreScan(saved) {
  Object.assign(folderData, saved.folderData);
  if (saved.dir) document.getElementById('dir-input').value = saved.dir;

  document.getElementById('results-section').style.display = 'block';
  for (const [dir, fd] of Object.entries(folderData)) {
    upsertFolderGroup(dir);
    for (const ev of fd.issues) appendIssueRow(ev);
  }

  updateSummary();
  document.getElementById('summary-bar').style.display = 'flex';
  document.getElementById('s-scanned').textContent =
    (saved.scanned || 0).toLocaleString();

  const total = Object.values(folderData).reduce((s,f) => s+f.total, 0);
  document.getElementById('export-bar').style.display = 'flex';
  document.getElementById('export-label').textContent =
    total + ' issue' + (total!==1?'s':'') + ' found across '
    + Object.keys(folderData).length + ' folder'
    + (Object.keys(folderData).length!==1?'s':'');

  applyFilter();
}

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
const exifData = {};       // { dir: { files: [], count: 0 } }
const exifGrids = new Map();  // dir → { grid: Element, badge: Element }

function startExifScan() {
  const dir = document.getElementById('dir-input').value.trim();
  if (!dir) { alert('Please enter a directory path.'); return; }

  Object.keys(exifData).forEach(k => delete exifData[k]);
  exifGrids.clear();
  document.getElementById('exif-folder-list').innerHTML = '';
  document.getElementById('exif-section').style.display = 'none';
  document.getElementById('exif-summary-label').textContent = '';

  document.getElementById('scan-btn').disabled  = true;
  document.getElementById('exif-btn').disabled  = true;
  document.getElementById('exif-cancel-btn').disabled = false;
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
        ? `✓ Done — ${(ev.scanned||0).toLocaleString()} files in ${ev.elapsed}s`
        : `Cancelled after ${(ev.scanned||0).toLocaleString()} files`;
      document.getElementById('p-current').textContent = label;
      document.getElementById('p-current').classList.remove('scanning-pulse');
      document.getElementById('p-bar').style.width = '100%';
      const total = Object.values(exifData).reduce((s, d) => s + d.count, 0);
      document.getElementById('exif-summary-label').textContent =
        total.toLocaleString() + ' file' + (total !== 1 ? 's' : '');
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
  const thumbUrl = '/api/thumbnail?path=' + encodeURIComponent(ev.filepath);

  const card = document.createElement('div');
  card.className = 'exif-card' + (hasExif ? '' : ' no-exif');
  card.title = ev.filepath;

  const thumbHtml = isVideo
    ? `<div class="exif-card-thumb exif-card-thumb-video"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><polygon points="5 3 19 12 5 21 5 3"/></svg><span class="exif-card-vidext">${escHtml(ev.ext.replace('.','').toUpperCase())}</span></div>`
    : `<div class="exif-card-thumb"><img class="exif-card-img" data-src="${escHtml(thumbUrl)}" alt="" onerror="this.parentElement.classList.add('exif-thumb-error')"></div>`;

  card.innerHTML = `
    ${thumbHtml}
    <div class="exif-card-meta">
      <div class="exif-card-filename">${escHtml(ev.filename)}</div>
      ${camera   ? `<div class="exif-card-camera">${escHtml(camera)}</div>` : ''}
      ${ev.date  ? `<div class="exif-card-date"><span class="exif-card-label">Capture Time</span> ${escHtml(ev.date)}</div>` : ''}
      ${settings ? `<div class="exif-card-settings">${escHtml(settings)}</div>` : ''}
      ${dims     ? `<div class="exif-card-dims">${escHtml(dims)}</div>` : ''}
      <div class="exif-card-size">${formatSize(ev.file_size || 0)}</div>
      ${(ev.gps_lat != null && ev.gps_lng != null) ? `<a class="exif-card-gps" href="https://maps.google.com/?q=${ev.gps_lat},${ev.gps_lng}" target="_blank" rel="noopener">◎ ${ev.gps_lat.toFixed(4)}, ${ev.gps_lng.toFixed(4)}</a>` : ''}
      <div class="exif-card-no-exif">No EXIF</div>
    </div>
  `;

  const img = card.querySelector('.exif-card-img');
  if (img) _thumbObserver.observe(img);

  grid.appendChild(card);

  // Update folder file count
  const badge = refs && refs.badge;
  if (badge) badge.textContent = exifData[ev.dir].count + ' file' + (exifData[ev.dir].count !== 1 ? 's' : '');
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

function cancelExifScan() {
  fetch('/api/exif-cancel', { method: 'POST' });
  if (exifEventSource) { exifEventSource.close(); exifEventSource = null; }
  exifDone();
}

function exifDone() {
  if (exifEventSource) { exifEventSource.close(); exifEventSource = null; }
  document.getElementById('scan-btn').disabled  = false;
  document.getElementById('exif-btn').disabled  = false;
  document.getElementById('exif-cancel-btn').disabled = true;
}

function exportExifData() {
  const header = ['Filename','Directory','Extension','File Size (bytes)',
                  'Camera Make','Camera Model','Lens','Date',
                  'ISO','Aperture','Shutter','Focal Length','Width','Height','GPS Lat','GPS Lng','Has EXIF'];
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

// ── Mount status watcher ─────────────────────────────────────────────────────
let mountSource = null;

function watchMount(path) {
  if (mountSource) { mountSource.close(); mountSource = null; }

  const el = document.getElementById('mount-status');
  if (!path) { el.style.display = 'none'; return; }

  mountSource = new EventSource('/api/mount-status?path=' + encodeURIComponent(path));

  mountSource.onmessage = function(e) {
    const data = JSON.parse(e.data);
    if (data.exists) {
      el.className = 'mount-status mounted';
      el.innerHTML = '<span class="dot"></span>Directory available \u2014 ready to scan';
      el.style.display = 'flex';
      setTimeout(function() { if (el.className.includes('mounted')) el.style.display = 'none'; }, 5000);
      // Keep SSE open \u2014 drive may unmount while the page is open
    } else {
      el.className = 'mount-status unmounted';
      el.innerHTML = '<span class="dot"></span>Volume not mounted \u2014 waiting for drive\u2026';
      el.style.display = 'flex';
    }
  };

  mountSource.onerror = function() {
    mountSource.close();
    mountSource = null;
    el.style.display = 'none';
  };
}

// ── Init ─────────────────────────────────────────────────────────────────────
(async function() {
  checkLibs();

  // Restore saved scans first — restoreScan() overwrites dir-input with the
  // scanned directory, which may differ from lastScanDir in localStorage.
  const scans = await loadSavedScans();
  if (scans.length > 0) {
    populateScanDropdown(scans, scans[0].ts);
    restoreScan(scans[0]);
  } else {
    // No saved scans — fall back to localStorage
    try {
      const savedDir = localStorage.getItem('lastScanDir');
      if (savedDir) document.getElementById('dir-input').value = savedDir;
    } catch(e) {}
  }

  // Watch the final dir-input value, whichever source set it.
  const dir = document.getElementById('dir-input').value.trim();
  if (dir) watchMount(dir);
})();
