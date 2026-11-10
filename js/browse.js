// Directory selection: the browse modal and the pre-scan media count.

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
  scheduleDirCount(true);
}

// ── Pre-scan count ───────────────────────────────────────────────────────────
// Shows how many photos and videos a scan of the chosen directory will process.
// Waits for a pause in typing; each new count replaces (and server-side cancels)
// the previous one.
let dirCountSource = null;
let dirCountTimer = null;

function scheduleDirCount(immediate) {
  clearTimeout(dirCountTimer);
  dirCountTimer = setTimeout(startDirCount, immediate ? 0 : 400);
}

function stopDirCount() {
  clearTimeout(dirCountTimer);
  if (dirCountSource) { dirCountSource.close(); dirCountSource = null; }
}

function startDirCount() {
  stopDirCount();
  const el = document.getElementById('dir-count');
  const dir = document.getElementById('dir-input').value.trim();
  if (!dir) { el.style.display = 'none'; return; }

  // Numbers are wrapped in <strong> so they stand out; all other text is fixed
  const plural = (n, word) => `<strong>${n.toLocaleString()}</strong> ${word}${n !== 1 ? 's' : ''}`;
  const show = (html, cls) => { el.className = 'dir-count' + (cls ? ' ' + cls : ''); el.innerHTML = html; el.style.display = 'block'; };
  show('Counting\u2026', 'counting');

  const src = new EventSource('/api/count?dir=' + encodeURIComponent(dir));
  dirCountSource = src;
  src.onmessage = e => {
    if (src !== dirCountSource) return;   // a newer count has started
    const ev = JSON.parse(e.data);
    if (ev.type === 'progress') {
      show(`Counting\u2026 ${plural(ev.photos, 'photo')}, ${plural(ev.videos, 'video')} so far`, 'counting');
    } else if (ev.type === 'complete') {
      stopDirCount();
      if (ev.photos + ev.videos === 0) {
        show(`No photos or videos found (${plural(ev.folders, 'folder')} searched)`, 'problem');
      } else {
        show(`${plural(ev.photos, 'photo')} and ${plural(ev.videos, 'video')} in ${plural(ev.folders, 'folder')}`
          + (ev.videos ? ' \u00b7 Blur Check checks photos only' : ''));
      }
    } else if (ev.type === 'error') {
      stopDirCount();
      show(ev.reason === 'not_dir' ? 'That path is a file, not a folder' : 'Folder not found', 'problem');
    }
  };
  src.onerror = () => { if (src === dirCountSource) stopDirCount(); };
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
      list.innerHTML = '<div class="browse-empty" style="color:var(--red)">Cannot connect to server. Try closing and re-opening the browser.</div>';
    }
  };
  xhr.send();
}

function browseTo(path) {
  fetchBrowse('/api/browse?path=' + encodeURIComponent(path), 2);
}
