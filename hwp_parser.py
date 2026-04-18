"""
HWP 5.0 binary file parser.

HWP 5.0 files use OLE Compound Document format. Body text is stored as
zlib-compressed record streams. Each record has a 4-byte header encoding
tag ID, nesting level, and payload size.
"""

import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Union
import olefile


# ---------------------------------------------------------------------------
# HWP record tag IDs (HWPTAG_BEGIN = 16)
# ---------------------------------------------------------------------------
HWPTAG_BEGIN = 16

TAG_PARA_HEADER      = HWPTAG_BEGIN + 50   # 66
TAG_PARA_TEXT        = HWPTAG_BEGIN + 51   # 67
TAG_PARA_CHAR_SHAPE  = HWPTAG_BEGIN + 52   # 68
TAG_PARA_LINE_SEG    = HWPTAG_BEGIN + 53   # 69
TAG_CTRL_HEADER      = HWPTAG_BEGIN + 54   # 70
TAG_LIST_HEADER      = HWPTAG_BEGIN + 55   # 71
TAG_TABLE            = HWPTAG_BEGIN + 60   # 76
TAG_STYLE            = HWPTAG_BEGIN + 10   # 26

# Inline control characters inside paragraph text words
SPECIAL_CTRL_TAB        = 0x09
SPECIAL_CTRL_LINE_BREAK = 0x0A
SPECIAL_CTRL_PARA_BREAK = 0x0D
INLINE_CTRL_EXTRA_WORDS = 7   # non-special ctrl chars carry 7 extra words


# ---------------------------------------------------------------------------
# Low-level record reader
# ---------------------------------------------------------------------------

@dataclass
class Record:
    tag: int
    level: int
    data: bytes


def _read_record(buf: bytes, offset: int):
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
# FileHeader
# ---------------------------------------------------------------------------

@dataclass
class FileHeader:
    version: tuple
    compressed: bool
    encrypted: bool


def _parse_file_header(data: bytes) -> FileHeader:
    if len(data) < 40 or not data[:17].startswith(b'HWP Document File'):
        raise HwpParseError('Not a valid HWP file (bad signature)')

    ver_bytes = data[32:36]
    version = (ver_bytes[3], ver_bytes[2], ver_bytes[1], ver_bytes[0])
    flags = struct.unpack_from('<I', data, 36)[0]

    return FileHeader(
        version=version,
        compressed=bool(flags & 1),
        encrypted=bool(flags & 2),
    )


# ---------------------------------------------------------------------------
# Document model: unified ordered content
# ---------------------------------------------------------------------------

@dataclass
class Paragraph:
    text: str
    style_name: str = ''


@dataclass
class Cell:
    row: int
    col: int
    text: str = ''


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
            key = (c.row, c.col)
            grid[key] = grid.get(key, '') + c.text.replace('\n', ' ').strip()

        lines = []
        for r in range(self.rows):
            row_vals = [grid.get((r, c), '') for c in range(self.cols)]
            lines.append('| ' + ' | '.join(row_vals) + ' |')
            if r == 0:
                lines.append('| ' + ' | '.join(['---'] * self.cols) + ' |')
        return '\n'.join(lines)


# Content is an ordered sequence of paragraphs and tables
Block = Union[Paragraph, Table]


