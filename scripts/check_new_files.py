#!/usr/bin/env python3
"""오픈API가 없는 데이터(datasets.json 에서 "api": false)에 새 파일이 올라왔는지 확인한다.

공공데이터포털 데이터 페이지의 제목(예: '…강좌정보_20261123 | 공공데이터포털')에서
파일 날짜만 읽고, data/raw 에 있는 CSV 파일 이름의 날짜와 비교한다. 파일을 내려받지는 않는다.

새 파일이 있으면:
  - GITHUB_TOKEN, GITHUB_REPOSITORY 가 있으면 (GitHub Actions) 이슈를 연다. 같은 제목의 열린 이슈가 있으면 다시 열지 않는다.
  - 없으면 (로컬) 결과만 출력한다.

새 파일이 없거나 페이지를 읽지 못해도 실패로 끝내지 않는다 (자동 갱신을 막지 않기 위해).
"""
import fnmatch
import glob
import json
import os
import re
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, 'data', 'raw')
PAGE = 'https://www.data.go.kr/data/{id}/fileData.do'


def http(url, data=None, token=None, method=None):
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; olly-data-check)'}
    if token:
        headers.update({'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'})
    body = json.dumps(data).encode() if data is not None else None
    if body:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', 'replace')


def portal_date(ds):
    html = http(PAGE.format(id=ds['id']))
    m = re.search(r'<title>([^<]*)</title>', html)
    title = m[1].strip() if m else ''
    d = re.findall(r'_(20\d{6})', title)
    return (d[-1] if d else ''), title


def local_date(ds):
    best = ''
    for name in (os.listdir(RAW) if os.path.isdir(RAW) else []):
        name = unicodedata.normalize('NFC', name)  # macOS에서 올린 파일은 NFD 이름
        if not fnmatch.fnmatch(name, ds['raw_glob']) or any(x in name for x in ds.get('raw_exclude', [])):
            continue
        d = re.findall(r'20\d{6}', name)
        if d and max(d) > best:
            best = max(d)
    return best


def fmt(d):
    return f'{d[:4]}-{d[4:6]}-{d[6:]}' if len(d) == 8 else '없음'


def open_issue(item, token, repo):
    title = f"[데이터] {item['name']} 새 파일 ({fmt(item['portal'])})"
    api = f'https://api.github.com/repos/{repo}/issues'
    existing = json.loads(http(f'{api}?state=open&per_page=100', token=token))
    if any(i.get('title') == title for i in existing):
        print(f'  이미 열린 이슈가 있음: {title}')
        return
    body = f"""공공데이터포털에 새 파일이 올라왔어요. 이 데이터는 오픈API가 없어서 CSV를 직접 넣어야 해요.

- 데이터: [{item['title']}]({item['url']})
- 포털 파일 날짜: **{fmt(item['portal'])}**
- 저장소의 CSV 날짜: {fmt(item['local'])}

### 반영 방법
1. 위 링크에서 CSV 파일을 내려받습니다. (파일 이름을 바꾸지 마세요)
2. 저장소의 `data/raw/` 폴더에서 **Add file → Upload files**로 올리고 커밋합니다.
3. 업로드하면 자동 갱신이 바로 실행됩니다. Actions 탭의 실행 로그에서 `강좌 N → M개`를 확인하세요.
4. 반영되면 이 이슈를 닫아 주세요.

_매주 자동 갱신 때 `scripts/check_new_files.py`가 확인해서 연 이슈예요._"""
    res = json.loads(http(api, data={'title': title, 'body': body}, token=token, method='POST'))
    print(f"  이슈를 열었어요: {res.get('html_url')}")


def main():
    conf = json.load(open(os.path.join(ROOT, 'scripts', 'datasets.json'), encoding='utf-8'))
    token, repo = os.environ.get('GITHUB_TOKEN'), os.environ.get('GITHUB_REPOSITORY')
    for ds in conf['courses'] + [conf['events']]:
        if ds.get('api', True):
            continue
        name = conf['centers'][ds['center']] if 'center' in ds else ds['title']
        print(f'[{name}] {ds["title"]}')
        try:
            portal, page_title = portal_date(ds)
        except Exception as e:  # noqa: BLE001
            print(f'  ! 포털 페이지를 읽지 못함: {e}')
            continue
        local = local_date(ds)
        print(f'  포털 파일 {fmt(portal)} · 저장소 CSV {fmt(local)}')
        if not portal:
            print(f'  ! 페이지 제목에서 날짜를 찾지 못함: {page_title!r}')
            continue
        if portal <= local:
            print('  최신 파일이 이미 있어요')
            continue
        item = {'name': name, 'title': ds['title'], 'url': PAGE.format(id=ds['id']),
                'portal': portal, 'local': local}
        if token and repo:
            try:
                open_issue(item, token, repo)
            except Exception as e:  # noqa: BLE001
                print(f'  ! 이슈를 열지 못함: {e}')
        else:
            print(f"  → 새 파일이 있어요. 내려받아 data/raw/ 에 넣어 주세요: {item['url']}")


if __name__ == '__main__':
    main()
