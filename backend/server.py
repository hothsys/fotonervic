"""HTTP handler: serves the frontend and the /api/ endpoints."""

import csv
import html
import io
import json
import os
import subprocess
import sys
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from backend.blur.quality_model import quality_model_status, start_quality_model_download
from backend.blur.scan import blur_scan_gen, blur_state
from backend.config import APP_DIR, APP_NAME, APP_TITLE
from backend.exif import exif_scan_gen, exif_state
from backend.formats import JPEG_EXTS, RAW_EXTS
from backend.integrity import check_integrity
from backend.jobs import _cancel_job, _finish_job, _start_job
from backend.repair import salvage_jpeg
from backend.scan import count_media_gen, count_state, scan_directory_gen, scan_state
from backend.thumbnails import (
    _THUMBNAIL_CACHE_MAX,
    _generate_thumbnail,
    _thumbnail_cache,
    _thumbnail_lock,
)
from backend.tiff import _find_best_embedded_preview

# ─── HTTP handler ─────────────────────────────────────────────────────────────

class ScannerHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=APP_DIR, **kwargs)

    def end_headers(self):
        # Without this, browsers heuristically cache index.html/js/css (they
        # only get Last-Modified) and keep running stale code after an update.
        # no-cache still allows cheap 304 revalidation.
        if not self.path.startswith('/api/'):
            self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def _send_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, data, mimetype, filename):
        self.send_response(200)
        self.send_header('Content-Type', mimetype)
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('X-Filename', filename)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            return {}

    def _query_params(self):
        return parse_qs(urlparse(self.path).query)

    def _route_path(self):
        return urlparse(self.path).path

    # ── GET routes ──

    def do_GET(self):
        path = self._route_path()
        try:
            if path == '/api/scan':
                self._handle_scan()
            elif path == '/api/export':
                self._handle_export()
            elif path == '/api/browse':
                self._handle_browse()
            elif path == '/api/libs':
                self._handle_libs()
            elif path == '/api/mount-status':
                self._handle_mount_status()
            elif path == '/api/blur-scan':
                self._handle_blur_scan()
            elif path == '/api/count':
                self._handle_count()
            elif path == '/api/integrity':
                self._handle_integrity()
            elif path == '/api/quality-model':
                self._send_json(quality_model_status())
            elif path == '/api/exif-scan':
                self._handle_exif_scan()
            elif path == '/api/thumbnail':
                self._handle_thumbnail()
            elif path in ('/', '/index.html'):
                self._handle_index()
            else:
                super().do_GET()
        except (ConnectionResetError, BrokenPipeError):
            pass

    # ── POST routes ──

    def do_POST(self):
        path = self._route_path()
        try:
            if path == '/api/cancel':
                self._handle_cancel()
            elif path == '/api/exif-cancel':
                self._handle_exif_cancel()
            elif path == '/api/blur-cancel':
                _cancel_job(blur_state)
                self._send_json({'ok': True})
            elif path == '/api/quality-model/download':
                start_quality_model_download()
                self._send_json(quality_model_status())
            elif path == '/api/reveal':
                self._handle_reveal()
            elif path == '/api/extract-preview':
                self._handle_extract_preview()
            elif path == '/api/repair-jpeg':
                self._handle_repair_jpeg()
            elif path == '/api/salvage-image':
                self._handle_salvage_image()
            elif path == '/api/clear-cache':
                self._handle_clear_cache()
            else:
                self.send_error(404)
        except (ConnectionResetError, BrokenPipeError):
            pass

    # ── Handler methods ──

    def _handle_index(self):
        """Serve index.html with {{APP_NAME}} / {{APP_TITLE}} filled in from app.conf."""
        with open(os.path.join(APP_DIR, 'index.html'), encoding='utf-8') as f:
            body = (f.read()
                    .replace('{{APP_NAME}}', html.escape(APP_NAME))
                    .replace('{{APP_TITLE}}', html.escape(APP_TITLE))
                    .encode())
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_scan(self):
        params = self._query_params()
        root_dir = params.get('dir', [''])[0].strip()
        if not root_dir:
            return self._send_json({'error': 'No directory specified'}, 400)

        cancel  = _start_job(scan_state)
        results = scan_state['results']

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        try:
            for event in scan_directory_gen(root_dir, cancel):
                if event.get('type') == 'issue':
                    results.append(event)
                line = f"data: {json.dumps(event)}\n\n"
                self.wfile.write(line.encode())
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            _finish_job(scan_state, cancel)

    def _handle_cancel(self):
        _cancel_job(scan_state)
        self._send_json({'ok': True})

    def _handle_exif_cancel(self):
        _cancel_job(exif_state)
        self._send_json({'ok': True})

    def _handle_thumbnail(self):
        params = self._query_params()
        filepath = params.get('path', [''])[0].strip()

        if not filepath or not os.path.exists(filepath):
            self.send_error(404)
            return

        with _thumbnail_lock:
            data = _thumbnail_cache.get(filepath)
            if data is not None:
                _thumbnail_cache.move_to_end(filepath)
        if data is None:
            data = _generate_thumbnail(filepath)  # slow; done outside the lock
            if data is None:
                self.send_error(404)
                return
            with _thumbnail_lock:
                _thumbnail_cache[filepath] = data
                _thumbnail_cache.move_to_end(filepath)
                if len(_thumbnail_cache) > _THUMBNAIL_CACHE_MAX:
                    _thumbnail_cache.popitem(last=False)

        self.send_response(200)
        self.send_header('Content-Type', 'image/jpeg')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        self.wfile.write(data)

    def _handle_clear_cache(self):
        """Empty the server's thumbnail cache and tell the browser to drop its
        HTTP cache for this origin. Saved scans (IndexedDB) and localStorage
        are untouched: Clear-Site-Data "cache" covers only the HTTP cache."""
        with _thumbnail_lock:
            cleared = len(_thumbnail_cache)
            _thumbnail_cache.clear()
        body = json.dumps({'ok': True, 'thumbnails_cleared': cleared}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Clear-Site-Data', '"cache"')
        self.end_headers()
        self.wfile.write(body)

    def _handle_exif_scan(self):
        params = self._query_params()
        root_dir = params.get('dir', [''])[0].strip()
        if not root_dir:
            return self._send_json({'error': 'No directory specified'}, 400)

        cancel  = _start_job(exif_state)
        results = exif_state['results']

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        try:
            for event in exif_scan_gen(root_dir, cancel):
                if event.get('type') == 'exif_result':
                    results.append(event)
                line = f"data: {json.dumps(event, default=str)}\n\n"
                self.wfile.write(line.encode())
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            _finish_job(exif_state, cancel)

    def _handle_integrity(self):
        """Integrity check for one file: GET /api/integrity?path=..."""
        filepath = self._query_params().get('path', [''])[0].strip()
        if not filepath or not os.path.isfile(filepath):
            return self._send_json({'error': 'File not found'}, 404)
        self._send_json({'path': filepath, **check_integrity(filepath)})

    def _handle_count(self):
        root_dir = self._query_params().get('dir', [''])[0].strip()
        if not root_dir:
            return self._send_json({'error': 'No directory specified'}, 400)

        cancel = _start_job(count_state)   # cancels a count still running for an older path
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()
        try:
            for event in count_media_gen(root_dir, cancel):
                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            _finish_job(count_state, cancel)

    def _handle_blur_scan(self):
        params = self._query_params()
        root_dir = params.get('dir', [''])[0].strip()
        if not root_dir:
            return self._send_json({'error': 'No directory specified'}, 400)

        cancel  = _start_job(blur_state)
        results = blur_state['results']

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        try:
            for event in blur_scan_gen(root_dir, cancel):
                if event.get('type') == 'blur_result':
                    results.append(event)
                self.wfile.write(f"data: {json.dumps(event, default=str)}\n\n".encode())
                self.wfile.flush()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            _finish_job(blur_state, cancel)

    def _handle_export(self):
        results = scan_state.get('results', [])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Status', 'Filename', 'Extension', 'Directory',
                         'Full Path', 'File Size (bytes)', 'Corruption %', 'Issue'])
        for r in results:
            writer.writerow([
                r.get('status',''),
                r.get('filename',''),
                r.get('ext',''),
                r.get('dir',''),
                r.get('filepath',''),
                r.get('file_size',''),
                r.get('corrupt_pct',''),
                r.get('reason',''),
            ])

        output.seek(0)
        # UTF-8 BOM so Excel interprets unicode characters (em dashes, etc.) correctly
        csv_str = '\ufeff' + output.getvalue()
        body = csv_str.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Disposition',
                         'attachment; filename=photo_scan_results.csv')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_browse(self):
        params = self._query_params()
        raw = params.get('path', [''])[0].strip()
        target = Path(raw).expanduser().resolve() if raw else Path.home()

        if not target.exists() or not target.is_dir():
            target = Path.home()

        try:
            dirs = sorted([
                d.name for d in target.iterdir()
                if d.is_dir() and not d.name.startswith('.')
            ], key=str.lower)
        except PermissionError:
            dirs = []

        parent = str(target.parent) if target != target.parent else None
        self._send_json({
            'current': str(target),
            'parent': parent,
            'dirs': dirs,
        })

    def _handle_reveal(self):
        data = self._read_json_body()
        target = data.get('path', '')
        if not target or not os.path.exists(target):
            return self._send_json({'error': 'Path not found'}, 404)

        try:
            if sys.platform == 'darwin':
                if os.path.isfile(target):
                    subprocess.Popen(['open', '-R', target])
                else:
                    subprocess.Popen(['open', target])
            elif sys.platform == 'win32':
                if os.path.isfile(target):
                    subprocess.Popen(['explorer', '/select,', target])
                else:
                    subprocess.Popen(['explorer', target])
            else:
                parent = os.path.dirname(target) if os.path.isfile(target) else target
                subprocess.Popen(['xdg-open', parent])
            self._send_json({'ok': True})
        except Exception as e:
            self._send_json({'error': str(e)}, 500)

    def _handle_extract_preview(self):
        data = self._read_json_body()
        filepath = data.get('filepath', '')

        if not filepath or not os.path.exists(filepath):
            return self._send_json({'error': 'File not found'}, 404)

        ext = Path(filepath).suffix.lower()
        if ext not in RAW_EXTS:
            return self._send_json({'error': 'Not a RAW file'}, 400)

        preview = _find_best_embedded_preview(filepath)
        if not preview:
            return self._send_json({'error': 'No embedded preview found'}, 404)

        pw, ph, p_off, p_len = preview

        try:
            with open(filepath, 'rb') as f:
                f.seek(p_off)
                jpeg_bytes = f.read(p_len)
        except Exception as e:
            return self._send_json({'error': f'Read error: {e}'}, 500)

        stem = Path(filepath).stem
        filename = f'{stem}_preview.jpg'
        self._send_file(jpeg_bytes, 'image/jpeg', filename)

    def _handle_repair_jpeg(self):
        data = self._read_json_body()
        filepath = data.get('filepath', '')

        if not filepath or not os.path.exists(filepath):
            return self._send_json({'error': 'File not found'}, 404)

        ext = Path(filepath).suffix.lower()
        if ext not in JPEG_EXTS:
            return self._send_json({'error': 'Not a JPEG file'}, 400)

        # Decode the truncated image; Pillow can recover all pixel data
        # even when the compressed stream is incomplete
        try:
            from PIL import Image, ImageFile
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            img = Image.open(filepath)
            img.load()
        except Exception as e:
            return self._send_json({
                'error': f'Cannot decode image for repair: {e}'
            }, 422)

        # Preserve EXIF and ICC profile
        exif_data = img.info.get('exif', b'')
        icc_profile = img.info.get('icc_profile', None)

        # Re-encode as a structurally clean JPEG
        save_kwargs = {'quality': 100, 'optimize': True}
        if exif_data:
            save_kwargs['exif'] = exif_data
        if icc_profile:
            save_kwargs['icc_profile'] = icc_profile

        buf = io.BytesIO()
        img.save(buf, 'JPEG', **save_kwargs)

        # Verify the result decodes cleanly in strict mode
        buf.seek(0)
        try:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
            verify = Image.open(buf)
            verify.load()
        except Exception as e:
            return self._send_json({
                'error': f'Repair produced an invalid file: {e}'
            }, 422)

        buf.seek(0)
        repaired_bytes = buf.read()

        stem = Path(filepath).stem
        suffix = Path(filepath).suffix
        filename = f'{stem}_repaired{suffix}'
        self._send_file(repaired_bytes, 'image/jpeg', filename)

    def _handle_salvage_image(self):
        data = self._read_json_body()
        filepath = data.get('filepath', '')

        if not filepath or not os.path.exists(filepath):
            return self._send_json({'error': 'File not found'}, 404)

        ext = Path(filepath).suffix.lower()
        if ext not in JPEG_EXTS:
            return self._send_json({'error': 'Not a JPEG file'}, 400)

        try:
            image_bytes, filename = salvage_jpeg(filepath)
        except ValueError as e:
            return self._send_json({'error': str(e)}, 422)
        except Exception as e:
            return self._send_json({'error': f'Salvage failed: {e}'}, 500)

        self._send_file(image_bytes, 'image/jpeg', filename)

    def _handle_libs(self):
        status = {}
        try:
            from PIL import Image
            status['pillow'] = True
        except ImportError:
            status['pillow'] = False

        try:
            import rawpy
            status['rawpy'] = True
        except ImportError:
            status['rawpy'] = False

        try:
            import pillow_heif
            status['pillow_heif'] = True
        except ImportError:
            status['pillow_heif'] = False

        self._send_json(status)

    def _handle_mount_status(self):
        params = self._query_params()
        path = params.get('path', [''])[0].strip()
        if not path:
            return self._send_json({'error': 'No path specified'}, 400)

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.end_headers()

        last_exists = None
        try:
            while True:
                # os.path.exists() can return True for empty mount-point dirs
                # that macOS leaves behind after ejecting a volume. Verify the
                # path is a non-empty accessible directory to avoid false positives.
                try:
                    exists = os.path.isdir(path) and next(os.scandir(path), None) is not None
                except OSError:
                    exists = False
                if exists != last_exists:
                    last_exists = exists
                    event = json.dumps({'exists': exists, 'path': path})
                    self.wfile.write(f"data: {event}\n\n".encode())
                    self.wfile.flush()
                time.sleep(3)
        except (ConnectionResetError, BrokenPipeError):
            pass

    def log_message(self, format, *args):
        pass  # Suppress default access log noise