@dataclass
class HwpDocument:
    version: tuple
    content: List[Block]  # paragraphs and tables in document reading order

    # Style names that map to heading levels
    _HEADING_MAP = {
        '제목': 1, 'Title': 1,
        '소제목': 2,
        '개요 1': 2, 'Heading 1': 2,
        '개요 2': 3, 'Heading 2': 3,
        '개요 3': 4, 'Heading 3': 4,
        '개요 4': 5, 'Heading 4': 5,
        '개요 5': 6, 'Heading 5': 6,
    }

    def to_text(self) -> str:
        parts = []
        for block in self.content:
            if isinstance(block, Paragraph) and block.text.strip():
                parts.append(block.text.strip())
            elif isinstance(block, Table):
                for cell in block.cells:
                    if cell.text.strip():
                        parts.append(cell.text.strip())
        return '\n'.join(parts)

    def to_markdown(self) -> str:
        parts = []
        for block in self.content:
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                level = self._HEADING_MAP.get(block.style_name)
                if level:
                    parts.append('#' * level + ' ' + text)
                else:
                    parts.append(text)
            elif isinstance(block, Table):
                md = block.to_markdown()
                if md:
                    parts.append(md)
        return '\n\n'.join(parts)

    def to_llm_text(self) -> str:
        """
        Compact format optimised for LLM context windows.
        Headings use XML-style tags; tables are pipe-delimited.
        """
        parts = []
        for block in self.content:
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if not text:
                    continue
                level = self._HEADING_MAP.get(block.style_name)
                if level:
                    tag = f'h{level}'
                    parts.append(f'<{tag}>{text}</{tag}>')
                else:
                    parts.append(text)
            elif isinstance(block, Table):
                md = block.to_markdown()
                if md:
                    parts.append(md)
        return '\n'.join(parts)

    def to_json(self) -> dict:
        blocks = []
        for block in self.content:
            if isinstance(block, Paragraph):
                blocks.append({
                    'type': 'paragraph',
                    'style': block.style_name,
                    'text': block.text,
                })
            elif isinstance(block, Table):
                blocks.append({
                    'type': 'table',
                    'rows': block.rows,
                    'cols': block.cols,
                    'cells': [
                        {'row': c.row, 'col': c.col, 'text': c.text}
                        for c in block.cells
                    ],
                })
        return {
            'version': '.'.join(str(v) for v in self.version),
            'content': blocks,
        }


# ---------------------------------------------------------------------------
# Style extraction from DocInfo
# ---------------------------------------------------------------------------

def _parse_styles(doc_info_buf: bytes) -> dict:
    """Return {style_index: name} from DocInfo TAG_STYLE records."""
    styles = {}
    idx = 0
    for rec in iter_records(doc_info_buf):
        if rec.tag == TAG_STYLE:
            if len(rec.data) >= 2:
                name_len = struct.unpack_from('<H', rec.data, 0)[0]
                end = 2 + name_len * 2
                if end <= len(rec.data):
                    name = rec.data[2:end].decode('utf-16-le', errors='replace')
                    styles[idx] = name
            idx += 1
    return styles


# ---------------------------------------------------------------------------
# Paragraph text extraction
# ---------------------------------------------------------------------------

def _extract_para_text(data: bytes) -> str:
    """
    Parse a TAG_PARA_TEXT payload (UTF-16LE words).
    Control chars 0x01-0x1F that are not tab/newline are inline objects
    occupying 8 words total (1 ctrl + 7 extra).
    """
    chars = []
    i = 0
    while i + 1 < len(data):
        code = struct.unpack_from('<H', data, i)[0]
        i += 2

        if code == SPECIAL_CTRL_PARA_BREAK or code == SPECIAL_CTRL_LINE_BREAK:
            chars.append('\n')
        elif code == SPECIAL_CTRL_TAB:
            chars.append('\t')
        elif 0x01 <= code <= 0x1F:
            i += INLINE_CTRL_EXTRA_WORDS * 2  # skip inline object payload
        else:
            chars.append(chr(code))

    return ''.join(chars)


def _para_style_index(data: bytes) -> int:
    """Extract style index byte from TAG_PARA_HEADER payload."""
    return data[8] if len(data) >= 10 else 0


# ---------------------------------------------------------------------------
# Section parser — preserves document order
# ---------------------------------------------------------------------------

