"""Render drawing sheets once for the twin's image inputs."""
import base64
from contextlib import closing
import io
import math
import threading

import pypdfium2 as pdfium
from PIL import Image

_RENDER_LOCK = threading.Lock()  # PDFium forbids simultaneous calls across threads.


def page_count(pdf: bytes) -> int:
    """Read the page count while serializing all PDFium calls."""
    try:
        with _RENDER_LOCK, closing(pdfium.PdfDocument(pdf)) as doc:
            if not len(doc):
                raise ValueError('The drawing has no pages.')
            return len(doc)
    except (pdfium.PdfiumError, OSError, ValueError, TypeError) as exc:
        raise ValueError('Could not read the PDF drawing.') from exc


def render_page(pdf: bytes, page: int, dpi: int = 150, max_side: int = 2048,
                grayscale: bool = False) -> Image.Image:
    """Return one detached 1-based raster; the caller owns and closes it.

    No PDFium resources escape the lock. PNG encoding happens in the caller,
    after releasing the lock, and masters never need a base64 intermediate.
    """
    if not pdf or any(type(v) is not int or v <= 0 for v in (page, dpi, max_side)):
        raise ValueError('A readable PDF and positive render limits are required.')
    try:
        with _RENDER_LOCK, closing(pdfium.PdfDocument(pdf)) as doc:
            if page > len(doc):
                raise ValueError('The drawing page does not exist.')
            with closing(doc[page - 1]) as sheet:
                width, height = sheet.get_size()
                if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                    raise ValueError('The drawing has an invalid page size.')
                # PDFium rounds upward; avoid an extra row at exact DPI boundaries.
                scale = math.nextafter(min(dpi / 72, max_side / max(width, height)), 0.0)
                with closing(sheet.render(scale=scale)) as bitmap:
                    with bitmap.to_pil() as image:
                        raster = image.convert('L') if grayscale else image.copy()
    except (pdfium.PdfiumError, OSError, ValueError, TypeError) as exc:
        raise ValueError('Could not read the PDF drawing.') from exc
    raster.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return raster


def render_pages(pdf: bytes, dpi: int = 150, max_side: int = 2048,
                 max_pages: int = 16) -> list[dict]:
    """Return 1-based PNG sheets, capped by page count and raster dimensions."""
    if not pdf or any(type(v) is not int or v <= 0
                      for v in (dpi, max_side, max_pages)):
        raise ValueError('A readable PDF and positive render limits are required.')
    pages = []
    for page in range(1, min(page_count(pdf), max_pages) + 1):
        with render_page(pdf, page, dpi=dpi, max_side=max_side) as image:
            with io.BytesIO() as output:
                image.save(output, format='PNG')
                pages.append({'page': page, 'mime': 'image/png',
                              'b64': base64.b64encode(output.getvalue()).decode('ascii')})
    return pages
