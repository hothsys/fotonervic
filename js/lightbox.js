// Lightbox: full-screen preview of Exif Info and Blur Check photos.

// ── Lightbox ─────────────────────────────────────────────────────────────────
// Clicking an image card's thumbnail opens it; the arrow keys (or the ‹ ›
// buttons) step through the visible cards of that section in their current
// order. Browsers can't show RAW (or HEIC in Chrome), so photos come from
// /api/preview as upright JPEGs: a screen-size version, and the full-resolution
// one when the photo is clicked to zoom to 100% (to check focus). Scroll or drag
// to pan; click again or press Escape to zoom back out. Photos already shown at
// their actual size can't be zoomed, so they get no zoom cursor. Videos have no
// lightbox.
const PREVIEW_FORMAT_VERSION = 1;  // bump when /api/preview output changes
const PREVIEW_SIZE = 2560;         // long side of the screen-size version (PREVIEW_SIZE in backend/preview.py)

let lbCards = [];      // the image cards being stepped through
let lbIndex = 0;
let lbZoomed = false;
let lbZoomable = false;   // false when the photo is already shown at its actual size
let lbLoadToken = 0;   // ignores loads that finish after moving to another photo
let lbDrag = null;     // { x, y, left, top, moved } while panning a zoomed photo

function previewUrl(path, full) {
  const v = PREVIEW_FORMAT_VERSION + (thumbCacheToken ? '.' + thumbCacheToken : '');
  return '/api/preview?v=' + v + (full ? '&full=1' : '') + '&path=' + encodeURIComponent(path);
}

function lbPath(i) {
  return lbCards[i].querySelector('[data-lightbox]').getAttribute('data-lightbox');
}

function openLightbox(thumb) {
  const card = thumb.closest('.exif-card');
  const section = card.closest('#exif-section, #blur-section') || document;
  lbCards = [...section.querySelectorAll('.exif-card')]
    .filter(c => c.offsetParent !== null && c.querySelector('[data-lightbox]'));
  lbIndex = Math.max(0, lbCards.indexOf(card));
  const lb = document.getElementById('lightbox');
  // The busy lock disables every button during a scan; the lightbox's own stay usable
  lb.querySelectorAll('button').forEach(b => { b.disabled = false; });
  lb.classList.add('open');
  showLightboxPhoto();
}

function closeLightbox() {
  document.getElementById('lightbox').classList.remove('open');
  lbLoadToken++;
  setLightboxZoom(false);
  document.getElementById('lb-img').removeAttribute('src');
}

function lightboxNav(dir) {
  const next = lbIndex + dir;
  if (next < 0 || next >= lbCards.length) return;
  lbIndex = next;
  showLightboxPhoto();
}

function lightboxCaptionHtml(size) {
  const card = lbCards[lbIndex];
  const r = card.blurResult;
  const parts = [`<span class="lb-filename">${escHtml(lbPath(lbIndex).split('/').pop())}</span>`];
  if (r && r.blur_score != null) {
    parts.push(`<span class="blur-badge ${blurBadgeClass(r.blur_score)}">Blur ${Math.round(r.blur_score)}</span>`);
  }
  if (r && isDamaged(r)) parts.push(integrityTagHtml(r));
  if (size) parts.push(`<span class="lb-dims">${size}</span>`);
  return parts.join('');
}

// Load url into the lightbox image; onReady runs once it's showing
function loadLightboxImage(url, onReady) {
  const token = ++lbLoadToken;
  const img = document.getElementById('lb-img');
  const lb = document.getElementById('lightbox');
  lb.classList.add('loading');
  lb.classList.remove('failed');
  const next = new Image();
  next.onload = () => {
    if (token !== lbLoadToken) return;
    img.src = next.src;
    lb.classList.remove('loading');
    if (onReady) onReady(next);
  };
  next.onerror = () => {
    if (token !== lbLoadToken) return;
    lb.classList.remove('loading');
    lb.classList.add('failed');
  };
  next.src = url;
}

// Zooming only helps when there are more pixels than the screen shows: either
// the screen-size version was scaled down by the server (the photo is bigger
// than PREVIEW_SIZE), or it's displayed smaller than its own size.
function updateLightboxZoomable() {
  const img = document.getElementById('lb-img');
  if (lbZoomed || !img.naturalWidth) return;
  const w = img.naturalWidth, h = img.naturalHeight;
  const downscaled = Math.max(w, h) >= PREVIEW_SIZE;
  const shrunk = img.getBoundingClientRect().width < w - 1;
  lbZoomable = downscaled || shrunk;
  document.getElementById('lightbox').classList.toggle('no-zoom', !lbZoomable);
  document.getElementById('lb-caption').innerHTML =
    lightboxCaptionHtml(lbZoomable ? '' : `100% · ${w} × ${h}`);
}

