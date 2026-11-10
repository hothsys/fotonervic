// Click delegation for result rows and startup. Loaded last.

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

// ── Init ─────────────────────────────────────────────────────────────────────
(async function() {
  checkLibs();
  refreshQualityModelStatus();   // so the Blur Check panel is current when it appears

  // Saved scans are listed but not loaded; the user picks one from the
  // dropdown. The directory box gets the last folder any scan was started on.
  await migrateLegacyDB();
  populateScanDropdown(await loadSavedScans(), null);
  try {
    const savedDir = localStorage.getItem('lastScanDir');
    if (savedDir) document.getElementById('dir-input').value = savedDir;
  } catch(e) {}

  const dir = document.getElementById('dir-input').value.trim();
  if (dir) watchMount(dir);
  if (dir) scheduleDirCount(true);
  document.getElementById('dir-input').addEventListener('input', () => scheduleDirCount(false));
})();
