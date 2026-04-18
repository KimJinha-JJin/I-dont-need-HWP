"""
HWP 5.0 binary file parser.

HWP 5.0 files use OLE Compound Document format. Body text is stored as
zlib-compressed record streams. Each record has a 4-byte header encoding
tag ID, nesting level, and payload size.
"""

import struct
import zlib
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional
import olefile


# ---------------------------------------------------------------------------
# HWP record tag IDs (HWPTAG_BEGIN = 16)
# ---------------------------------------------------------------------------
HWPTAG_BEGIN = 16

# BodyText record tags
TAG_PARA_HEADER     = HWPTAG_BEGIN + 50   # 66  0x42
TAG_PARA_TEXT       = HWPTAG_BEGIN + 51   # 67  0x43
TAG_PARA_CHAR_SHAPE = HWPTAG_BEGIN + 52   # 68  0x44
TAG_PARA_LINE_SEG   = HWPTAG_BEGIN + 53   # 69  0x45
TAG_CTRL_HEADER     = HWPTAG_BEGIN + 54   # 70  0x46
TAG_LIST_HEADER     = HWPTAG_BEGIN + 55   # 71  0x47
TAG_PAGE_DEF        = HWPTAG_BEGIN + 56   # 72  0x48
TAG_FOOTNOTE_SHAPE  = HWPTAG_BEGIN + 57   # 73
TAG_PAGE_BORDER_FILL = HWPTAG_BEGIN + 58  # 74
TAG_SHAPE_COMPONENT = HWPTAG_BEGIN + 59   # 75
TAG_TABLE           = HWPTAG_BEGIN + 60   # 76  0x4C
TAG_PARA_NUM        = HWPTAG_BEGIN + 62   # 78

# DocInfo record tags
TAG_DOCUMENT_PROPERTIES = HWPTAG_BEGIN + 0   # 16
TAG_ID_MAPPINGS         = HWPTAG_BEGIN + 1   # 17
TAG_BIN_DATA            = HWPTAG_BEGIN + 2   # 18
TAG_FACE_NAME           = HWPTAG_BEGIN + 3   # 19
TAG_BORDER_FILL         = HWPTAG_BEGIN + 4   # 20
TAG_CHAR_SHAPE          = HWPTAG_BEGIN + 5   # 21
TAG_TAB_DEF             = HWPTAG_BEGIN + 6   # 22
TAG_NUMBERING           = HWPTAG_BEGIN + 7   # 23
TAG_BULLET              = HWPTAG_BEGIN + 8   # 24
TAG_PARA_SHAPE          = HWPTAG_BEGIN + 9   # 25
TAG_STYLE               = HWPTAG_BEGIN + 10  # 26

# Inline control character codes (in paragraph text words)
# Chars 0x01-0x1F that are NOT 0x09/0x0A/0x0D are inline objects
# Each inline object = 1 control word + 7 extra words = 16 bytes total
INLINE_CTRL_EXTRA_WORDS = 7
SPECIAL_CTRL_TAB        = 0x09
SPECIAL_CTRL_LINE_BREAK = 0x0A
SPECIAL_CTRL_PARA_BREAK = 0x0D
CTRL_TABLE              = 0x1D  # Inline table placeholder


# ---------------------------------------------------------------------------
# Low-level record reader
# ---------------------------------------------------------------------------

@dataclass
class Record:
    tag: int
    level: int
    data: bytes


def _read_record(buf: bytes, offset: int):
    """Return (Record, new_offset) or (None, offset) at end of buffer."""
    if offset + 4 > len(buf):
        return None, offset

    header = struct.unpack_from('<I', buf, offset)[0]
    tag_id = header & 0x3FF
    level  = (header >> 10) & 0xF
    size   = (header >> 14) & 0xFFF
    offset += 4

    if size == 0xFFF:
        if offset + 4 > len(buf):
            return None, offset
        size = struct.unpack_from('<I', buf, offset)[0]
        offset += 4

    payload = buf[offset:offset + size]
    offset += size
    return Record(tag_id, level, payload), offset


def iter_records(buf: bytes) -> Iterator[Record]:
    offset = 0
    while offset < len(buf):
        rec, offset = _read_record(buf, offset)
        if rec is None:
            break
        yield rec


# ---------------------------------------------------------------------------
# FileHeader parsing
# ---------------------------------------------------------------------------