function showLightboxPhoto() {
  setLightboxZoom(false);
  const path = lbPath(lbIndex);
  document.getElementById('lb-counter').textContent = `${lbIndex + 1} / ${lbCards.length}`;
  document.getElementById('lb-prev').hidden = lbIndex === 0;
  document.getElementById('lb-next').hidden = lbIndex === lbCards.length - 1;
  document.getElementById('lb-caption').innerHTML = lightboxCaptionHtml();
  document.getElementById('lb-img').removeAttribute('src');
  loadLightboxImage(previewUrl(path, false), () => requestAnimationFrame(updateLightboxZoomable));
  // Warm the cache for the neighbours, so stepping through is quick
  [lbIndex - 1, lbIndex + 1].filter(i => i >= 0 && i < lbCards.length)
    .forEach(i => { new Image().src = previewUrl(lbPath(i), false); });
}

function setLightboxZoom(zoomed) {
  lbZoomed = zoomed;
  document.getElementById('lightbox').classList.toggle('zoomed', zoomed);
}

// Zoom to 100% around the clicked point, loading the full-resolution image
function zoomLightbox(clientX, clientY) {
  const img = document.getElementById('lb-img');
  const stage = document.getElementById('lb-stage');
  const rect = img.getBoundingClientRect();
  const fx = (clientX - rect.left) / rect.width;
  const fy = (clientY - rect.top) / rect.height;
  loadLightboxImage(previewUrl(lbPath(lbIndex), true), full => {
    setLightboxZoom(true);
    stage.scrollLeft = fx * full.naturalWidth - stage.clientWidth / 2;
    stage.scrollTop  = fy * full.naturalHeight - stage.clientHeight / 2;
    document.getElementById('lb-caption').innerHTML =
      lightboxCaptionHtml(`100% · ${full.naturalWidth} × ${full.naturalHeight}`);
  });
}

function unzoomLightbox() {
  // Back to the screen-size version (cached, so it's instant)
  loadLightboxImage(previewUrl(lbPath(lbIndex), false), () => {
    setLightboxZoom(false);
    requestAnimationFrame(updateLightboxZoomable);
  });
  document.getElementById('lb-caption').innerHTML = lightboxCaptionHtml();
}

(function initLightbox() {
  const lb = document.getElementById('lightbox');
  const stage = document.getElementById('lb-stage');
  const img = document.getElementById('lb-img');

  img.addEventListener('click', e => {
    if (lbDrag && lbDrag.moved) return;   // the end of a pan, not a click
    if (lbZoomed) unzoomLightbox();
    else if (!lbZoomable) return;         // already at actual size
    else zoomLightbox(e.clientX, e.clientY);
  });
  stage.addEventListener('click', e => {   // the dark area around the photo
    if (e.target === stage && !lbZoomed) closeLightbox();
  });
  // Drag to pan a zoomed photo
  stage.addEventListener('mousedown', e => {
    if (!lbZoomed || e.button !== 0) return;
    lbDrag = { x: e.clientX, y: e.clientY, left: stage.scrollLeft, top: stage.scrollTop, moved: false };
    e.preventDefault();
  });
  window.addEventListener('mousemove', e => {
    if (!lbDrag) return;
    const dx = e.clientX - lbDrag.x, dy = e.clientY - lbDrag.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) lbDrag.moved = true;
    stage.scrollLeft = lbDrag.left - dx;
    stage.scrollTop  = lbDrag.top - dy;
  });
  window.addEventListener('mouseup', () => {
    setTimeout(() => { lbDrag = null; });   // after the click event that follows
  });
  // A resize can show the whole photo at actual size, or shrink it again
  window.addEventListener('resize', () => { if (lb.classList.contains('open')) updateLightboxZoomable(); });
  document.addEventListener('keydown', e => {
    if (!lb.classList.contains('open')) return;
    if (e.key === 'Escape') { e.preventDefault(); lbZoomed ? unzoomLightbox() : closeLightbox(); }
    else if (e.key === 'ArrowLeft')  { e.preventDefault(); lightboxNav(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); lightboxNav(1); }
  });
})();
