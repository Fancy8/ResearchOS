"""Isolated PDF parser entry point; stdout is structured JSON only."""

import json
import sys
from pathlib import Path

from pypdf import PdfReader

PARSER_VERSION = "pypdf-6.20.1-anchor-v1"


def parse(path, max_pages):
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise ValueError("ENCRYPTED_PDF")
    if not 0 < len(reader.pages) <= max_pages:
        raise ValueError("PAGE_LIMIT_EXCEEDED")
    pages = []
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        if len(text) > 2_000_000:
            raise ValueError("PAGE_TEXT_TOO_LARGE")
        pages.append(
            {
                "page_number": number,
                "text_content": text,
                "layout_data": {
                    "parser_version": PARSER_VERSION,
                    "cropbox": [float(value) for value in page.cropbox],
                    "rotation": page.rotation,
                },
            }
        )
    return {
        "page_count": len(pages),
        "has_text_layer": any(item["text_content"].strip() for item in pages),
        "parser_version": PARSER_VERSION,
        "pages": pages,
    }


if __name__ == "__main__":
    try:
        source = Path(sys.argv[1]).resolve()
        permitted = (
            Path(sys.prefix).resolve(),
            Path(sys.base_prefix).resolve(),
            Path(__file__).resolve().parents[2],
        )

        def audit(event, args):
            if event in {"socket.connect", "socket.bind", "subprocess.Popen", "os.system"}:
                raise PermissionError("PARSER_NETWORK_OR_PROCESS_FORBIDDEN")
            if event == "open" and isinstance(args[0], (str, bytes)):
                target = Path(args[0]).resolve()
                if target != source and not any(target.is_relative_to(base) for base in permitted):
                    raise PermissionError("PARSER_FILE_ACCESS_FORBIDDEN")

        sys.addaudithook(audit)
        result = parse(source, int(sys.argv[2]))
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    except Exception as error:
        allowed = {"ENCRYPTED_PDF", "PAGE_LIMIT_EXCEEDED", "PAGE_TEXT_TOO_LARGE"}
        code = str(error) if isinstance(error, ValueError) and str(error) in allowed else "INVALID_PDF"
        print(json.dumps({"ok": False, "error_code": code}))
        sys.exit(1)
