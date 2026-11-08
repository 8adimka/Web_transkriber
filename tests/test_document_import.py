"""Synthetic document parsing tests; no providers, filesystem extraction or DB.

    python -m unittest discover -s tests -p test_document_import.py -v
"""

from io import BytesIO
import stat
import struct
import unittest
from unittest.mock import patch
import zipfile

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend.services.transcriber.app import document_import as documents


def archive(files, compression=zipfile.ZIP_DEFLATED):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as result:
        for name, content in files.items():
            result.writestr(name, content)
    return output.getvalue()


def epub(*, spine=None, chapters=None, extra=None):
    spine = spine if spine is not None else ['second', 'first']
    chapters = chapters if chapters is not None else {
        'first': '<html><head><title>Chapter one</title></head><body><h1>First chapter</h1><p>Hello <em>world</em>.</p></body></html>',
        'second': '<html><body><h1>Second chapter</h1><p>Read me first.</p></body></html>',
    }
    files = {
        'mimetype': 'application/epub+zip',
        'META-INF/container.xml': '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
        'OPS/book.opf': '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Reader test book</dc:title></metadata><manifest>' +
            ''.join(f'<item id="{name}" href="chapters/{name}.xhtml" media-type="application/xhtml+xml"/>' for name in chapters) + '</manifest><spine>' +
            ''.join(f'<itemref idref="{name}"/>' for name in spine) + '</spine></package>',
    }
    for name, content in chapters.items():
        files[f'OPS/chapters/{name}.xhtml'] = content
    files.update(extra or {})
    return archive(files)


