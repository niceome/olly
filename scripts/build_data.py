#!/usr/bin/env python3
"""공공데이터포털 강좌·이벤트 데이터를 받아 courses.json, events.json 으로 변환한다.

데이터를 가져오는 순서 (센터마다 따로):
  1. 오픈API(자동변환, api.odcloud.kr) - 환경변수 DATA_GO_KR_KEY 가 있을 때
  2. data/raw 의 예비 CSV - 파일 이름의 날짜가 가장 최근인 것
  3. 기존 courses.json / events.json 의 해당 센터 데이터 유지

출력 형식 (index.html 이 그대로 읽음)
  courses.json: [센터, 능력치, 종목, 강좌명, "HH:MM-HH:MM", "월,수,금", 대상, 수강료, 신청URL]
  events.json : [센터, 제목, 시작일, 종료일, 등록일, 구분, 게시글URL]

표준 라이브러리만 사용한다.
"""
import argparse
import csv
import datetime as dt
import glob
import io
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, 'scripts')
RAW = os.path.join(ROOT, 'data', 'raw')
COURSES_OUT = os.path.join(ROOT, 'courses.json')
EVENTS_OUT = os.path.join(ROOT, 'events.json')

STATS = ['지구력', '근력', '유연성', '민첩성', '리듬감', '집중력', '기타']
DAYS = '월화수목금토일'
API_BASE = 'https://api.odcloud.kr/api'
SPEC_URL = 'https://infuser.odcloud.kr/oas/docs?namespace={id}/v1'
ADULT_ONLY = False  # True 면 어린이·청소년 강좌를 아예 뺀다 (지금은 화면에서 거름)

# 원본 열 이름 후보. 센터·연도마다 열 이름이 달라서 앞에서부터 처음 맞는 열을 쓴다.
# 원본 열 이름이 바뀌어 강좌가 줄면 여기에 새 이름을 추가한다.
COLS = {
    'sport': ['종목', '종목명', '강좌종목', '운동종목', '프로그램종목', '강좌구분', '프로그램구분', '분류', '강좌분류'],
    'name': ['강좌명', '프로그램명', '강습명', '반명', '강좌반명', '과정명', '강좌'],
    'time': ['강좌시간', '강습시간', '수업시간', '운영시간', '시간', '이용시간', '강좌시간대'],
    'start_time': ['시작시간', '강좌시작시간', '수업시작시간', '운영시작시간'],
    'end_time': ['종료시간', '강좌종료시간', '수업종료시간', '운영종료시간'],
    'days': ['요일', '강좌요일', '운영요일', '수업요일', '강습요일', '이용요일'],
    'target': ['대상', '수강대상', '강좌대상', '이용대상', '모집대상', '대상구분'],
    'price': ['수강료', '강좌료', '이용료', '금액', '가격', '수강료(원)', '강습료', '월수강료'],
    'period': ['강좌기간', '운영기간', '수강기간', '기간', '교육기간'],
    'start': ['강좌시작일', '시작일', '개강일', '운영시작일', '수강시작일', '시작일자'],
    'end': ['강좌종료일', '종료일', '종강일', '운영종료일', '수강종료일', '종료일자'],
    'url': ['신청URL', '수강신청URL', '홈페이지', 'URL', '링크', '바로가기', '접수URL'],
}
EVENT_COLS = {
    'center': ['센터명', '센터', '시설명', '사업장', '사업장명', '기관명', '시설'],
    'title': ['제목', '이벤트명', '게시글제목', '행사명', '이벤트제목', '게시물제목'],
    'posted': ['등록일', '게시일', '작성일', '등록일자', '게시일자', '작성일자'],
    'period': ['이벤트기간', '행사기간', '기간', '진행기간'],
    'start': ['이벤트시작일', '행사시작일', '시작일', '시작일자'],
    'end': ['이벤트종료일', '행사종료일', '종료일', '종료일자'],
    'url': ['URL', '게시글URL', '링크', '주소', '상세URL', '게시글주소'],
}

