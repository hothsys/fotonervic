// Watches whether the chosen directory's volume is mounted.

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
      el.innerHTML = '<span class="dot"></span>Directory available and ready to scan';
      el.style.display = 'flex';
      setTimeout(function() { if (el.className.includes('mounted')) el.style.display = 'none'; }, 5000);
      // Keep SSE open; the drive may unmount while the page is open
    } else {
      el.className = 'mount-status unmounted';
      el.innerHTML = '<span class="dot"></span>Volume not mounted. Waiting for drive\u2026';
      el.style.display = 'flex';
    }
  };

  mountSource.onerror = function() {
    mountSource.close();
    mountSource = null;
    el.style.display = 'none';
  };
}