def pdf(text=None, *, encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    if text is not None:
        font = DictionaryObject({
            NameObject('/Type'): NameObject('/Font'),
            NameObject('/Subtype'): NameObject('/Type1'),
            NameObject('/BaseFont'): NameObject('/Helvetica'),
        })
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        stream.set_data(f'BT /F1 12 Tf 72 700 Td ({escaped}) Tj ET'.encode())
        page[NameObject('/Contents')] = stream
    writer.add_metadata({'/Title': 'Synthetic PDF'})
    if encrypted:
        writer.encrypt('synthetic-password')
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class DocumentImportTests(unittest.TestCase):
    def assertCode(self, code, data, filename):
        with self.assertRaises(documents.DocumentImportError) as error:
            documents.extract_document(data, filename)
        self.assertEqual(error.exception.code, code)
        self.assertTrue(error.exception.message)

    def test_utf8_text_preserves_paragraphs_and_literal_html_as_text(self):
        result = documents.extract_document('Hello world.\r\n\r\n<script>plain text</script> Привет!'.encode(), 'meeting.txt')
        self.assertEqual(result['title'], 'meeting')
        self.assertEqual(result['content'], 'Hello world.\n\n<script>plain text</script> Привет!')

    def test_bom_encodings_and_windows_cyrillic(self):
        for encoding in ['utf-8-sig', 'utf-16', 'utf-32', 'cp1251']:
            with self.subTest(encoding=encoding):
                result = documents.extract_document('Привет, читатель!'.encode(encoding), 'Книга.TXT')
                self.assertEqual(result['content'], 'Привет, читатель!')
                self.assertEqual(result['title'], 'Книга')

    def test_bomless_utf16_text(self):
        for encoding in ['utf-16-le', 'utf-16-be']:
            with self.subTest(encoding=encoding):
                self.assertEqual(documents.extract_document('Hello reader'.encode(encoding), 'test.txt')['content'], 'Hello reader')

    def test_markdown_has_readable_titles_and_link_labels_without_remote_resources(self):
        result = documents.extract_document(b'# A book\n\nA **short** [story](https://example.invalid).\n\n```python\nprint("hello")\n```', 'book.md')
        self.assertEqual(result['title'], 'A book')
        self.assertIn('A short story.', result['content'])
        self.assertIn('print("hello")', result['content'])
        self.assertNotIn('https://', result['content'])

    def test_html_omits_active_hidden_and_head_content(self):
        data = b'<html><head><title>Reader &amp; books</title><style>hidden style</style></head><body><h1>Chapter</h1><p>Some <strong>words</strong> &amp; text.</p><script>fetch("https://example.invalid")</script><div hidden>hidden content</div><iframe src="https://example.invalid">remote</iframe><p>End.</p></body></html>'
        result = documents.extract_document(data, 'book.html')
        self.assertEqual(result['title'], 'Reader & books')
        self.assertEqual(result['content'], 'Chapter\n\nSome words & text.\n\nEnd.')

    def test_fb2_title_inline_text_poems_and_notes(self):
        data = '''<?xml version="1.0" encoding="utf-8"?><FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"><description><title-info><book-title>Тестовая книга</book-title><annotation><p>Not body</p></annotation></title-info></description><body><section><title><p>Глава первая</p></title><p>Привет <emphasis>мир</emphasis>!</p><poem><stanza><v>Строка стиха</v></stanza></poem></section></body><body name="notes"><section><p>Примечание</p></section></body><binary>Not text</binary></FictionBook>'''.encode()
        result = documents.extract_document(data, 'test.fb2')
        self.assertEqual(result['title'], 'Тестовая книга')
        self.assertEqual(result['content'], 'Глава первая\n\nПривет мир!\n\nСтрока стиха\n\nПримечание')

    def test_fb2_xml_declared_cp1251(self):
        data = '<?xml version="1.0" encoding="windows-1251"?><FictionBook><body><p>Кириллица</p></body></FictionBook>'.encode('cp1251')
        self.assertEqual(documents.extract_document(data, 'cyrillic.fb2')['content'], 'Кириллица')

    def test_xml_entities_are_rejected_before_expansion(self):
        for entity in ['<!ENTITY a "boom">', '<!ENTITY a SYSTEM "file:///etc/passwd">']:
            with self.subTest(entity=entity):
                self.assertCode('unsafe_document', f'<!DOCTYPE FictionBook [{entity}]><FictionBook><body><p>&a;</p></body></FictionBook>'.encode(), 'unsafe.fb2')

    def test_malformed_or_wrong_xml_is_rejected(self):
        self.assertCode('invalid_document', b'<FictionBook><body>', 'broken.fb2')
        self.assertCode('invalid_document', b'<not-a-book><p>Hello</p></not-a-book>', 'wrong.fb2')

    def test_epub_uses_spine_order_and_metadata_title(self):
        result = documents.extract_document(epub(), 'book.epub')
        self.assertEqual(result['title'], 'Reader test book')
        self.assertLess(result['content'].index('Second chapter'), result['content'].index('First chapter'))
        self.assertIn('Hello world.', result['content'])
        self.assertNotIn('Chapter one', result['content'])

    def test_epub_spine_and_members_must_exist(self):
        self.assertCode('invalid_document', epub(spine=[]), 'bad.epub')
        self.assertCode('invalid_document', epub(spine=['missing']), 'bad.epub')
        self.assertCode('invalid_document', archive({'mimetype': 'application/epub+zip'}), 'bad.epub')

    def test_epub_reference_can_use_valid_parent_directory_inside_archive(self):
        data = archive({
            'META-INF/container.xml': '<container><rootfiles><rootfile full-path="OPS/meta/book.opf"/></rootfiles></container>',
            'OPS/meta/book.opf': '<package><manifest><item id="one" href="../chapter%201.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/></spine></package>',
            'OPS/chapter 1.xhtml': '<html><body><p>One chapter</p></body></html>',
        })
        self.assertEqual(documents.extract_document(data, 'book.epub')['content'], 'One chapter')

    def test_epub_external_reference_and_archive_escape_are_rejected(self):
        for href in ['https://example.invalid/chapter.xhtml', '../../outside.xhtml', '/absolute.xhtml']:
            data = archive({
                'META-INF/container.xml': '<container><rootfiles><rootfile full-path="OPS/book.opf"/></rootfiles></container>',
                'OPS/book.opf': f'<package><manifest><item id="one" href="{href}" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="one"/></spine></package>',
            })
            with self.subTest(href=href):
                self.assertCode('unsafe_document', data, 'book.epub')

    def test_epub_drm_is_rejected_but_standard_font_obfuscation_is_allowed(self):
        template = '<encryption><EncryptedData><EncryptionMethod Algorithm="{}"/></EncryptedData></encryption>'
        self.assertCode('encrypted_document', epub(extra={'META-INF/encryption.xml': template.format('https://example.invalid/drm')}), 'book.epub')
        allowed = epub(extra={'META-INF/encryption.xml': template.format('http://www.idpf.org/2008/embedding')})
        self.assertIn('First chapter', documents.extract_document(allowed, 'book.epub')['content'])

    def test_docx_includes_paragraphs_tables_and_metadata(self):
        data = archive({
            'word/document.xml': '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello</w:t><w:tab/><w:t>reader.</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Cell one</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Cell two</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>',
            'docProps/core.xml': '<cp:coreProperties xmlns:cp="urn:properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Office notes</dc:title></cp:coreProperties>',
            'word/_rels/document.xml.rels': '<Relationships><Relationship Target="https://example.invalid/external" TargetMode="External"/></Relationships>',
        })
        result = documents.extract_document(data, 'notes.docx')
        self.assertEqual(result['title'], 'Office notes')
        self.assertEqual(result['content'], 'Hello reader.\n\nCell one\n\nCell two')

    def test_archive_path_traversal_and_symlinks_are_rejected(self):
        for name in ['../outside.xml', '/absolute.xml', 'C:/file.xml', 'folder\\file.xml']:
            with self.subTest(name=name):
                self.assertCode('unsafe_document', archive({name: 'x'}), 'unsafe.docx')
        output = BytesIO()
        with zipfile.ZipFile(output, 'w') as result:
            info = zipfile.ZipInfo('word/document.xml')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            result.writestr(info, '../../outside')
        self.assertCode('unsafe_document', output.getvalue(), 'unsafe.docx')

    def test_archive_duplicate_names_are_rejected(self):
        output = BytesIO()
        with zipfile.ZipFile(output, 'w') as result:
            result.writestr('word/document.xml', 'one')
            with self.assertWarns(UserWarning):
                result.writestr('word/document.xml', 'two')
        self.assertCode('unsafe_document', output.getvalue(), 'duplicate.docx')

    def test_archive_size_count_and_compression_limits(self):
        with patch.object(documents, 'MAX_ARCHIVE_BYTES', 128):
            self.assertCode('file_too_large', archive({'book.xml': 'x' * 129}), 'large.epub')
        with patch.object(documents, 'MAX_ARCHIVE_ENTRIES', 2):
            self.assertCode('file_too_large', archive({'a': '', 'b': '', 'c': ''}), 'many.epub')
        self.assertCode('unsafe_document', archive({'document.xml': 'x'}, zipfile.ZIP_BZIP2), 'compressed.docx')

    def test_encrypted_archive_flag_is_rejected(self):
        data = bytearray(archive({'word/document.xml': 'text'}))
        for signature, offset in [(b'PK\x03\x04', 6), (b'PK\x01\x02', 8)]:
            start = data.index(signature)
            flags = struct.unpack_from('<H', data, start + offset)[0]
            struct.pack_into('<H', data, start + offset, flags | 1)
        self.assertCode('encrypted_document', bytes(data), 'encrypted.docx')

    def test_pdf_extracts_real_text_layer(self):
        result = documents.extract_document(pdf('Hello PDF reader.'), 'test.pdf')
        self.assertEqual(result['title'], 'Synthetic PDF')
        self.assertIn('Hello PDF reader.', result['content'])

    def test_pdf_without_text_and_encrypted_pdf_have_specific_errors(self):
        self.assertCode('no_text_layer', pdf(), 'scan.pdf')
        self.assertCode('encrypted_document', pdf('Secret', encrypted=True), 'protected.pdf')

    def test_pdf_processing_limits_are_context_local(self):
        from pypdf import get_configuration
        before = get_configuration()
        documents.extract_document(pdf('Example text.'), 'test.pdf')
        self.assertIs(get_configuration(), before)
        with patch.object(documents, 'MAX_PDF_PAGES', 0):
            self.assertCode('file_too_large', pdf('Example'), 'too-many-pages.pdf')
        self.assertIs(get_configuration(), before)

    def test_empty_unsupported_binary_and_malformed_documents_are_rejected(self):
        self.assertCode('empty_document', b'', 'empty.txt')
        self.assertCode('empty_document', b'  \n\t ', 'blank.txt')
        self.assertCode('unsupported_format', b'data', 'book.mobi')
        self.assertCode('invalid_document', b'\x00\x01\x02\x00binary', 'binary.txt')
        self.assertCode('invalid_document', b'not a zip', 'broken.epub')
        self.assertCode('invalid_document', b'%PDF-1.7 broken', 'broken.pdf')

    def test_upload_and_extracted_text_limits_are_enforced(self):
        with patch.object(documents, 'MAX_UPLOAD_BYTES', 3):
            self.assertCode('file_too_large', b'four', 'size.txt')
        with patch.object(documents, 'MAX_TEXT_CHARS', 3):
            self.assertCode('text_too_large', b'four', 'size.txt')

    def test_filename_title_is_bounded_and_does_not_include_directory(self):
        result = documents.extract_document(b'Hello', '/some/folder/' + 'x' * 300 + '.txt')
        self.assertEqual(result['title'], 'x' * 240)
        self.assertNotIn('/', result['title'])


if __name__ == '__main__':
    unittest.main()