def _parse_section(buf: bytes, styles: dict) -> List[Block]:
    """
    Parse a decompressed section buffer and return content blocks in order.

    State machine:
    - Outside table: TAG_PARA_TEXT → Paragraph appended to content
    - Inside table cell (TAG_LIST_HEADER seen): text accumulates into Cell
    - TAG_TABLE marks start of a new Table block
    """
    content: List[Block] = []

    current_style_idx = 0
    current_table: Table | None = None
    current_cell: Cell | None = None
    table_row = -1
    table_col = -1
    # Track nesting level to know when we exit a table's cell lists
    table_list_level: int | None = None

    for rec in iter_records(buf):
        if rec.tag == TAG_PARA_HEADER:
            current_style_idx = _para_style_index(rec.data)

        elif rec.tag == TAG_PARA_TEXT:
            text = _extract_para_text(rec.data)
            if current_cell is not None:
                # Accumulate text into the current table cell
                current_cell.text += text
            else:
                current_table = None  # leaving table context
                content.append(Paragraph(
                    text=text,
                    style_name=styles.get(current_style_idx, ''),
                ))

        elif rec.tag == TAG_TABLE:
            if len(rec.data) >= 8:
                rows = struct.unpack_from('<H', rec.data, 4)[0]
                cols = struct.unpack_from('<H', rec.data, 6)[0]
                current_table = Table(rows=rows, cols=cols)
                content.append(current_table)
                table_row = -1
                table_col = -1
                current_cell = None
                table_list_level = rec.level

        elif rec.tag == TAG_LIST_HEADER and current_table is not None:
            # Each TAG_LIST_HEADER at the expected nesting level is a cell
            table_col += 1
            if table_col >= current_table.cols:
                table_col = 0
                table_row += 1
            current_cell = Cell(row=table_row, col=table_col)
            current_table.cells.append(current_cell)

    return content


# ---------------------------------------------------------------------------
# HWPX (ZIP/XML) support
# ---------------------------------------------------------------------------

def _parse_hwpx(path: Path) -> HwpDocument:
    import zipfile
    from xml.etree import ElementTree as ET

    content: List[Block] = []

    with zipfile.ZipFile(path) as zf:
        section_files = sorted(
            n for n in zf.namelist()
            if n.startswith('Contents/') and n.endswith('.xml') and 'section' in n.lower()
        )
        for sf in section_files:
            try:
                root = ET.fromstring(zf.read(sf))
            except ET.ParseError:
                continue
            for elem in root.iter():
                if elem.tag.endswith('}t') or elem.tag == 't':
                    text = (elem.text or '') + (elem.tail or '')
                    if text.strip():
                        content.append(Paragraph(text=text))

    return HwpDocument(version=(0, 0, 0, 0), content=content)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class HwpParseError(Exception):
    pass


def parse(filepath) -> HwpDocument:
    """
    Parse an HWP or HWPX file and return an HwpDocument.

    Raises:
        FileNotFoundError: if the file does not exist
        HwpParseError: if the file is not a valid or supported HWP/HWPX file
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f'File not found: {path}')

    with open(path, 'rb') as f:
        magic = f.read(4)

    if magic == b'PK\x03\x04':
        return _parse_hwpx(path)

    if not olefile.isOleFile(str(path)):
        raise HwpParseError(f'Not a valid HWP/HWPX file: {path}')

    ole = olefile.OleFileIO(str(path))
    try:
        return _parse_hwp5(ole)
    finally:
        ole.close()


def _parse_hwp5(ole: olefile.OleFileIO) -> HwpDocument:
    if not ole.exists('FileHeader'):
        raise HwpParseError('Missing FileHeader stream')

    header = _parse_file_header(ole.openstream('FileHeader').read())

    if header.encrypted:
        raise HwpParseError('Encrypted HWP files are not supported')

    compressed = header.compressed

    styles: dict = {}
    if ole.exists('DocInfo'):
        raw = ole.openstream('DocInfo').read()
        if compressed:
            try:
                raw = zlib.decompress(raw, -15)
            except zlib.error:
                pass
        styles = _parse_styles(raw)

    all_content: List[Block] = []
    section_num = 0
    while ole.exists(f'BodyText/Section{section_num}'):
        raw = ole.openstream(f'BodyText/Section{section_num}').read()
        if compressed:
            try:
                raw = zlib.decompress(raw, -15)
            except zlib.error:
                pass
        all_content.extend(_parse_section(raw, styles))
        section_num += 1

    # Fallback: PrvText preview stream (loses structure but better than nothing)
    if not all_content and ole.exists('PrvText'):
        prv = ole.openstream('PrvText').read()
        text = prv.decode('utf-16-le', errors='replace')
        for line in text.splitlines():
            if line.strip():
                all_content.append(Paragraph(text=line))

    return HwpDocument(version=header.version, content=all_content)