FILE_HEADER_SIGNATURE = b'HWP Document File\x00'

@dataclass
class FileHeader:
    version: tuple        # (major, minor, micro, build)
    compressed: bool
    encrypted: bool
    distribution: bool
    has_script: bool
    drm: bool
    xml_template: bool
    has_history: bool


def _parse_file_header(data: bytes) -> FileHeader:
    # Signature: 32 bytes, Version: 4 bytes (each 1 byte: build, micro, minor, major)
    # Wait: stored as little-endian DWORD so bytes are build, micro, minor, major
    if len(data) < 40:
        raise ValueError('FileHeader too short')

    sig = data[:len(FILE_HEADER_SIGNATURE)]
    if not sig.startswith(b'HWP Document File'):
        raise ValueError(f'Not a valid HWP file (bad signature)')

    # Version is stored at offset 32, 4 bytes
    ver_bytes = data[32:36]
    ver = (ver_bytes[3], ver_bytes[2], ver_bytes[1], ver_bytes[0])  # major.minor.micro.build

    # Flags DWORD at offset 36
    flags = struct.unpack_from('<I', data, 36)[0]

    return FileHeader(
        version=ver,
        compressed=bool(flags & (1 << 0)),
        encrypted=bool(flags & (1 << 1)),
        distribution=bool(flags & (1 << 2)),
        has_script=bool(flags & (1 << 3)),
        drm=bool(flags & (1 << 4)),
        xml_template=bool(flags & (1 << 5)),
        has_history=bool(flags & (1 << 6)),
    )


# ---------------------------------------------------------------------------
# Paragraph text extraction
# ---------------------------------------------------------------------------

def _extract_para_text(data: bytes) -> str:
    """
    Parse a HWPTAG_PARA_TEXT payload.

    Characters are UTF-16LE words. Control chars (0x01-0x1F) that are not
    tab/newline are inline objects occupying 8 words total (1 ctrl + 7 extra).
    """
    chars = []
    i = 0
    while i + 1 < len(data):
        code = struct.unpack_from('<H', data, i)[0]
        i += 2

        if code == SPECIAL_CTRL_PARA_BREAK:
            chars.append('\n')
        elif code == SPECIAL_CTRL_LINE_BREAK:
            chars.append('\n')
        elif code == SPECIAL_CTRL_TAB:
            chars.append('\t')
        elif 0x01 <= code <= 0x1F:
            # Inline object: skip the 7 remaining extra words
            i += INLINE_CTRL_EXTRA_WORDS * 2
        else:
            chars.append(chr(code))

    return ''.join(chars)


# ---------------------------------------------------------------------------
# Style name extraction from DocInfo
# ---------------------------------------------------------------------------

def _parse_styles(doc_info_buf: bytes) -> dict:
    """Return {style_index: style_name} from DocInfo records."""
    styles = {}
    idx = 0
    for rec in iter_records(doc_info_buf):
        if rec.tag == TAG_STYLE:
            # Style record: LocalName (Pascal-style length-prefixed UTF-16LE string)
            # at offset 0: WORD name_len, then name_len*2 bytes for name
            # then WORD eng_name_len, eng_name
            if len(rec.data) >= 2:
                name_len = struct.unpack_from('<H', rec.data, 0)[0]
                name_end = 2 + name_len * 2
                if name_end <= len(rec.data):
                    name = rec.data[2:name_end].decode('utf-16-le', errors='replace')
                    styles[idx] = name
            idx += 1
    return styles


# ---------------------------------------------------------------------------
# Para header — carries the style index
# ---------------------------------------------------------------------------

def _para_style_index(para_header_data: bytes) -> int:
    """Extract style index from HWPTAG_PARA_HEADER payload."""
    # offset 0: WORD instId (chars in para)
    # offset 2: WORD charShapeCount
    # offset 4: WORD rangeTagCount
    # offset 6: WORD lineCount
    # offset 8: WORD styleIndex (lower 8 bits)
    if len(para_header_data) >= 10:
        style_byte = para_header_data[9]  # high byte has heading level etc.
        style_index = para_header_data[8]  # low byte is style index
        return style_index
    return 0


# ---------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------

@dataclass
class Cell:
    row: int
    col: int
    text: str


