"""Regression tests assert intended v0.2 behavior (no billable remote API)."""
import base64
import io
import threading
import time
from pathlib import Path
import httpx
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import Store
from app import providers
from app.media_validation import verify_media


def png(size=(36,64)):
    b=io.BytesIO();Image.new('RGB',size,'red').save(b,format='PNG');return b.getvalue()


def png_b64():return base64.b64encode(png()).decode()


def client(tmp, provider=None):return TestClient(create_app(tmp,provider_func=provider))


def account(c):
    resp=c.post('/api/accounts',json={'name':'A','provider':'fal','api_key':'EXAMPLE-KEY'})
    assert resp.status_code==201,resp.text
    return resp.json()['id']


def queue(c,aid,project=1):
    r=c.post('/api/jobs',json={'prompts':['test media'],'kind':'image','account_id':aid,'project_id':project,'ratio':'9:16'})
    assert r.status_code==201,r.text
    return r.json()['ids'][0]


def wait(fn, timeout=4):
    t=time.monotonic()+timeout
    while time.monotonic()<t:
        if fn():return True
        time.sleep(.02)
    return False


def test_invalid_image_never_done_and_no_visible_asset(tmp_path):
    def invalid(*_):return [{'b64_json':base64.b64encode(b'not an image').decode()}]
    with client(tmp_path,invalid) as c:
        a=account(c);jid=queue(c,a)
        c.post('/api/control',json={'command':'start'})
        assert wait(lambda:c.app.state.store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='failed')
        assert c.get('/api/state').json()['assets']==[]
        assert not list((tmp_path/'output').iterdir())


def test_downloaded_html_disguised_as_png_is_rejected(tmp_path):
    def provider(*_):return ['https://fal.media/pretend.png']
    def download(_url,dest,_proxy):dest.write_bytes(b'<html>404 bad media </html>')
    app=create_app(tmp_path,provider_func=provider,download_func=download)
    with TestClient(app) as c:
        a=account(c);jid=queue(c,a)
        c.post('/api/control',json={'command':'start'})
        assert wait(lambda:app.state.store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='failed')
        assert c.get('/api/state').json()['assets']==[]


def test_partial_output_rolls_back_all_files(tmp_path):
    def provider(*_):return [{'b64_json':png_b64()},{'b64_json':'invalid-base64!'}]
    with client(tmp_path,provider) as c:
        a=account(c);jid=queue(c,a)
        c.post('/api/control',json={'command':'start'})
        assert wait(lambda:c.app.state.store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='failed')
        assert c.get('/api/state').json()['assets']==[]
        assert not list((tmp_path/'output').iterdir())


def test_asset_survives_job_delete_and_legacy_migration(tmp_path):
    def provider(*_):return [{'b64_json':png_b64()}]
    with client(tmp_path,provider) as c:
        a=account(c);jid=queue(c,a)
        c.post('/api/control',json={'command':'start'})
        assert wait(lambda:c.app.state.store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='done')
        asset=c.get('/api/state').json()['assets'][0]
        assert c.delete(f'/api/jobs/{jid}').status_code==200
        stored=c.get('/api/state').json()['assets'][0]
        assert stored['url']==asset['url'] and stored['prompt']=='test media' and stored['job_id'] is None
        assert c.get(asset['url']).content.startswith(b'\x89PNG')
    with client(tmp_path) as c:
        assert c.get('/api/state').json()['assets'][0]['url']==asset['url']


def test_worker_count_persisted_after_restart(tmp_path):
    with client(tmp_path) as c:
        assert c.post('/api/settings',json={'workers':7}).json()['workers']==7
    with client(tmp_path) as c:
        assert c.get('/api/state').json()['engine']['workers']==7


def test_failed_remote_cleared_only_when_provider_confirmed_failure(tmp_path):
    with client(tmp_path) as c:
        a=account(c);jid=queue(c,a)
        store=c.app.state.store
        store.update_job(jid,state='failed',remote_id='old',endpoint='fal-ai/flux/dev',remote_stage='provider_failed')
        assert c.post(f'/api/jobs/{jid}/retry').status_code==200
        row=store.one('SELECT remote_id,remote_stage FROM jobs WHERE id=?',(jid,))
        assert row=={'remote_id':None,'remote_stage':'new'}


def test_download_failure_resume_reuses_remote_and_no_force(tmp_path):
    with client(tmp_path) as c:
        a=account(c);jid=queue(c,a)
        store=c.app.state.store
        store.update_job(jid,state='failed',remote_id='valid-remote-id',endpoint='fal-ai/flux/dev',remote_stage='download_failed')
        assert c.post(f'/api/jobs/{jid}/retry').status_code==200
        assert store.one('SELECT remote_id FROM jobs WHERE id=?',(jid,))['remote_id']=='valid-remote-id'


def test_ambiguous_billable_request_requires_confirmation(tmp_path):
    with client(tmp_path) as c:
        a=account(c);jid=queue(c,a)
        store=c.app.state.store
        store.update_job(jid,state='failed',remote_stage='ambiguous')
        assert c.post(f'/api/jobs/{jid}/retry').status_code==409
        assert store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='failed'
        assert c.post(f'/api/jobs/{jid}/retry',json={'force_new':True}).status_code==200
        assert store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='queued'


