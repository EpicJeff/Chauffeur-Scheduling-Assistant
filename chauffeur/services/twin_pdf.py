"""Render drawing sheets once for the twin's image inputs."""
import base64
from contextlib import closing
import io
import math

import pypdfium2 as pdfium
from PIL import Image


def render_pages(pdf: bytes, dpi: int = 150, max_side: int = 2048,
                 max_pages: int = 16) -> list[dict]:
    """Return 1-based PNG sheets, capped by page count and raster dimensions."""
    if not pdf or any(type(v) is not int or v <= 0
                      for v in (dpi, max_side, max_pages)):
        raise ValueError('A readable PDF and positive render limits are required.')
    try:
        with closing(pdfium.PdfDocument(pdf)) as doc:
            if not len(doc):
                raise ValueError('The drawing has no pages.')
            pages = []
            for index in range(min(len(doc), max_pages)):
                with closing(doc[index]) as page:
                    width, height = page.get_size()
                    if not all(math.isfinite(v) and v > 0 for v in (width, height)):
                        raise ValueError('The drawing has an invalid page size.')
                    # Avoid allocating a full-size architectural sheet only to
                    # shrink it afterward. PDFium rounds dimensions upward.
                    scale = min(dpi / 72, max_side / max(width, height))
                    with closing(page.render(scale=scale)) as bitmap:
                        with bitmap.to_pil() as image:
                            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                            output = io.BytesIO()
                            image.save(output, format='PNG')
                    pages.append({'page': index + 1, 'mime': 'image/png',
                                  'b64': base64.b64encode(output.getvalue()).decode('ascii')})
            return pages
    except (pdfium.PdfiumError, OSError, ValueError, TypeError) as exc:
        raise ValueError('Could not read the PDF drawing.') from exc
