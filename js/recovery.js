// Recovery actions on result rows: Export Preview, Repair JPG, Salvage Image.

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
