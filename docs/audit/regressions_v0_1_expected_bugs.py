"""Audit probes documenting ACTUAL 0.1.0 behavior; not asserting intended behavior."""
import base64, time
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import Store

KEY='test-only-key'
def a(c):
    return c.post('/api/accounts',json={'name':'Audited','provider':'fal','api_key':KEY}).json()['id']
def j(c,aid,prompts=['x'],project=1):
    r=c.post('/api/jobs',json={'prompts':prompts,'account_id':aid,'kind':'image','project_id':project})
    assert r.status_code==201, r.text
    return r.json()['ids']
def wait(fn,timeout=4):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if fn():return True
        time.sleep(0.02)
    return False

def test_settings_reset_on_restart_confirmed(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        assert c.post('/api/settings',json={'workers':7}).json()['workers']==7
    with TestClient(create_app(tmp_path)) as c:
        assert c.get('/api/state').json()['engine']['workers']==2

def test_retry_of_failed_remote_keeps_invalid_remote_request_confirmed(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        aid=a(c); jid=j(c,aid)[0]
        c.app.state.store.update_job(jid,state='failed',remote_id='already-failed-remote',endpoint='fal-ai/flux/dev')
        assert c.post(f'/api/jobs/{jid}/retry').status_code==200
        job=c.app.state.store.one('SELECT * FROM jobs WHERE id=?',(jid,))
        assert (job['state'],job['remote_id'])==('queued','already-failed-remote')

def test_retry_failed_bulk_keeps_invalid_remote_request_confirmed(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        aid=a(c); jid=j(c,aid)[0]
        c.app.state.store.update_job(jid,state='failed',remote_id='already-failed-remote',endpoint='fal-ai/flux/dev')
        assert c.post('/api/jobs/retry-failed').status_code==200
        assert c.app.state.store.one('SELECT remote_id FROM jobs WHERE id=?',(jid,))['remote_id']=='already-failed-remote'

def test_deleting_job_hides_gallery_asset_but_file_remains_confirmed(tmp_path):
    sample=base64.b64encode(b'actual-invalid-image-payload').decode()
    def provider(*_args):return [{'b64_json':sample}]
    with TestClient(create_app(tmp_path,provider_func=provider)) as c:
        aid=a(c); jid=j(c,aid)[0]
        c.post('/api/control',json={'command':'start'})
        assert wait(lambda: c.get('/api/state').json()['jobs'][0]['state']=='done')
        url=c.get('/api/state').json()['assets'][0]['url']
        assert c.delete(f'/api/jobs/{jid}').status_code==200
        assert c.get('/api/state').json()['assets']==[]
        assert c.get(url).status_code==200

def test_corrupt_media_marked_done_confirmed(tmp_path):
    sample=base64.b64encode(b'not-a-valid-png-image').decode()
    def provider(*_args):return [{'b64_json':sample}]
    with TestClient(create_app(tmp_path,provider_func=provider)) as c:
        aid=a(c);j(c,aid)
        c.post('/api/control',json={'command':'start'})
        assert wait(lambda: c.get('/api/state').json()['jobs'][0]['state']=='done')
        url=c.get('/api/state').json()['assets'][0]['url']
        assert c.get(url).content==b'not-a-valid-png-image'

def test_partial_assets_still_visible_after_job_failed_confirmed(tmp_path):
    ok=base64.b64encode(b'first-result').decode()
    def provider(*_args):return [{'b64_json':ok},{'b64_json':'not-base64!!!'}]
    with TestClient(create_app(tmp_path,provider_func=provider)) as c:
        aid=a(c);j(c,aid)
        c.post('/api/control',json={'command':'start'})
        assert wait(lambda: c.get('/api/state').json()['jobs'][0]['state']=='failed')
        assert len(c.get('/api/state').json()['assets'])==1

def test_job_list_pagination_limit_confirmed(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        aid=a(c)
        for i in range(8):j(c,aid, [f'p{i}-{x}' for x in range(150)])
        assert c.app.state.store.one('SELECT count(*) as n FROM jobs')['n']==1200
        assert len(c.get('/api/state').json()['jobs'])==1000


def test_cancel_requested_can_stay_running_while_provider_blocks(tmp_path):
    import threading
    entered=threading.Event(); release=threading.Event()
    def blocked_provider(*args):
        entered.set()
        release.wait(3)
        return [{'b64_json':base64.b64encode(b'data').decode()}]
    try:
        with TestClient(create_app(tmp_path,provider_func=blocked_provider)) as c:
            aid=a(c);jid=j(c,aid)[0]
            c.post('/api/control',json={'command':'start'})
            assert entered.wait(2)
            assert c.post(f'/api/jobs/{jid}/cancel').status_code==200
            row=c.app.state.store.one('SELECT state,cancel_requested FROM jobs WHERE id=?',(jid,))
            assert row=={'state':'running','cancel_requested':1}
            release.set()
            assert wait(lambda:c.app.state.store.one('SELECT state FROM jobs WHERE id=?',(jid,))['state']=='canceled')
    finally:release.set()

def test_retry_failed_affects_other_projects_confirmed(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        aid=a(c)
        project=c.post('/api/projects',json={'name':'Other project'}).json()['id']
        id1=j(c,aid,project=1)[0]
        id2=j(c,aid,project=project)[0]
        c.app.state.store.update_job(id1,state='failed')
        c.app.state.store.update_job(id2,state='failed')
        c.post('/api/jobs/retry-failed')
        state=c.app.state.store.query('SELECT id,state FROM jobs ORDER BY id')
        assert [r['state'] for r in state]==['queued','queued']

def test_queued_jobs_do_not_restart_automatically_after_app_restart(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        aid=a(c); j(c,aid)
        c.post('/api/control',json={'command':'start'})
        c.post('/api/control',json={'command':'pause'})
    with TestClient(create_app(tmp_path)) as c:
        assert c.get('/api/state').json()['engine']['paused'] is True
