# I don't need HWP

> 한글 문서(.hwp / .hwpx)를 AI와 웹 환경에서 바로 쓸 수 있게 변환하는 도구

관공서의 HWP 파일, 이제 설치 없이 브라우저에서 바로 HTML로 변환하세요.  
Google Docs 임포트도, AI 프롬프트 입력도 한 번에.

---

## 직접 피눈물 흘려본 사람들은 안다.

공공기관에서 HWP 파일을 받아본 적 있는가. 그렇다면 당신은 이미 트라우마가 있다.

**재현 가능한 시나리오들:**

- 맥북 쓰는 사람한테 `.hwp` 첨부파일 보내는 공무원  
  → 열어보면 "이 파일을 열 수 없습니다" → 한컴뷰어 설치 → 설치 안 됨 → 포기
- AI한테 공문서 분석 시켜보려고 HWP 올렸더니  
  → "지원하지 않는 파일 형식입니다" → 울면서 복붙 → 서식 전부 날아감
- 구글 독스에 붙여넣기 했더니 표가 텍스트 한 줄로 합쳐짐  
  → 30분짜리 재작업 시작
- "HWP는 뷰어가 무료잖아요"  
  → 뷰어는 읽기만 됨. 복사도 안 됨. 편집은 유료. 감사합니다.
- 리눅스 서버에서 HWP 파일 처리하려고 방법 찾아봤더니  
  → 2009년 블로그 글이 제일 최신임
- PDF로 받으면 안 되냐고 했더니  
  → "HWP로만 제출 가능합니다" (공문)

**결론:** HWP는 1인 독점 포맷으로 대한민국 공공문서 생태계를 20년째 볼모로 잡고 있으며,  
이로 인해 발생하는 국민 멘탈 손실은 추산 불가입니다.

이 프로젝트는 그 분노를 코드로 승화한 결과물입니다.

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
2. HWP / HWPX 파일 드래그앤드롭
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

| 항목 | HWP 5.0 | HWPX |
|---|---|---|
| 텍스트 추출 | ✅ | ✅ |
| 표 (병합 셀 포함) | ✅ | ✅ |
| 이미지 | ✅ | ✅ |
| 굵기·기울임·밑줄 | — | ✅ |
| 글자 색상 | — | ✅ |
| 단락 정렬 | — | ✅ |
| 제목·개요 → HTML 헤딩 | ✅ | ✅ |
| 암호화 파일 | ❌ | ❌ |

> HWP 5.0은 바이너리 포맷 특성상 글자 서식 복원이 제한적입니다.  
> 서식 보존이 중요하다면 HWPX(한글 2010 이상에서 저장 가능)를 권장합니다.

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

- **브라우저**: [`cfb.js`](https://github.com/SheetJS/js-cfb) (OLE 파싱) · [`JSZip`](https://stuk.github.io/jszip/) (HWPX ZIP 해제) · 브라우저 네이티브 `DecompressionStream` (deflate-raw)
- **Python**: [`olefile`](https://olefile.readthedocs.io/) · 표준 라이브러리 (`zlib`, `struct`)

---

## 라이선스

MIT
