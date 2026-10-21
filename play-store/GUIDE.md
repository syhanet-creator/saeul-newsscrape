# Google Play 등록 가이드 (한수원 뉴스 스크랩)

앱 주소: https://saeul-newsscrape.vercel.app  (웹앱/PWA를 안드로이드 앱으로 감싸는 방식: TWA)

## 0. 패키지 이름 (한 번 정하면 못 바꿈)
권장: `com.syhanet.khnpnews`
- **영문 자판**으로 입력하세요(한/영 키). 소문자로 시작, 영문 소문자·숫자·밑줄(_)·점(.)만 가능, 점으로 두 단어 이상.
- 이미 쓰는 이름이면 `com.syhanet.khnpnews2`처럼 바꾸고, **Play Console과 PWABuilder에 같은 이름**을 써야 합니다.

## 1. .aab 만들기 (PWABuilder, 컴퓨터 브라우저 권장)
1. https://www.pwabuilder.com 접속 → 주소에 `https://saeul-newsscrape.vercel.app` 입력 → Start
2. 점수 화면에서 **Package For Stores** → **Android** → **Generate Package**(Google Play)
3. 옵션:
   - Package ID: `com.syhanet.khnpnews`
   - App name: `한수원 뉴스 스크랩` / Short name: `한수원뉴스`
   - App version: `1.0.0` / App version code: `1`
   - Display mode: Standalone, Notification delegation 등은 기본값
   - **Signing key: New** (PWABuilder가 키를 만들어 줌)
4. Generate → zip 다운로드. 안에 들어 있는 것:
   - `*.aab` : Play Console에 올릴 파일
   - `signing.keystore`, `signing-key-info.txt` : **업로드 키와 비밀번호. 절대 잃어버리거나 공개하지 마세요**(안전한 곳에 백업)
   - `assetlinks.json` : 아래 3번에 사용
5. 다음 버전을 올릴 때는 같은 키로, **버전 코드(version code)를 1씩 올려서** 다시 만듭니다.

## 2. Play Console에 올리기
1. 앱 만들기: 앱 이름 `한수원 뉴스 스크랩`, 기본 언어 한국어, 앱, 무료
2. 테스트 → **내부 테스트** → 새 버전 만들기 → `.aab` 업로드 (Play 앱 서명 사용에 동의)
3. 설정 → **앱 무결성 → 앱 서명**에서 *앱 서명 키 인증서 SHA-256 지문* 복사

## 3. 주소창 없는 전체 화면으로 열리게 하기 (Digital Asset Links)
이 단계를 안 하면 앱 안에 크롬 주소창이 보입니다.
- 아래 두 개를 채팅에 알려 주세요(비밀이 아닌 공개 지문입니다):
  1. PWABuilder 업로드 키의 SHA-256 (`signing-key-info.txt` 또는 assetlinks.json 안)
  2. Play Console **앱 서명 키** SHA-256 (2-3)
- 제가 `https://saeul-newsscrape.vercel.app/.well-known/assetlinks.json`에 넣어 배포합니다. 형식:
```json
[{"relation":["delegate_permission/common.handle_all_urls"],
  "target":{"namespace":"android_app","package_name":"com.syhanet.khnpnews",
            "sha256_cert_fingerprints":["<앱 서명 키 SHA-256>","<업로드 키 SHA-256>"]}}]
```

## 4. 스토어 등록정보·정책 항목
- 문구·URL은 `listing.md`, 그래픽은 `icon-512.png`, `feature-graphic-1024x500.png`
- 개인정보처리방침 URL: https://saeul-newsscrape.vercel.app/privacy  (이메일 입력 후 배포 필요)
- 앱 콘텐츠: 개인정보처리방침, **뉴스 앱 선언**, 광고 포함 여부(배너가 외부 광고면 '예'), 데이터 보안(수집 없음 / 암호화 전송 HTTPS), 콘텐츠 등급 설문, 타겟 연령(성인 위주), 정부 앱 여부(아니오)
- 스크린샷: 실제 폰 화면 2장 이상

## 5. 출시 전 알아둘 점
- **신규 개인 개발자 계정**은 정식 출시 전에 *비공개 테스트*를 일정 인원·기간(예: 14일) 거쳐야 할 수 있습니다. Play Console의 안내 조건을 확인하세요.
- **명칭·로고 주의**: '한수원'·새울본부 로고를 쓰므로 '사칭/상표' 문제로 반려될 수 있습니다. 설명에 *비공식 앱*임을 분명히 적었고, 문제가 되면 이름을 바꿔야 할 수 있습니다. 한수원 공식 앱처럼 보이지 않게 주의하세요.
- 앱 내용(뉴스 목록, 운영정보 등)은 웹에서 바로 바뀌므로 **웹 배포만 하면 앱에도 반영**됩니다. 앱 파일(.aab)은 아이콘·이름·패키지 설정이 바뀔 때만 다시 올립니다.