# 사전에 없는 종목을 분류하는 키워드 (앞에서부터 처음 맞는 것)
STAT_KEYWORDS = [
    (1, r'헬스|근력|웨이트|PT|TRX|HIIT|바디펌프|크로스핏|서킷|케틀벨|바디'),
    (0, r'수영|아쿠아|워킹|걷기|러닝|런|조깅|마라톤|사이클|스피닝|자전거|스케이트|수구|철인'),
    (2, r'요가|필라테스|스트레칭|발레|SNPE|S\.N\.P\.E|폼롤러|체형'),
    (3, r'테니스|배드민턴|탁구|농구|축구|풋살|스쿼시|검도|태권도|배구|피구|복싱|킥복싱|주짓수|유도|펜싱|클라이밍|인라인'),
    (4, r'댄스|에어로빅|줌바|트램폴린|점핑|스텝|체조|로빅|리듬'),
    (5, r'골프|당구|승마|양궁|사격|볼링|다트|드론|바둑|명상'),
]

# 강사 이름으로 오인하면 안 되는 강좌 낱말
COURSE_WORDS = set('''
초급 중급 상급 고급 기초 신기초 심화 연수 입문 성인 청소년 어린이 유아 초등 주부 여성 남성 전용 혼성
주말 평일 오전 오후 저녁 새벽 야간 정규 단기 속성 정예 소수 특강 레슨 개인 그룹 실내 실외 교실 강습
강좌 강습 수업 클래스 훈련 특별 정기 공개 이벤트 리그 동호회 모임 회원 신규 기존 모던 국제식 체육관 소체육관 대체육관 이상 이하 미만 할인 제외 자유 자유형 배영 평영 접영 오리발 연습 대회 선수 마스터즈 키즈 주니어 쥬니어 시니어 실버 가족 커플
초급반 중급반 상급반 고급반 기초반 연수반 성인반 주말반 평일반 일반 기본 응용 완성 경기 체험 원데이
'''.split())
SURNAMES = set('김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용봉')


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 받기

def http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'olly-data-updater'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def latest_api_path(ds):
    """명세에서 가장 최근 파일의 uddi 경로를 찾는다. 실패하면 datasets.json 의 api_path."""
    try:
        spec = http_json(SPEC_URL.format(id=ds['id']))
        paths = []
        for p, v in (spec.get('paths') or {}).items():
            info = (v.get('get') or {})
            text = f"{info.get('summary', '')} {info.get('description', '')}"
            dates = re.findall(r'(20\d{2})[-.]?(\d{2})[-.]?(\d{2})', text)
            paths.append((max(dates) if dates else ('', '', ''), p))
        if paths:
            return sorted(paths)[-1][1]
    except Exception as e:  # noqa: BLE001
        log(f'  명세 조회 실패({e}), api_path 사용')
    return ds.get('api_path') or ''


def fetch_api(ds, key):
    path = latest_api_path(ds)
    if not path:
        raise RuntimeError('API 경로를 찾지 못함 (datasets.json 의 api_path 확인)')
    log(f'  오픈API({path})로 받는 중')
    rows, page = [], 1
    while True:
        q = urllib.parse.urlencode({'page': page, 'perPage': 1000, 'serviceKey': key})
        d = http_json(f'{API_BASE}{path}?{q}')
        data = d.get('data') or []
        rows += data
        total = d.get('totalCount') or d.get('matchCount') or 0
        if not data or len(rows) >= total:
            break
        page += 1
    if not rows:
        raise RuntimeError('받은 행이 없음')
    return rows


