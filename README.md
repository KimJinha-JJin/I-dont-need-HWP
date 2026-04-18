# I don't need HWP

> 한글 문서(.hwp)를 AI와 웹 환경에서 바로 쓸 수 있게 변환하는 도구

관공서의 HWP 파일, 이제 설치 없이 브라우저에서 바로 HTML로 변환하세요.  
Google Docs 임포트도, AI 프롬프트 입력도 한 번에.

---

## 왜 만들었나

한글과컴퓨터의 HWP 포맷은 OLE 바이너리 기반이라 XML 중심의 현대 플랫폼과 궁합이 나쁩니다.
공공기관 서식을 Google Docs에 옮기거나 LLM에 문서를 읽힐 때마다 복붙·깨짐·재작업이 반복됩니다.
이 프로젝트는 그 마찰을 없애기 위해 만들었습니다.

---

## 사용법

### 브라우저 앱 (설치 불필요)

`index.html`을 브라우저에서 열고 HWP 파일을 드래그앤드롭하면 끝입니다.  
**파일은 서버에 전송되지 않으며, 브라우저 안에서만 처리됩니다.**

```
1. index.html 더블클릭
2. HWP 파일 드래그앤드롭
3. HTML 다운로드
4. Google Drive 업로드 → 파일 우클릭 → "Google 문서로 열기"
```

### Python CLI (고급 사용자)

```bash
pip install olefile
```

```bash
# Google Docs 임포트용 HTML
python cli.py 공문서.hwp -f html

# AI 프롬프트 최적화 텍스트
python cli.py 공문서.hwp -f llm

# 마크다운
python cli.py 공문서.hwp -f markdown

# JSON (RAG 파이프라인용)
python cli.py 공문서.hwp -f json
```

---

## 출력 포맷

| 포맷 | 용도 |
|---|---|
| `html` | Google Docs 임포트, 웹 공유 |
| `markdown` | 문서 뷰어, GitHub |
| `llm` | LLM 프롬프트 직접 삽입 |
| `json` | RAG · 벡터 DB 파이프라인 |
| `text` | 단순 텍스트 추출 |

---

## 지원 범위

- **HWP 5.0** — OLE 바이너리, zlib 압축/비압축
- **HWPX** — ZIP/XML 기반 (진행 중)
- 제목·개요 스타일 → HTML 헤딩 자동 변환
- 표 → HTML `<table>` / 마크다운 파이프 테이블 인라인 렌더링
- 암호화 파일 미지원

---

## 구조

```
index.html        브라우저 앱 (cfb.js + 순수 JS, 설치 불필요)
hwp_parser.py     Python 파서 라이브러리
cli.py            커맨드라인 인터페이스
requirements.txt  의존성 (olefile)
```

---

## 기술 스택

- **브라우저**: [`cfb.js`](https://github.com/SheetJS/js-cfb) (OLE 파싱) · 브라우저 네이티브 `DecompressionStream` (deflate-raw)
- **Python**: [`olefile`](https://olefile.readthedocs.io/) · 표준 라이브러리 (`zlib`, `struct`)

---

## 라이선스

MIT
