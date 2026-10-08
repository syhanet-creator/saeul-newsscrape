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
- 출처: 구글 뉴스 RSS + 지역 신문(울산뉴스넷, 울주신문: 사이트 검색 결과 수집) + 네이버 뉴스(선택)
- 유사 기사 묶기: 제목 유사도로 같은 사안의 기사를 네모 상자로 묶어 표시
- 스팸·광고 숨김: 도박/게임 사이트 글 자동 표시 후 기본 숨김 (`newscore.py`의 `BLOCKED_SOURCES`, `SPAM_RE` 또는 환경변수 `BLOCKED_SOURCES`)
- 탭: 전체 / 새울 / 지역 / 스크랩. 새울 기사 우선 정렬 옵션
- 스크랩: ☆ 클릭으로 저장(브라우저 저장), CSV 내보내기·목록 복사
- 검색 키워드 편집(최대 8개, 브라우저 저장)
- 주간 AI 요약: 최근 7일 기사를 AI로 요약. 매주 처음 열 때 자동 생성, 지난 요약은 브라우저에 보관
  - 환경변수 `GEMINI_API_KEY`(Google AI Studio 무료 키) 또는 `ANTHROPIC_API_KEY` 중 하나 필요. 둘 다 있으면 Gemini 우선
  - 로컬: `$env:GEMINI_API_KEY="..."` 후 실행 / Vercel: Project Settings -> Environment Variables 추가 후 Redeploy
  - 모델 변경: `GEMINI_MODEL`, `SUMMARY_MODEL`(Claude)
- 네이버 뉴스(선택): `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 환경변수가 있으면 자동으로 함께 검색
