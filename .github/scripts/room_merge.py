"""리덱스 자동 반영 — 방 브랜치(room-<id>)를 검사해 통과하면 main에 합친다.
사용: python3 room_merge.py <index|data> <room-브랜치명>
- 자기 방 파일만 바뀌었는지, main이 그 사이 같은 파일을 바꾸지 않았는지(겹치면 중단)
- index: 금지 문자열·줄바꿈 유지·용량 급감·인라인 JS 문법 검사
- data : 공개 내보내기(run_all — 금지 문자열·개인정보·건수 10% 급감 검사)는 워크플로가 이어서 실행
결과는 RESULT 파일(마크다운)로 남기고, 실패하면 종료코드 1. 커밋·푸시는 워크플로가 한다."""
import os,re,sys,subprocess,tempfile,json
KIND,BR=sys.argv[1],sys.argv[2]
ROOM=BR.replace('room-','',1)
OUT=os.environ.get('RESULT','result.md')
PAGES={'company':['company.html'],'public':['public.html'],'csr':['index.html','pr.html'],'climate':['climate.html'],'map':['map.html'],'farm':['farm.html']}
GEN_INDEX=('data/','auto/')                                   # 공개 데이터는 총괄 도구가 만든다 — 방이 올린 것은 무시
GEN_DATA=('manifest.json','master/','db/','feeds/','auto/','indexes/csr/feed_cases.json')  # run_all이 다시 만드는 것 — 무시
FORBID=['mailto:','ceo@','hani@','claude.ai/artifact']
def sh(*a,check=True):
    r=subprocess.run(a,capture_output=True,text=True)
    if check and r.returncode: raise SystemExit(f'명령 실패: {" ".join(a)}\n{r.stderr}')
    return r.stdout
def allowed(p):
    if KIND=='index': return p in PAGES.get(ROOM,[])
    return p.startswith(f'indexes/{ROOM}/') or p.startswith(f'sources/{ROOM}/')
def gen(p): return p.startswith(GEN_INDEX) if KIND=='index' else (p in GEN_DATA or p.startswith(GEN_DATA))
log=[]; bad=[]
def done(ok):
    head=f"# {KIND} · {BR} → main : {'✅ 반영' if ok else '❌ 중단'}\n\n"
    open(OUT,'w',encoding='utf-8').write(head+'\n'.join(log+[f'- ❌ {b}' for b in bad])+'\n')
    print(open(OUT,encoding='utf-8').read()); sys.exit(0 if ok else 1)
if ROOM not in PAGES: bad.append(f'모르는 방 이름: {BR} (room-company·public·csr·climate·map·farm)'); done(False)
sh('git','fetch','-q','origin','main',BR)
base=sh('git','merge-base','origin/main',f'origin/{BR}').strip()
tip=sh('git','rev-parse','--short',f'origin/{BR}').strip()
log.append(f'- 브랜치 끝 {tip} · 갈라진 곳 {base[:7]} · main {sh("git","rev-parse","--short","origin/main").strip()}')
room=[l.split('\t') for l in sh('git','diff','--name-status','--no-renames',base,f'origin/{BR}').splitlines() if l]
mainch={l for l in sh('git','diff','--name-only','--no-renames',base,'origin/main').splitlines() if l}
take=[]
for st,p in room:
    if gen(p): log.append(f'- 무시(총괄 도구가 다시 만듦): {p}'); continue
    if not allowed(p): bad.append(f'자기 방 밖 파일: {p} — 「총괄 요청」으로 남길 것'); continue
    if p in mainch: bad.append(f'main이 그 사이 같은 파일을 바꿈: {p} — `git fetch origin && git rebase origin/main` 후 다시 올릴 것'); continue
    take.append((st,p))
if not take and not bad: bad.append('바뀐 파일 없음')
if bad: done(False)
# main 위에 방 파일 얹기
sh('git','checkout','-q','-B','main','origin/main')
for st,p in take:
    if st=='D': sh('git','rm','-q','--',p)
    else: sh('git','checkout',f'origin/{BR}','--',p)
    log.append(f'- {"삭제" if st=="D" else "반영"}: {p}')
# index 페이지 검사
if KIND=='index':
    for st,p in take:
        if st=='D': continue
        new=open(p,'rb').read(); t=new.decode('utf-8','replace')
        for f in FORBID:
            if f in t: bad.append(f'{p}: 금지 문자열 「{f}」')
        try: old=subprocess.run(['git','show',f'origin/main:{p}'],capture_output=True).stdout
        except Exception: old=b''
        if old:
            crlf=lambda b: b.count(b'\r\n')>b.count(b'\n')/2
            if crlf(old)!=crlf(new): bad.append(f'{p}: 줄바꿈이 바뀜 ({"CRLF" if crlf(old) else "LF"} → {"CRLF" if crlf(new) else "LF"})')
            if len(new)<len(old)*0.5: bad.append(f'{p}: 파일이 절반 넘게 줄어듦 ({len(old):,} → {len(new):,}바이트)')
        if 'index-ask' not in t and p!='pr.html': bad.append(f'{p}: 문의 연결(index-ask)이 없음')
        n=0
        for m in re.finditer(r'<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>',t,re.S):
            attrs,code=m.group(1),m.group(2)
            ty=re.search(r'type\s*=\s*["\']?([^"\'\s>]+)',attrs)
            if ty and ty.group(1).lower() not in ('text/javascript','application/javascript','module'): continue
            if not code.strip(): continue
            with tempfile.NamedTemporaryFile('w',suffix='.mjs' if ty and ty.group(1)=='module' else '.js',delete=False,encoding='utf-8') as fh: fh.write(code)
            r=subprocess.run(['node','--check',fh.name],capture_output=True,text=True); n+=1
            if r.returncode:
                L=r.stderr.strip().splitlines(); e=next((l for l in L if 'Error' in l),L[-1] if L else '')
                bad.append(f'{p}: 스크립트 문법 오류 — {e[:200]}')
        log.append(f'- 검사 {p}: {len(new):,}바이트 · 스크립트 {n}개 문법 확인')
if bad: done(False)
done(True)