@dataclass
class Table:
    rows: int
    cols: int
    cells: List[Cell] = field(default_factory=list)

    def to_markdown(self) -> str:
        if not self.cells:
            return ''

        grid: dict = {}
        for c in self.cells:
            grid[(c.row, c.col)] = c.text.replace('\n', ' ').strip()

        lines = []
        for r in range(self.rows):
            row_cells = [grid.get((r, c), '') for c in range(self.cols)]
            lines.append('| ' + ' | '.join(row_cells) + ' |')
            if r == 0:
                lines.append('| ' + ' | '.join(['---'] * self.cols) + ' |')

        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------

@dataclass
class Paragraph:
    text: str
    style_name: str = ''


@dataclass
class HwpDocument:
    version: tuple
    paragraphs: List[Paragraph]
    tables: List[Table]

    # Heading tag names used in Korean docs
    _HEADING_STYLES = {
        '제목',         # 제목 (Title)
        '개요 1',       # Outline 1
        '개요 2',       # Outline 2
        '개요 3',       # Outline 3
        '개요 4',
        '개요 5',
        '개요 6',
        '개요 7',
        '소제목',       # Sub-title
        'Heading 1',
        'Heading 2',
        'Heading 3',
    }

    def to_text(self) -> str:
        return '\n'.join(p.text for p in self.paragraphs if p.text.strip())

    def to_markdown(self) -> str:
        lines = []
        for p in self.paragraphs:
            text = p.text.strip()
            if not text:
                continue
            style = p.style_name

            # Map style names to markdown headings
            if style == '제목' or style == 'Title':
                lines.append(f'# {text}')
            elif style in ('개요 1', 'Heading 1'):
                lines.append(f'## {text}')
            elif style in ('개요 2', 'Heading 2'):
                lines.append(f'### {text}')
            elif style in ('개요 3', 'Heading 3'):
                lines.append(f'#### {text}')
            elif style in ('소제목',):
                lines.append(f'## {text}')
            else:
                lines.append(text)

        return '\n\n'.join(lines)

    def to_json(self) -> dict:
        return {
            'version': '.'.join(str(v) for v in self.version),
            'paragraphs': [
                {'text': p.text, 'style': p.style_name}
                for p in self.paragraphs
            ],
            'tables': [
                {
                    'rows': t.rows,
                    'cols': t.cols,
                    'cells': [
                        {'row': c.row, 'col': c.col, 'text': c.text}
                        for c in t.cells
                    ],
                }
                for t in self.tables
            ],
        }


# ---------------------------------------------------------------------------
# Section parser (BodyText/Section*)
# ---------------------------------------------------------------------------

def _parse_section(buf: bytes, styles: dict) -> tuple:
    """
    Parse a decompressed section buffer.
    Returns (paragraphs, tables).
    """
    paragraphs: List[Paragraph] = []
    tables: List[Table] = []

    current_style_idx = 0
    current_table: Optional[Table] = None
    table_row = 0
    table_col = 0
    inside_table_cell = False

    records = list(iter_records(buf))
    i = 0

    while i < len(records):
        rec = records[i]

        if rec.tag == TAG_PARA_HEADER:
            current_style_idx = _para_style_index(rec.data)

        elif rec.tag == TAG_PARA_TEXT:
            text = _extract_para_text(rec.data)
            style_name = styles.get(current_style_idx, '')
            if inside_table_cell and current_table is not None:
                # Append to current table cell
                current_table.cells[-1].text += text
            else:
                paragraphs.append(Paragraph(text=text, style_name=style_name))

        elif rec.tag == TAG_TABLE:
            # Table record: offset 0 DWORD flags, offset 4 WORD rows, offset 6 WORD cols
            if len(rec.data) >= 8:
                rows = struct.unpack_from('<H', rec.data, 4)[0]
                cols = struct.unpack_from('<H', rec.data, 6)[0]
                current_table = Table(rows=rows, cols=cols)
                tables.append(current_table)
                table_row = -1
                table_col = -1
                inside_table_cell = False

        elif rec.tag == TAG_LIST_HEADER:
            # List header marks the start of a table cell list
            if current_table is not None:
                table_col += 1
                if table_col >= current_table.cols:
                    table_col = 0
                    table_row += 1
                current_table.cells.append(Cell(row=table_row, col=table_col, text=''))
                inside_table_cell = True

        i += 1

    return paragraphs, tables


