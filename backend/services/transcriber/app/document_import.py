"""Bounded, in-memory conversion of supported documents to plain reader text.

No archive members are written to disk and no linked resources are loaded.
EPUB chapters follow the package spine, not ZIP filename order.
"""

from contextlib import contextmanager
from html.parser import HTMLParser
from io import BytesIO
import posixpath
import re
import stat
from typing import Iterator
from urllib.parse import unquote, urlsplit
import zipfile

from defusedxml import ElementTree as SafeXML
from defusedxml.common import DefusedXmlException
from xml.etree.ElementTree import ParseError


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 5_000_000
MAX_ARCHIVE_BYTES = 40 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 1000
MAX_PDF_PAGES = 2000
SUPPORTED_EXTENSIONS = frozenset({
    ".txt", ".text", ".fb2", ".epub", ".docx", ".pdf", ".md", ".markdown", ".html", ".htm"
})


class DocumentImportError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _fail(code: str, message: str):
    raise DocumentImportError(code, message)


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = text.replace("\ufeff", "").replace("\u00ad", "")
    if "\x00" in text:
        _fail("invalid_document", "The document contains binary data instead of readable text.")
    controls = sum(ord(char) < 32 and char not in "\n\t\f" for char in text)
    if controls > max(2, len(text) // 100):
        _fail("invalid_document", "The document contains binary data instead of readable text.")
    text = re.sub(r"[\x01-\x08\x0b\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_TEXT_CHARS:
        _fail("text_too_large", "The extracted text exceeds the reader size limit.")
    return text


def _title(value: str | None, filename: str) -> str:
    fallback = filename.replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    title = re.sub(r"\s+", " ", value or "").strip()
    title = re.sub(r"[\x00-\x1f\x7f]", "", title)
    fallback = re.sub(r"[\x00-\x1f\x7f]", "", fallback)
    return (title or fallback or "Untitled text")[:240]


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        encodings = ["utf-32"]
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ["utf-16"]
    elif b"\x00" in data[:512]:
        sample = data[:512]
        # Common BOM-less UTF-16 text. Random binary remains an explicit error.
        odd_zeroes = sample[1::2].count(0)
        even_zeroes = sample[0::2].count(0)
        if odd_zeroes > len(sample) // 8 and even_zeroes == 0:
            encodings = ["utf-16-le"]
        elif even_zeroes > len(sample) // 8 and odd_zeroes == 0:
            encodings = ["utf-16-be"]
        else:
            _fail("invalid_document", "The file is not a supported text document.")
    else:
        encodings = ["utf-8-sig", "cp1251"]
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    _fail("unsupported_encoding", "The document encoding is not supported. Save it as UTF-8 and retry.")


def _xml(data: bytes):
    try:
        return SafeXML.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException:
        _fail("unsafe_document", "XML entities and external resources are not allowed.")
    except (ParseError, ValueError, LookupError):
        _fail("invalid_document", "The XML document is damaged or has an unsupported encoding.")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


class _HTMLText(HTMLParser):
    BLOCKS = frozenset({"p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "tr", "hr"})
    OMIT = frozenset({"script", "style", "template", "noscript", "iframe", "object", "svg"})
    VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []
        self.title_parts = []
        self.length = 0

    def _append(self, value: str):
        self.length += len(value)
        if self.length > MAX_TEXT_CHARS + 100_000:
            _fail("text_too_large", "The extracted text exceeds the reader size limit.")
        self.parts.append(value)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        omitted = bool(self.stack and self.stack[-1][1]) or tag in self.OMIT
        omitted = omitted or "hidden" in attributes or attributes.get("aria-hidden") == "true"
        if not omitted and tag in self.BLOCKS:
            self._append("\n\n")
        if tag not in self.VOID:
            self.stack.append((tag, omitted))
        elif not omitted and tag == "br":
            self._append("\n")
        elif not omitted and tag in {"td", "th"}:
            self._append("\t")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or not any(item[0] == tag for item in self.stack):
            return
        while self.stack:
            popped, omitted = self.stack.pop()
            if popped == tag:
                if not omitted and tag in self.BLOCKS:
                    self._append("\n\n")
                elif not omitted and tag in {"td", "th"}:
                    self._append("\t")
                return

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        if any(item[0] == "title" for item in self.stack):
            self.title_parts.append(data)
        elif not any(item[0] == "head" for item in self.stack):
            self._append(data)


def _html(data: bytes) -> dict:
    parser = _HTMLText()
    parser.feed(_decode(data))
    parser.close()
    return {"title": "".join(parser.title_parts), "content": "".join(parser.parts)}


def _markdown(data: bytes) -> dict:
    text = _decode(data)
    title = re.search(r"(?m)^#{1,2}\s+(.+?)\s*#*\s*$", text)
    text = re.sub(r"(?m)^\s*(```|~~~)[^\n]*$", "", text)
    text = re.sub(r"!\[([^\]]*)\]\([^\n)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^\n)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s{0,3}>\s?", "", text)
    text = re.sub(r"(`+)(.*?)\1", r"\2", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    return {"title": title.group(1) if title else "", "content": text}


def _fb2(data: bytes) -> dict:
    root = _xml(data)
    if _local(root.tag) != "FictionBook":
        _fail("invalid_document", "The file is not a FictionBook document.")
    title = next(("".join(node.itertext()) for node in root.iter() if _local(node.tag) == "book-title"), "")
    paragraphs = []
    for body in root:
        if _local(body.tag) != "body":
            continue
        # Binary covers/metadata never enter the reading text. Notes are retained.
        for node in body.iter():
            if _local(node.tag) in {"p", "v", "text-author", "subtitle"}:
                paragraphs.append("".join(node.itertext()))
    return {"title": title, "content": "\n\n".join(paragraphs)}


def _safe_path(name: str) -> str:
    if not name or "\\" in name or "\x00" in name or name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        _fail("unsafe_document", "The archive contains an unsafe file path.")
    if ".." in name.split("/"):
        _fail("unsafe_document", "The archive contains an unsafe file path.")
    return posixpath.normpath(name)


class _Archive:
    def __init__(self, data: bytes):
        self.archive = zipfile.ZipFile(BytesIO(data))
        entries = self.archive.infolist()
        if len(entries) > MAX_ARCHIVE_ENTRIES or sum(info.file_size for info in entries) > MAX_ARCHIVE_BYTES:
            self.archive.close()
            _fail("file_too_large", "The expanded archive exceeds the reader size limit.")
        self.members = {}
        try:
            for info in entries:
                name = _safe_path(info.orig_filename)
                if info.flag_bits & 1:
                    _fail("encrypted_document", "Encrypted archives are not supported.")
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    _fail("unsafe_document", "The archive uses unsupported compression.")
                if stat.S_ISLNK(info.external_attr >> 16):
                    _fail("unsafe_document", "Archive symbolic links are not supported.")
                if name in self.members:
                    _fail("unsafe_document", "The archive contains duplicate file paths.")
                self.members[name] = info
        except BaseException:
            self.archive.close()
            raise

    def read(self, name: str) -> bytes:
        name = _safe_path(name)
        if name not in self.members:
            _fail("invalid_document", "The document archive is missing required content.")
        with self.archive.open(self.members[name]) as member:
            value = member.read(MAX_ARCHIVE_BYTES + 1)
        if len(value) > MAX_ARCHIVE_BYTES:
            _fail("file_too_large", "The expanded archive exceeds the reader size limit.")
        return value

    def resolve(self, base: str, reference: str) -> str:
        uri = urlsplit(reference)
        if uri.scheme or uri.netloc or not uri.path:
            _fail("unsafe_document", "External document references are not supported.")
        path = unquote(uri.path)
        if path.startswith("/") or "\\" in path:
            _fail("unsafe_document", "The document reference points outside the archive.")
        return _safe_path(posixpath.normpath(posixpath.join(posixpath.dirname(base), path)))

    def close(self):
        self.archive.close()


@contextmanager
def _archive(data: bytes) -> Iterator[_Archive]:
    archive = _Archive(data)
    try:
        yield archive
    finally:
        archive.close()


def _epub(data: bytes) -> dict:
    with _archive(data) as archive:
        if "META-INF/encryption.xml" in archive.members:
            encryption = _xml(archive.read("META-INF/encryption.xml"))
            allowed_fonts = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}
            for node in encryption.iter():
                if _local(node.tag) == "EncryptionMethod" and node.get("Algorithm") not in allowed_fonts:
                    _fail("encrypted_document", "DRM-protected books are not supported.")
        container = _xml(archive.read("META-INF/container.xml"))
        package_name = next((node.get("full-path") for node in container.iter() if _local(node.tag) == "rootfile"), None)
        if not package_name:
            _fail("invalid_document", "The EPUB package is missing.")
        package_name = _safe_path(package_name)
        package = _xml(archive.read(package_name))
        if _local(package.tag) != "package":
            _fail("invalid_document", "The EPUB package is invalid.")
        title = next(("".join(node.itertext()) for node in package.iter() if _local(node.tag) == "title"), "")
        manifest = {node.get("id"): node for node in package.iter() if _local(node.tag) == "item"}
        spine = [node for node in package.iter() if _local(node.tag) == "itemref"]
        if not spine:
            _fail("invalid_document", "The EPUB reading order is missing.")
        parts = []
        length = 0
        for reference in spine:
            item = manifest.get(reference.get("idref"))
            if item is None or not item.get("href"):
                _fail("invalid_document", "An EPUB chapter is missing from its manifest.")
            if item.get("media-type") not in {"application/xhtml+xml", "text/html"}:
                _fail("unsupported_format", "This EPUB contains non-text chapters that cannot be displayed.")
            chapter = _html(archive.read(archive.resolve(package_name, item.get("href"))))["content"]
            length += len(chapter)
            if length > MAX_TEXT_CHARS:
                _fail("text_too_large", "The extracted text exceeds the reader size limit.")
            parts.append(chapter)
        return {"title": title, "content": "\n\n".join(parts)}


def _docx(data: bytes) -> dict:
    with _archive(data) as archive:
        root = _xml(archive.read("word/document.xml"))
        if _local(root.tag) != "document":
            _fail("invalid_document", "The Word document is invalid.")
        parts = []
        for paragraph in root.iter():
            if _local(paragraph.tag) != "p":
                continue
            text = []
            for node in paragraph.iter():
                kind = _local(node.tag)
                if kind == "t":
                    text.append(node.text or "")
                elif kind in {"br", "cr"}:
                    text.append("\n")
                elif kind == "tab":
                    text.append("\t")
            parts.append("".join(text))
        title = ""
        if "docProps/core.xml" in archive.members:
            core = _xml(archive.read("docProps/core.xml"))
            title = next(("".join(node.itertext()) for node in core.iter() if _local(node.tag) == "title"), "")
        return {"title": title, "content": "\n\n".join(parts)}


def _pdf(data: bytes) -> dict:
    from pypdf import PdfReader, apply_configuration
    from pypdf.errors import FileNotDecryptedError, LimitReachedError

    try:
        # Context-local limits do not change other requests. No PDF external tool
        # is used. See pypdf's Configuration and text-extraction documentation.
        with apply_configuration(
            maximum_declared_stream_length=MAX_ARCHIVE_BYTES,
            array_based_stream_maximum_output_length=MAX_ARCHIVE_BYTES,
            zlib_maximum_output_length=MAX_ARCHIVE_BYTES,
            lzw_maximum_output_length=MAX_ARCHIVE_BYTES,
            run_length_maximum_output_length=MAX_ARCHIVE_BYTES,
            stream_decoding_work_maximum_length=MAX_ARCHIVE_BYTES,
            stream_parsing_work_maximum_count=500_000,
            page_tree_maximum_entries=MAX_PDF_PAGES + 100,
            page_tree_maximum_depth=50,
            page_tree_maximum_page_entries=100_000,
            xform_maximum_invocations_per_extraction=500,
            jbig2dec_binary=None,
        ):
            reader = PdfReader(BytesIO(data), root_object_recovery_limit=1000, xref_stream_maximum_entries=200_000)
            if reader.is_encrypted:
                _fail("encrypted_document", "Password-protected PDFs are not supported.")
            if len(reader.pages) > MAX_PDF_PAGES:
                _fail("file_too_large", "The PDF contains too many pages.")
            parts = []
            length = 0
            decoded_length = 0
            for page in reader.pages:
                stream = page.get_contents()
                if stream is not None:
                    decoded_length += len(stream.get_data())
                    if decoded_length > MAX_ARCHIVE_BYTES:
                        _fail("file_too_large", "The expanded PDF exceeds the reader size limit.")
                content = page.extract_text() or ""
                length += len(content)
                if length > MAX_TEXT_CHARS:
                    _fail("text_too_large", "The extracted text exceeds the reader size limit.")
                parts.append(content)
            text = "\n\n".join(parts)
            if not text.strip():
                _fail("no_text_layer", "This PDF has no readable text layer. Scanned pages require OCR.")
            title = reader.metadata.title if reader.metadata else ""
            return {"title": title or "", "content": text}
    except FileNotDecryptedError:
        _fail("encrypted_document", "Password-protected PDFs are not supported.")
    except LimitReachedError:
        _fail("file_too_large", "The PDF exceeds the reader processing limits.")


def extract_document(data: bytes, filename: str) -> dict[str, str]:
    """Extract a document or raise a stable, localizable DocumentImportError."""
    if len(data) > MAX_UPLOAD_BYTES:
        _fail("file_too_large", "The file exceeds the 10 MiB upload limit.")
    if not data:
        _fail("empty_document", "The document is empty.")
    extension = posixpath.splitext(filename.lower())[1]
    if extension not in SUPPORTED_EXTENSIONS:
        _fail("unsupported_format", "This document format is not supported.")
    try:
        if extension in {".txt", ".text"}:
            result = {"title": "", "content": _decode(data)}
        elif extension in {".md", ".markdown"}:
            result = _markdown(data)
        elif extension in {".html", ".htm"}:
            result = _html(data)
        elif extension == ".fb2":
            result = _fb2(data)
        elif extension == ".epub":
            result = _epub(data)
        elif extension == ".docx":
            result = _docx(data)
        else:
            result = _pdf(data)
        content = _normalize(result["content"])
        if not content:
            _fail("empty_document", "The document contains no readable text.")
        return {"title": _title(result.get("title"), filename), "content": content}
    except DocumentImportError:
        raise
    except Exception as error:
        # Parser errors must not expose local paths, document contents or internals.
        raise DocumentImportError("invalid_document", "The document is damaged or cannot be read.") from error