def test_bulk_retry_requires_project_only_retries_safe_jobs(tmp_path):
    with client(tmp_path) as c:
        a=account(c)
        p=c.post('/api/projects',json={'name':'B'}).json()['id']
        one=queue(c,a);two=queue(c,a,p);three=queue(c,a)
        store=c.app.state.store
        store.update_job(one,state='failed',remote_stage='provider_failed',remote_id='bad',endpoint='fal-ai/flux/dev')
        store.update_job(two,state='failed',remote_stage='provider_failed')
        store.update_job(three,state='failed',remote_stage='ambiguous')
        assert c.post('/api/jobs/retry-failed').status_code==422
        resp=c.post('/api/jobs/retry-failed?project_id=1').json()
        assert resp['retried']==1 and resp['skipped']==[three]
        rows=store.query('SELECT id,state FROM jobs ORDER BY id')
        assert [r['state'] for r in rows]==['queued','failed','failed']


def test_more_than_1000_visible_plus_paged_api(tmp_path):
    with client(tmp_path) as c:
        a=account(c)
        for i in range(8):
            r=c.post('/api/jobs',json={'prompts':[f'v{i}_{j}' for j in range(150)],'account_id':a,'kind':'image'})
            assert r.status_code==201
        assert len(c.get('/api/state').json()['jobs'])==1200
        p=c.get('/api/jobs?limit=80&offset=1000').json()
        assert p['total']==1200 and len(p['items'])==80


def test_true_image_ratio_after_save(tmp_path):
    def provider(*_):return [{'b64_json':png_b64()}]
    with client(tmp_path,provider) as c:
        a=account(c);jid=queue(c,a)
        c.post('/api/control',json={'command':'start'})
        assert wait(lambda:c.app.state.store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='done')
        asset=c.get('/api/state').json()['assets'][0]
        with Image.open(tmp_path/'output'/asset['filename']) as im:
            w,h=im.size
            assert abs(w/h-9/16)<.001


def test_retry_safe_get_transient_429_503(monkeypatch):
    tries=0
    def handler(req):
        nonlocal tries
        tries+=1
        return httpx.Response([429,503,200][min(tries-1,2)],json={'ok':True})
    with httpx.Client(transport=httpx.MockTransport(handler)) as h:
        assert providers.retry_safe_get(h,'https://queue.fal.run/status',sleep=lambda _:None).status_code==200
        assert tries==3


def test_video_html_rejected(tmp_path):
    p=tmp_path/'bad.mp4';p.write_bytes(b'<html>404 not found, invalid MP4</html>')
    with pytest.raises(ValueError):verify_media(p,'video')


def test_legacy_remote_id_conservatively_migrated(tmp_path):
    s=Store(tmp_path)
    aid=s.add_account('Legacy','fal','fake')
    jid=s.queue(['legacy'],'image',aid,'9:16',5,[None])[0]
    s.update_job(jid,state='failed',remote_id='old',remote_stage='new')
    s2=Store(tmp_path)
    assert s2.one('SELECT remote_stage FROM jobs WHERE id=?',(jid,))['remote_stage']=='submitted'


def test_canceled_running_reports_request_pending(tmp_path):
    entered=threading.Event();release=threading.Event()
    def delayed(job,acc,store,remote,status,canceled):
        entered.set();release.wait(3)
        return [{'b64_json':png_b64()}]
    try:
        with client(tmp_path,delayed) as c:
            a=account(c);jid=queue(c,a);c.post('/api/control',json={'command':'start'})
            assert entered.wait(2)
            assert c.post(f'/api/jobs/{jid}/cancel').status_code==200
            item=c.get('/api/state').json()['jobs'][0]
            assert item['state']=='running' and item['cancel_requested']==1
            release.set()
            assert wait(lambda:c.app.state.store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='canceled')
    finally:release.set()


def test_valid_mp4_download_entire_worker_pipeline(tmp_path):
    """Real encoded MP4 fixture validates video download, metadata and gallery."""
    import shutil,subprocess
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg not installed in this runner')
    source=tmp_path/'sample.mp4'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi',
                    '-i','color=c=black:s=64x64:r=12:d=0.5',
                    '-c:v','mpeg4','-pix_fmt','yuv420p','-movflags','+faststart',str(source)],
                   check=True,timeout=15)
    def provider(*_):return ['https://fal.media/encoded.mp4']
    def download(_url,dest,_proxy):dest.write_bytes(source.read_bytes())
    app=create_app(tmp_path,provider_func=provider,download_func=download)
    with TestClient(app) as c:
        a=account(c)
        r=c.post('/api/jobs',json={'prompts':['short sample video'],'kind':'video','account_id':a,'ratio':'1:1','duration':5})
        assert r.status_code==201
        jid=r.json()['ids'][0]
        c.post('/api/control',json={'command':'start'})
        assert wait(lambda:app.state.store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state'] in ('done','failed'))
        job=app.state.store.one('SELECT state,error FROM jobs WHERE id=?',(jid,))
        assert job['state']=='done',job
        gallery=c.get('/api/state').json()['assets']
        assert len(gallery)==1 and gallery[0]['kind']=='video'
        assert c.get(gallery[0]['url']).content==source.read_bytes()


def test_restart_does_not_double_bill_untracked_running_job(tmp_path):
    s=Store(tmp_path);aid=s.add_account('A','openai','test-secret')
    ids=s.queue(['untracked paid POST','tracked remote'],'image',aid,'9:16',5,[None,None])
    s.update_job(ids[0],state='running',remote_stage='submitting',remote_id=None)
    s.update_job(ids[1],state='running',remote_stage='submitted',remote_id='fal-remote-123')
    with client(tmp_path) as c:
        jobs=c.app.state.store.query('SELECT id,state,remote_stage,remote_id FROM jobs ORDER BY id')
        assert jobs[0]['state']=='failed' and jobs[0]['remote_stage']=='ambiguous'
        assert jobs[1]['state']=='queued' and jobs[1]['remote_id']=='fal-remote-123'