def read_csv(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp949', 'euc-kr'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError(f'인코딩을 알 수 없음: {path}')
    return list(csv.DictReader(io.StringIO(text)))


def latest_raw(ds):
    files = [f for f in glob.glob(os.path.join(RAW, ds['raw_glob']))
             if not any(x in os.path.basename(f) for x in ds.get('raw_exclude', []))]
    if not files:
        return None

    def k(f):
        d = re.findall(r'20\d{6}', os.path.basename(f))
        return (max(d) if d else '', os.path.getmtime(f))
    return max(files, key=k)


def get_rows(ds, key, offline):
    if key and not offline and ds.get('id'):
        try:
            return fetch_api(ds, key), 'api'
        except Exception as e:  # noqa: BLE001
            log(f'  ! 오픈API 실패: {e}')
    f = latest_raw(ds)
    if f:
        log(f'  최신 파일: {os.path.relpath(f, ROOT)}')
        return read_csv(f), 'csv'
    return None, None


# ---------------------------------------------------------------- 정제

def norm_key(s):
    return re.sub(r'[\s_()\[\]·./-]', '', str(s or ''))


def pick(row, names, used_log=None):
    nk = {norm_key(k): k for k in row}
    for n in names:
        k = nk.get(norm_key(n))
        if k is not None:
            return str(row[k] or '').strip()
    return ''


def find_cols(rows, table):
    """어떤 원본 열이 어떤 항목에 쓰였는지 로그용으로 돌려준다."""
    if not rows:
        return {}
    nk = {norm_key(k): k for k in rows[0]}
    found = {}
    for field, names in table.items():
        for n in names:
            if norm_key(n) in nk:
                found[field] = nk[norm_key(n)]
                break
    return found


def norm_date(s):
    m = re.search(r'(20\d{2})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})', s or '')
    if not m:
        m = re.search(r'(20\d{2})(\d{2})(\d{2})', s or '')
    if not m:
        return ''
    try:
        return dt.date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return ''


def split_period(s):
    """'2026-06-01~2026-06-30' 처럼 한 칸에 든 기간을 나눈다."""
    ds = re.findall(r'20\d{2}\s*[-./년]\s*\d{1,2}\s*[-./월]\s*\d{1,2}|20\d{6}', s or '')
    a = norm_date(ds[0]) if ds else ''
    b = norm_date(ds[1]) if len(ds) > 1 else ''
    return a, b


def norm_hm(h, m):
    h, m = int(h), int(m or 0)
    if not (0 <= h <= 24 and 0 <= m < 60):
        return None
    return f'{h:02d}:{m:02d}'


def norm_time(s, start='', end=''):
    if start and end:
        return norm_time(f'{start}-{end}')
    s = (s or '').replace('：', ':')
    hm = re.findall(r'(\d{1,2})\s*:\s*(\d{2})', s)
    if len(hm) >= 2:
        a, b = norm_hm(*hm[0]), norm_hm(*hm[1])
    else:
        m = re.search(r'(\d{2})(\d{2})\s*[~\-]\s*(\d{2})(\d{2})', s) or \
            re.search(r'(\d{1,2})\s*시\s*(\d{0,2})\s*분?\s*[~\-]\s*(\d{1,2})\s*시\s*(\d{0,2})', s)
        if not m:
            return ''
        a, b = norm_hm(m[1], m[2]), norm_hm(m[3], m[4])
    return f'{a}-{b}' if a and b else ''


def norm_days(s):
    s = (s or '').replace('매일', '월화수목금토일').replace('평일', '월화수목금').replace('주말', '토일')
    s = re.sub(r'주\s*7\s*일', '월화수목금토일', s)
    s = re.sub(r'주\s*5\s*일', '월화수목금', s)
    s = re.sub(r'([월화수목금토일])\s*[~∼\-]\s*([월화수목금토일])',
               lambda m: DAYS[DAYS.index(m[1]):DAYS.index(m[2]) + 1], s)
    got = {c for c in s if c in DAYS}
    return ','.join(c for c in DAYS if c in got)


def days_from_name(name):
    m = re.search(r'\(([월화수목금토일.,/·\s~]+)\)|([월화수목금토일](?:[.,/·]?[월화수목금토일])+)', name)
    return norm_days(m[0]) if m else ''


def norm_price(s):
    d = re.sub(r'[^\d]', '', (s or '').split('.')[0])
    return int(d) if d else 0


SPORT_WORDS = set()  # main() 에서 sport_stat.json 종목명으로 채움


def looks_like_name(tok):
    tok = tok.strip('*').strip()
    if not re.fullmatch(r'[가-힣]{2,4}', tok or '') or tok[0] not in SURNAMES:
        return False
    if tok in COURSE_WORDS or tok in SPORT_WORDS or any(w in tok for w in ('급', '반', '초', '과정', '교실')):
        return False
    if any(sp in tok or tok in sp for sp in SPORT_WORDS if len(sp) >= 2):
        return False
    return not any(re.search(p, tok, re.I) for _, p in STAT_KEYWORDS)


REMOVED = {}  # 강사 이름으로 보고 지운 낱말 → 원래 강좌명 (로그 확인용)


def strip_instructor(name):
    """강좌명에 든 강사 이름을 지운다.
    '*홍길동 강사', '홍길동 코치', '홍길동 실외테니스', '스피닝(화목)홍길동' 같은 경우."""
    s = name
    # '홍길동 강사', '*홍길동강사', '(홍길동 코치)'
    s = re.sub(r'[(\[]?\s*\*?\s*[가-힣]{2,4}\s*(강사|코치|선생님|선생|프로|감독)(?![가-힣])\s*(님)?\s*[)\]]?', ' ', s)
    # 맨 끝 ')홍길동' 또는 ' 홍길동'
    m = re.search(r'(?:(?<=[)\]])|\s|\*)\s*([가-힣]{2,4})\s*$', s)
    if m and looks_like_name(m[1]):
        s = s[:m.start(1)]
    # 맨 앞 '홍길동 실외테니스'
    m = re.match(r'^\s*\*?([가-힣]{2,4})\s+(?=\S)', s)
    if m and looks_like_name(m[1]):
        s = s[m.end():]
    s = re.sub(r'\s{2,}', ' ', s).strip(' -_/*')
    if s != name.strip():
        REMOVED.setdefault(name.strip(), s)
    return s


def classify(sport, name, table, unknown):
    if sport in table:
        return STATS.index(table[sport])
    text = f'{sport} {name}'
    for idx, pat in STAT_KEYWORDS:
        if re.search(pat, text, re.I):
            unknown.setdefault(sport, STATS[idx])
            return idx
    unknown.setdefault(sport, '기타')
    return 6


RENTAL = re.compile(r'(코트|구장).*(대여|대관)|정기\s*대[여관]|대관')


def build_center(center, rows, ref, table, unknown):
    cols = find_cols(rows, COLS)
    log(f'  인식한 열: {cols}')
    missing = [f for f in ('name', 'days') if f not in cols]
    if 'time' not in cols and not ('start_time' in cols and 'end_time' in cols):
        missing.append('time')
    if missing:
        log(f'  ! 필수 열 없음 {missing}. 원본 열: {list(rows[0].keys())}')

    out, skipped = [], {'시간 없음': 0, '요일 없음': 0, '대여 제외': 0}
    periods = []
    for r in rows:
        sport = pick(r, COLS['sport'])
        raw_name = pick(r, COLS['name'])
        if not raw_name:
            continue
        name = strip_instructor(raw_name) or sport or raw_name
        if RENTAL.search(sport + ' ' + raw_name):
            skipped['대여 제외'] += 1
            continue
        t = norm_time(pick(r, COLS['time']), pick(r, COLS['start_time']), pick(r, COLS['end_time']))
        if not t:
            skipped['시간 없음'] += 1
            continue
        days = norm_days(pick(r, COLS['days'])) or days_from_name(raw_name)
        if not days:
            skipped['요일 없음'] += 1
            continue
        a, b = norm_date(pick(r, COLS['start'])), norm_date(pick(r, COLS['end']))
        if not a and not b:
            a, b = split_period(pick(r, COLS['period']))
        target = pick(r, COLS['target'])
        if ADULT_ONLY and re.search(r'어린이|청소년|유아|초등|키즈|주니어|쥬니어', target + name):
            continue
        url = pick(r, COLS['url'])
        if url and not url.startswith('http'):
            url = ''
        row = [center, classify(sport, name, table, unknown), sport, name, t, days, target,
               norm_price(pick(r, COLS['price'])), url]
        periods.append((a, b))
        out.append((row, a, b))

    if any(v for v in skipped.values()):
        log(f'  건너뜀: {skipped}')

    # 갱신 시점에 운영 중인 강좌만. 운영 중인 게 하나도 없으면(원본이 아직 안 바뀜) 가장 최근 기간을 쓴다.
    dated = [x for x in out if x[1] or x[2]]
    if dated:
        live = [x for x in out if (not x[1] or x[1] <= ref) and (not x[2] or ref <= x[2])]
        if not live:
            latest = max(x[1] or x[2] for x in dated)
            log(f'  ! {ref} 에 운영 중인 강좌가 없어 가장 최근 기간({latest}~)을 사용')
            live = [x for x in out if (x[1] or x[2]) == latest]
        out = live

    seen, res = set(), []
    for row, _, _ in out:
        k = tuple(row[:8])
        if k not in seen:
            seen.add(k)
            res.append(row)
    return res


# ---------------------------------------------------------------- 이벤트

def event_type(title):
    if re.search(r'당첨|결과|발표', title):
        return '당첨 발표'
    if re.search(r'무료|체험|공개강습', title):
        return '무료 체험'
    if re.search(r'회원\s*등록|재등록', title):
        return '회원등록'
    if re.search(r'챌린지|미션|100일', title):
        return '챌린지'
    if re.search(r'캠페인|ESG|환경주간', title, re.I):
        return '캠페인'
    return '행사'


def event_center(text, url, board):
    b = re.search(r'bid=(\d+)', url or '')
    if b and b[1] in board:
        return board[b[1]]
    if '일산' in text:
        return 2
    if '분당' in text:
        return 3
    if '수영장' in text:
        return 0
    if re.search(r'올림픽공원|올림픽스포츠센터|올팍', text):
        return 1
    return None


def build_events(rows, conf):
    cols = find_cols(rows, EVENT_COLS)
    log(f'  인식한 열: {cols}')
    out, seen = [], set()
    for r in rows:
        title = re.sub(r'\s+', ' ', pick(r, EVENT_COLS['title'])).strip()
        if not title:
            continue
        url = pick(r, EVENT_COLS['url'])
        url = url if url.startswith('http') else ''
        c = event_center(pick(r, EVENT_COLS['center']) + ' ' + title, url, conf['board_center'])
        if c is None:
            continue
        posted = norm_date(pick(r, EVENT_COLS['posted']))
        if not posted or posted < conf.get('since', '2000-01-01'):
            continue
        a, b = norm_date(pick(r, EVENT_COLS['start'])), norm_date(pick(r, EVENT_COLS['end']))
        if not a and not b:
            a, b = split_period(pick(r, EVENT_COLS['period']))
        row = [c, title, a, b, posted, event_type(title), url]
        k = (c, title, posted)
        if k not in seen:
            seen.add(k)
            out.append(row)
    # 최신 글이 먼저. 화면은 내 센터 소식을 앞에서부터 몇 개만 보여 준다.
    out.sort(key=lambda x: (x[4], x[0]), reverse=True)
    return out


# ---------------------------------------------------------------- 저장

def load_json(path):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (OSError, ValueError):
        return []


def dump(path, data, dry):
    text = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    old = open(path, encoding='utf-8').read() if os.path.exists(path) else None
    if old == text:
        log(f'{os.path.basename(path)}: 바뀐 내용 없음')
        return False
    if dry:
        log(f'{os.path.basename(path)}: 바뀜 (--dry-run 이라 저장 안 함)')
        return True
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    log(f'{os.path.basename(path)}: 저장함')
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--ref', help='운영 중 판단 기준일 YYYY-MM-DD (기본: 오늘, 한국 시간)')
    ap.add_argument('--offline', action='store_true', help='오픈API를 쓰지 않고 data/raw CSV만 사용')
    ap.add_argument('--dry-run', action='store_true', help='결과만 보여 주고 저장하지 않음')
    args = ap.parse_args()

    kst = dt.timezone(dt.timedelta(hours=9))
    ref = args.ref or dt.datetime.now(kst).date().isoformat()
    key = os.environ.get('DATA_GO_KR_KEY', '').strip()
    conf = json.load(open(os.path.join(SCRIPTS, 'datasets.json'), encoding='utf-8'))
    table = json.load(open(os.path.join(SCRIPTS, 'sport_stat.json'), encoding='utf-8'))
    SPORT_WORDS.update(k for k in table if k)
    bad = {k: v for k, v in table.items() if v not in STATS}
    if bad:
        sys.exit(f'sport_stat.json 에 잘못된 능력치: {bad} (가능한 값: {STATS})')

    log(f'기준일 {ref} · 인증키 {"있음" if key else "없음 (예비 CSV 사용)"}')
    old_courses, old_events = load_json(COURSES_OUT), load_json(EVENTS_OUT)

    # 강좌
    courses, unknown = [], {}
    for ds in conf['courses']:
        c = ds['center']
        log(f'[{conf["centers"][c]}] {ds["title"]}')
        rows, src = get_rows(ds, key, args.offline)
        built = build_center(c, rows, ref, table, unknown) if rows else []
        prev = [x for x in old_courses if x[0] == c]
        if not built:
            log(f'  ! 새 데이터 없음 → 기존 강좌 {len(prev)}개 유지')
            built = prev
        elif prev and len(built) < len(prev) / 2:
            log(f'  ! 강좌가 {len(prev)} → {len(built)}개로 절반 넘게 줄어 기존 강좌 유지 (열 이름 변경 의심)')
            built = prev
        else:
            log(f'  강좌 {len(prev)} → {len(built)}개 ({src})')
            built.sort(key=lambda x: (x[2], x[4], x[3], x[5]))
        courses += built

    if REMOVED:
        log(f'강사 이름으로 보고 지운 강좌명 {len(REMOVED)}건 (잘못 지웠으면 COURSE_WORDS 에 낱말 추가):')
        for a, z in list(REMOVED.items())[:50]:
            log(f'  {a} → {z}')
    if unknown:
        log('능력치 미분류 종목 (키워드로 임시 분류함. scripts/sport_stat.json 에 추가하세요):')
        for s, v in unknown.items():
            log(f'  "{s}": "{v}"')

    if old_courses and len(courses) < len(old_courses) / 2:
        sys.exit(f'강좌가 {len(old_courses)} → {len(courses)}개로 절반 넘게 줄어 저장하지 않습니다.')

    # 이벤트
    ev_conf = conf['events']
    log(f'[이벤트] {ev_conf["title"]}')
    rows, src = get_rows(ev_conf, key, args.offline)
    events = build_events(rows, ev_conf) if rows else []
    if not events:
        log(f'  ! 새 데이터 없음 → 기존 이벤트 {len(old_events)}건 유지')
        events = old_events
    elif old_events and len(events) < len(old_events) / 2:
        log(f'  ! 이벤트가 {len(old_events)} → {len(events)}건으로 절반 넘게 줄어 기존 이벤트 유지')
        events = old_events
    else:
        log(f'  이벤트 {len(old_events)} → {len(events)}건 ({src})')

    counts = [sum(1 for x in courses if x[1] == i) for i in range(7)]
    log('능력치별 강좌: ' + ' · '.join(f'{s} {n}' for s, n in zip(STATS, counts)))
    dump(COURSES_OUT, courses, args.dry_run)
    dump(EVENTS_OUT, events, args.dry_run)


if __name__ == '__main__':
    main()