# ---------------------------------------------------------------------------
# HWPX (XML-based HWP) support
# ---------------------------------------------------------------------------

def _parse_hwpx(path: Path) -> HwpDocument:
    """Parse HWPX format (ZIP with XML files)."""
    import zipfile
    from xml.etree import ElementTree as ET

    paragraphs = []
    tables = []

    # HWPX namespace
    NS = {
        'hh': 'http://www.hancom.co.kr/hwpml/2011/paragraph',
        'hp': 'http://www.hancom.co.kr/hwpml/2011/paragraph',
        'hs': 'http://www.hancom.co.kr/hwpml/2011/section',
        'ha': 'http://www.hancom.co.kr/hwpml/2011/hh',
    }

    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        # Body section files follow the pattern Contents/section*.xml
        section_files = sorted(
            n for n in names
            if n.startswith('Contents/') and n.endswith('.xml') and 'section' in n.lower()
        )

        for sf in section_files:
            xml_data = zf.read(sf)
            try:
                root = ET.fromstring(xml_data)
            except ET.ParseError:
                continue

            # Extract all text nodes
            for elem in root.iter():
                if elem.tag.endswith('}t') or elem.tag == 't':
                    text = (elem.text or '') + (elem.tail or '')
                    if text.strip():
                        paragraphs.append(Paragraph(text=text, style_name=''))
                elif elem.tag.endswith('}run') or elem.tag.endswith('}Run'):
                    pass  # text already captured via 't' children

    return HwpDocument(version=(0, 0, 0, 0), paragraphs=paragraphs, tables=tables)


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

class HwpParseError(Exception):
    pass


def parse(filepath) -> HwpDocument:
    """
    Parse an HWP or HWPX file and return an HwpDocument.

    Supports:
    - HWP 5.0 (OLE binary, compressed or uncompressed)
    - HWPX (ZIP/XML)
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f'File not found: {path}')

    # HWPX detection: it's a ZIP file
    with open(path, 'rb') as f:
        magic = f.read(4)

    if magic == b'PK\x03\x04':
        return _parse_hwpx(path)

    # HWP 5.0 (OLE)
    if not olefile.isOleFile(str(path)):
        raise HwpParseError(f'Not a valid HWP/HWPX file: {path}')

    ole = olefile.OleFileIO(str(path))
    try:
        return _parse_hwp5(ole, path)
    finally:
        ole.close()


def _parse_hwp5(ole: olefile.OleFileIO, path: Path) -> HwpDocument:
    # ---- FileHeader ----
    if not ole.exists('FileHeader'):
        raise HwpParseError('Missing FileHeader stream')

    header_data = ole.openstream('FileHeader').read()
    try:
        file_header = _parse_file_header(header_data)
    except ValueError as e:
        raise HwpParseError(str(e))

    if file_header.encrypted:
        raise HwpParseError('Encrypted HWP files are not supported')

    compressed = file_header.compressed

    # ---- DocInfo → styles ----
    styles: dict = {}
    if ole.exists('DocInfo'):
        doc_info_raw = ole.openstream('DocInfo').read()
        if compressed:
            try:
                doc_info_raw = zlib.decompress(doc_info_raw, -15)
            except zlib.error:
                pass  # try uncompressed
        styles = _parse_styles(doc_info_raw)

    # ---- BodyText sections ----
    all_paragraphs: List[Paragraph] = []
    all_tables: List[Table] = []

    section_num = 0
    while ole.exists(f'BodyText/Section{section_num}'):
        raw = ole.openstream(f'BodyText/Section{section_num}').read()
        if compressed:
            try:
                raw = zlib.decompress(raw, -15)
            except zlib.error:
                pass
        paras, tables = _parse_section(raw, styles)
        all_paragraphs.extend(paras)
        all_tables.extend(tables)
        section_num += 1

    # ---- Fallback: use PrvText if no body text was found ----
    if not all_paragraphs and ole.exists('PrvText'):
        prv = ole.openstream('PrvText').read()
        text = prv.decode('utf-16-le', errors='replace')
        for line in text.splitlines():
            if line.strip():
                all_paragraphs.append(Paragraph(text=line, style_name=''))

    return HwpDocument(
        version=file_header.version,
        paragraphs=all_paragraphs,
        tables=all_tables,
    )
