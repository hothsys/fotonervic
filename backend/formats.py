"""File extensions the app recognizes, grouped by how they are checked."""

SUPPORTED_EXTENSIONS = {
    # JPEG family
    '.jpg', '.jpeg', '.jpe', '.jfif',
    # PNG
    '.png',
    # HEIC / HEIF (Apple)
    '.heic', '.heif',
    # Nikon RAW
    '.nef', '.nrw',
    # Sony RAW
    '.arw', '.srf', '.sr2',
    # Canon RAW
    '.cr2', '.cr3',
    # Adobe DNG
    '.dng',
    # Fujifilm RAW
    '.raf',
    # Panasonic RAW
    '.rw2',
    # Olympus RAW
    '.orf',
    # Pentax RAW
    '.pef',
    # Samsung RAW
    '.srw',
    # TIFF
    '.tif', '.tiff',
    # WebP
    '.webp',
    # BMP
    '.bmp',
    # GIF
    '.gif',
    # Video: MP4 / MOV / AVI / MPEG
    '.mp4', '.m4v', '.mov',
    '.avi',
    '.mpg', '.mpeg',
}

JPEG_EXTS  = {'.jpg', '.jpeg', '.jpe', '.jfif'}
PNG_EXTS   = {'.png'}
HEIC_EXTS  = {'.heic', '.heif'}
RAW_EXTS   = {'.nef', '.nrw', '.arw', '.srf', '.sr2', '.cr2', '.cr3',
               '.dng', '.raf', '.rw2', '.orf', '.pef', '.srw'}
NEF_EXTS   = {'.nef', '.nrw'}
ARW_EXTS   = {'.arw', '.srf', '.sr2'}
TIFF_RAW_EXTS = NEF_EXTS | ARW_EXTS

VIDEO_EXTS = {'.mp4', '.m4v', '.mov', '.avi', '.mpg', '.mpeg'}
MP4_EXTS   = {'.mp4', '.m4v', '.mov'}
AVI_EXTS   = {'.avi'}
MPEG_EXTS  = {'.mpg', '.mpeg'}
