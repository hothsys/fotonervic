// Saved Scan Directory results (IndexedDB) and the previous-scans dropdown.

// ── Session persistence (IndexedDB) ──────────────────────────────────────────
// Deliberately not the app's display name (app.conf APP_NAME), so renaming the
// app doesn't strand saved scans in a database the page no longer opens
const DB_NAME  = 'scan-history';
const DB_STORE = 'scan';
const MAX_SCANS = 10;
// Databases used by earlier versions, which were named after the app. Saved
// scans are moved out of them once on startup (migrateLegacyDB), then they
// are deleted.
const LEGACY_DB_NAMES = ['fotonervic', 'FotoNerveShatter'];

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

async function migrateLegacyDB() {
  // databases() lets us check without open() silently creating an empty DB
  if (!indexedDB.databases) return;
  let names = [];
  try { names = (await indexedDB.databases()).map(d => d.name); } catch(e) { return; }
  for (const legacy of LEGACY_DB_NAMES) {
    if (names.includes(legacy)) await migrateOneDB(legacy);
  }
}

async function migrateOneDB(legacyName) {
  try {
    const old = await idbReq(indexedDB.open(legacyName));
    let keys = [], vals = [];
    if (old.objectStoreNames.contains(DB_STORE)) {
      const store = old.transaction(DB_STORE, 'readonly').objectStore(DB_STORE);
      [keys, vals] = await Promise.all([idbReq(store.getAllKeys()), idbReq(store.getAll())]);
    }
    old.close();

    if (keys.length) {
      const db = await openDB();
      const store = db.transaction(DB_STORE, 'readwrite').objectStore(DB_STORE);
      await Promise.all(keys.map((k, i) => idbReq(store.put(vals[i], k))));
    }
    indexedDB.deleteDatabase(legacyName);
  } catch(e) {}
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
  hideScanResults();
}

async function loadSelectedScan(sel) {
  const ts = parseInt(sel.value);
  if (!ts) return;
  const saved = await loadScan(ts);
  if (!saved) {
    alert('Could not load this scan. It may have been cleared. Try rescanning.');
    return;
  }
  Object.keys(folderData).forEach(k => delete folderData[k]);
  document.getElementById('folder-list').innerHTML = '';
  hideScanResults();
  hideExifResults();
  hideBlurResults();
  restoreScan(saved);
  scheduleDirCount(true);
}

function populateScanDropdown(scans, selectTs) {
  const row = document.getElementById('prev-scans-row');
  const sel = document.getElementById('prev-scans-select');
  if (!scans || scans.length === 0) { row.style.display = 'none'; return; }

  // Exact date and time in the user's locale, e.g. "Oct 26, 2026, 2:15 PM"
  const when = ts => new Date(ts).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  sel.innerHTML = '';
  if (!selectTs) {
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Select a scan to load\u2026';
    placeholder.disabled = placeholder.selected = true;
    sel.appendChild(placeholder);
  }
  [...scans].sort((a, b) => b.ts - a.ts).forEach(scan => {   // most recent first
    const opt  = document.createElement('option');
    opt.value  = scan.ts;
    const parts = (scan.dir || '').split('/').filter(Boolean);
    const short = parts.length > 2 ? '…/' + parts.slice(-2).join('/') : scan.dir || '';
    opt.textContent = when(scan.ts) + (short ? ' \u00b7 ' + short : '');
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
