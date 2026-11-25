# 올리 데이터 자동 갱신 설정 방법

GitHub Actions가 **매주 월요일 새벽 4시 17분**에 공공데이터포털에서 최신 강좌·이벤트 정보를 받아 `courses.json`, `events.json`을 갱신합니다. 바뀐 내용이 있을 때만 저장되고, GitHub Pages 사이트에 반영됩니다.

## 저장소 파일 구성

```
index.html                       웹 화면
courses.json, events.json        서비스 데이터 (자동 갱신됨)
scripts/build_data.py            데이터 변환 스크립트
scripts/datasets.json            사용할 공공데이터 목록 (데이터 ID)
scripts/sport_stat.json          종목 → 능력치 분류표
data/raw/*.csv                   인증키가 없거나 API가 실패할 때 쓰는 예비 CSV
.github/workflows/update-data.yml  자동 실행 설정
```

## 1. 공공데이터포털에서 인증키 받기 

1. data.go.kr 로그인
2. 아래 데이터 페이지마다 **[오픈API] 탭 → 활용신청**을 누릅니다. 자동변환 오픈API는 보통 바로 승인됩니다.
   - 한국체육산업개발주식회사_올림픽수영장 강좌정보 (ID 15101610)
   - 한국체육산업개발주식회사_올림픽공원스포츠센터 강좌정보
   - 한국체육산업개발주식회사_일산올림픽스포츠센터 강좌정보
   - 한국체육산업개발주식회사_분당올림픽스포츠센터 강좌정보
   - 한국체육산업개발주식회사_스포츠센터 이벤트 정보 (ID 15098997로 보이며, 페이지 주소로 확인 필요)
3. **마이페이지 → 데이터활용 → Open API → 활용신청 현황**에서 **일반 인증키(Decoding)**를 복사합니다. 인증키는 한 계정에 하나라서 모든 데이터에 같은 키를 씁니다.

## 2. 데이터 ID 확인

`scripts/datasets.json`에 5개 데이터의 ID가 들어 있습니다. ID는 데이터 페이지 주소의 숫자입니다.

```
https://www.data.go.kr/data/15101610/fileData.do  →  15101610
```

스크립트는 오픈API 명세에서 가장 최근 파일의 경로(`/15101610/v1/uddi:…`)를 스스로 찾습니다. 찾지 못하면 `api_path`에 적힌 경로를 씁니다.
오픈API가 실패하면 `data/raw`의 CSV를 쓰고, CSV도 없으면 그 센터의 기존 강좌를 그대로 유지합니다.

### 예비 CSV 넣기 (선택)

data.go.kr에서 내려받은 CSV를 **이름을 바꾸지 말고** `data/raw/`에 넣으면 됩니다. 파일 이름의 날짜(예: `_20260515`)가 가장 최근인 파일을 씁니다. CP949 인코딩도 그대로 읽습니다.

## 3. GitHub에 인증키 등록

저장소 **Settings → Secrets and variables → Actions → New repository secret**
- Name: `DATA_GO_KR_KEY`
- Secret: 1번에서 복사한 인증키

> 인증키는 코드나 파일에 직접 쓰지 마세요. Secret에 넣으면 다른 사람에게 보이지 않습니다.

## 4. 쓰기 권한 켜기

**Settings → Actions → General → Workflow permissions → Read and write permissions** 선택 후 Save.

## 5. 첫 실행으로 확인

1. **Actions 탭 → "공공데이터 자동 갱신" → Run workflow**
2. 실행 기록에서 "데이터 받아서 변환" 단계의 로그를 확인합니다.
   - `오픈API(…)로 받는 중`, `최신 파일: …` → 정상
   - `! 오픈API 실패` → 인증키, 활용신청 승인, 데이터 ID를 확인하세요. 실패해도 예비 CSV나 기존 데이터로 사이트는 유지됩니다.
3. 데이터가 바뀌었다면 "데이터 자동 갱신 YYYY-MM-DD" 커밋이 생기고, 잠시 뒤 사이트에 반영됩니다.

## 이럴 땐 이렇게

| 상황 | 할 일 |
|---|---|
| 로그에 "능력치 미분류 종목"이 나옴 | `scripts/sport_stat.json`에 `"종목명": "지구력"` 형식으로 추가 |
| 강좌 수가 절반 넘게 줄어 기존 강좌를 유지함 | 원본 데이터의 열 이름이 바뀌었을 수 있음. `build_data.py`의 `COLS`에 새 열 이름 추가 |
| API 경로를 못 찾음 | 데이터 페이지의 오픈API 명세에서 `/15101610/v1/uddi:…` 형식의 경로를 복사해 `datasets.json`의 `api_path`에 입력 |
| 강사 이름이 아닌데 지워짐 | 로그의 "강사 이름으로 보고 지운 강좌명"을 확인하고, `build_data.py`의 `COURSE_WORDS`에 낱말 추가 |
| 바로 갱신하고 싶음 | Actions 탭에서 Run workflow (기준일도 지정 가능) |
| 로컬에서 미리 확인 | `python3 scripts/build_data.py --dry-run` (저장하지 않고 결과만 출력) |

## 개인정보 처리

변환 과정에서 강좌명에 들어 있는 강사 이름("*홍길동 강사", "홍길동 실외테니스", "스피닝(화목)홍길동" 등)을 지웁니다.