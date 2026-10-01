"""Isolated, timeout-controlled PDF fallback for portable packages."""
from pathlib import Path
import json
import sys


def main():
    source, target = map(Path, sys.argv[1:3])
    if source.stat().st_size > 128*1024*1024:
        raise ValueError('PDF too large')
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
        resource.setrlimit(resource.RLIMIT_FSIZE, (20*1024*1024, 20*1024*1024))
        resource.setrlimit(resource.RLIMIT_AS, (1024*1024*1024, 1024*1024*1024))
    except ImportError:
        pass
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from pypdf import PdfReader
    with source.open('rb') as file:
        reader = PdfReader(file, strict=False)
        if reader.is_encrypted:
            raise ValueError('Encrypted PDF not supported')
        if len(reader.pages) > 2000:
            raise ValueError('Too many pages')
        size = 2
        with target.open('w', encoding='utf-8') as out:
            out.write('[')
            first = True
            for i, page in enumerate(reader.pages):
                text = page.extract_text() or ''
                if not text.strip():
                    continue
                row = json.dumps([f'Pagina {i+1}', text], ensure_ascii=False)
                size += len(row.encode('utf-8')) + 1
                if size > 16*1024*1024:
                    raise ValueError('Extracted text too large')
                out.write(('' if first else ',') + row)
                first = False
            out.write(']')


if __name__ == '__main__':
    main()
