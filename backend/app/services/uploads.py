"""Upload validation (by content, not extension) and malware-scan integration."""
import io
import socket
import struct
import zipfile
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from ..config import settings

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
# Active/embedded content in a CV PDF is never legitimate for our purposes.
_PDF_ACTIVE = (b"/JavaScript", b"/JS ", b"/Launch", b"/EmbeddedFile", b"/OpenAction", b"/AA ")


class UploadRejected(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code, self.message = status_code, message


@dataclass
class Validated:
    kind: str  # pdf | docx
    mime: str


def sniff(data: bytes) -> str | None:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
            if "[Content_Types].xml" in names and "word/document.xml" in names:
                return "docx"
        except zipfile.BadZipFile:
            return None
    return None


def validate(filename: str, data: bytes) -> Validated:
    if not data:
        raise UploadRejected(400, "Empty file")
    if len(data) > settings.max_upload_bytes:
        raise UploadRejected(413, f"File exceeds the {settings.max_upload_bytes} byte limit")
    kind = sniff(data)
    if kind is None or kind not in settings.allowed_upload_types:
        raise UploadRejected(415, "Unsupported file content; only PDF and DOCX are accepted")
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext != kind:
        raise UploadRejected(415, "File extension does not match the file's actual content")
    if kind == "pdf":
        _check_pdf(data)
    else:
        _check_docx(data)
    return Validated(kind, MIME[kind])


def _check_pdf(data: bytes) -> None:
    if any(marker in data for marker in _PDF_ACTIVE):
        raise UploadRejected(422, "PDF contains active or embedded content and was rejected")
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise UploadRejected(422, "Encrypted PDFs are not supported")
        if len(reader.pages) > settings.max_pdf_pages:
            raise UploadRejected(422, f"PDF has more than {settings.max_pdf_pages} pages")
    except UploadRejected:
        raise
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError):
        raise UploadRejected(422, "PDF is malformed or unreadable")


def _check_docx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if len(infos) > 2000 or sum(i.file_size for i in infos) > settings.max_docx_uncompressed_bytes:
                raise UploadRejected(422, "DOCX expands to an unreasonable size and was rejected")
            if any(i.filename.startswith("word/vbaProject") or i.filename.endswith(".bin") and "embeddings" in i.filename
                   for i in infos):
                raise UploadRejected(422, "DOCX contains macros or embedded objects and was rejected")
    except zipfile.BadZipFile:
        raise UploadRejected(422, "DOCX is malformed")


# ---- malware scanning -------------------------------------------------------------------------

def scanner_configured() -> bool:
    return bool(settings.clamav_host)


def scan(data: bytes) -> str:
    """Returns 'clean', 'not_configured' or 'error'; raises UploadRejected if malware is found.

    'not_configured' means NO scan took place. Production config refuses to start in that state
    unless JOBHUNTER_ALLOW_UNSCANNED_UPLOADS=true is set deliberately.
    """
    if not scanner_configured():
        if settings.require_malware_scan:
            raise UploadRejected(503, "Malware scanning is required but not configured")
        return "not_configured"
    try:
        reply = _clamd_instream(data)
    except OSError:
        if settings.require_malware_scan or settings.env == "production":
            raise UploadRejected(503, "Malware scanner unavailable; upload refused")
        return "error"
    if reply.endswith("OK"):
        return "clean"
    if "FOUND" in reply:
        raise UploadRejected(422, "File rejected by malware scanner")
    raise UploadRejected(503, "Malware scanner returned an unexpected response")


def _clamd_instream(data: bytes) -> str:
    with socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=10) as s:
        s.sendall(b"zINSTREAM\0")
        for i in range(0, len(data), 8192):
            chunk = data[i:i + 8192]
            s.sendall(struct.pack("!I", len(chunk)) + chunk)
        s.sendall(struct.pack("!I", 0))
        buf = b""
        while not buf.endswith(b"\0") and (part := s.recv(4096)):
            buf += part
    return buf.rstrip(b"\0").decode(errors="replace").strip()
