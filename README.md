# saeul-newsscrape

한국수력원자력·새울원자력본부·한수원·새울본부 키워드를 실행할 때마다 구글 뉴스 RSS로 실시간 검색해 보여주는 기사 스크랩 앱.

## 실행
```
python news_scrap.py
```
또는 `실행.bat` 더블클릭. 브라우저가 자동으로 열립니다 (http://127.0.0.1:8765/).

- Python 3 표준 라이브러리만 사용 (설치 불필요)
- 키워드는 `news_scrap.py`의 `KEYWORDS`에서 수정

## 기능
- 유사 기사 묶기: 제목 유사도로 같은 사안의 기사를 네모 상자로 묶어 표시
- 주간 AI 요약: 최근 7일 기사를 AI로 요약 (버튼 클릭 시에만 호출, 30분 캐시)
  - 환경변수 `GEMINI_API_KEY` (Google AI Studio 무료 키) 또는 `ANTHROPIC_API_KEY` 중 하나 필요. 둘 다 있으면 Gemini 우선
  - 로컬: `$env:GEMINI_API_KEY="..."` 후 실행 / Vercel: Project Settings -> Environment Variables 추가 후 Redeploy
  - 모델 변경: `GEMINI_MODEL` (기본 gemini-3.8-flash), `SUMMARY_MODEL` (Claude, 기본 claude-haiku-4-5-20251001)
