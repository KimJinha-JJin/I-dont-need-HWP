"""
CLI for HWP → text/markdown/HTML/JSON conversion.

Usage:
  python cli.py document.hwp                 # prints markdown
  python cli.py document.hwp -f html -o out.html   # Google Docs 임포트용 HTML
  python cli.py document.hwp -f text         # plain text
  python cli.py document.hwp -f json         # JSON
  python cli.py document.hwp -f llm          # LLM 프롬프트 최적화 텍스트
"""

import argparse
import json
import sys
from pathlib import Path

import hwp_parser


def main():
    parser = argparse.ArgumentParser(
        description='Convert HWP/HWPX files to text, markdown, or JSON.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
formats:
  markdown  (default) — paragraph text with heading markers
  text                — plain text, newline-separated
  json                — structured JSON with paragraphs and tables
        """,
    )
    parser.add_argument('input', help='HWP or HWPX file path')
    parser.add_argument(
        '-f', '--format',
        choices=['markdown', 'html', 'text', 'json', 'llm'],
        default='markdown',
        dest='fmt',
        help='Output format (default: markdown). html = Google Docs importable HTML',
    )
    parser.add_argument(
        '-o', '--output',
        help='Write output to file instead of stdout',
    )
    parser.add_argument(
        '--version',
        action='store_true',
        help='Print HWP file version and exit',
    )

    args = parser.parse_args()

    try:
        doc = hwp_parser.parse(args.input)
    except FileNotFoundError as e:
        print(f'Error: {e}', file=sys.stderr)
        sys.exit(1)
    except hwp_parser.HwpParseError as e:
        print(f'Parse error: {e}', file=sys.stderr)
        sys.exit(1)

    if args.version:
        v = doc.version
        print(f'HWP {v[0]}.{v[1]}.{v[2]}.{v[3]}')
        return

    if args.fmt == 'text':
        output = doc.to_text()
    elif args.fmt == 'html':
        title = Path(args.input).stem
        output = doc.to_html(title=title)
        if args.output is None:
            # Default output file name when format is html
            default_out = Path(args.input).with_suffix('.html')
            default_out.write_text(output, encoding='utf-8')
            print(f'Saved: {default_out}')
            print('Google Docs에 가져오기: 구글 드라이브에 파일 업로드 후 "Google 문서로 열기"')
            return
    elif args.fmt == 'json':
        output = json.dumps(doc.to_json(), ensure_ascii=False, indent=2)
    elif args.fmt == 'llm':
        output = doc.to_llm_text()
    else:
        output = doc.to_markdown()

    if args.output:
        Path(args.output).write_text(output, encoding='utf-8')
        print(f'Written to {args.output}')
    else:
        print(output)


if __name__ == '__main__':
    main()
