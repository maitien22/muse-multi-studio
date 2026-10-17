import io
import time
from PIL import Image
from fastapi.testclient import TestClient
from app.main import create_app
from app.providers import fal_endpoint, fal_payload, safe_media_url
from app.store import Store


def client(tmp_path, provider_func=None, download_func=None):
    app=create_app(tmp_path,provider_func,download_func)
    return TestClient(app)


def add_account(c,provider='fal',proxy=''):
    r=c.post('/api/accounts',json={'name':'tài khoản số 1','provider':provider,'api_key':'MY-SECRET-TOKEN','proxy':proxy})
    assert r.status_code==201,r.text
    return r.json()['id']


def add_job(c,account_id,kind='image',ref_names=None):
    return c.post('/api/jobs',json={'prompts':['Một người đang đi bộ','Khung cảnh chiều mưa'], 'account_id':account_id,'kind':kind,'ratio':'9:16','duration':10,'ref_names':ref_names})


def wait_until(fn,seconds=4):
    limit=time.monotonic()+seconds
    while time.monotonic()<limit:
        if fn():return True
        time.sleep(.04)
    return False


def png_b64():
    import base64
    buff=io.BytesIO();Image.new('RGB',(36,64),'pink').save(buff,format='PNG')
    return base64.b64encode(buff.getvalue()).decode()


def test_account_encryption_and_origin(tmp_path):
    with client(tmp_path) as c:
        aid=add_account(c,proxy='http://username:pass@127.0.0.1:8866')
        payload=c.get('/api/accounts').json()[0]
        assert payload['id']==aid and 'secret' not in payload and 'proxy' not in payload
        assert 'MY-SECRET-TOKEN' not in (tmp_path/'muse.db').read_bytes().decode('latin1')
        assert 'MY-SECRET-TOKEN'==c.app.state.store.get_account(aid)['secret']
        assert c.post('/api/control',json={'command':'start'},headers={'Origin':'http://evil.example'}).status_code==403
        assert c.post('/api/accounts',json={'name':'n','provider':'x','api_key':'secrets'}).status_code==422
        assert c.delete(f'/api/accounts/{aid}').status_code==200


def test_job_uses_real_worker_path(tmp_path):
    calls=[]
    def provider(job,acc,store,on_remote,on_status,canceled):
        calls.append((job['id'],acc['provider']))
        on_remote('remote_real_test_id','fal-ai/flux/dev')
        on_status('IN_PROGRESS')
        return [{'b64_json':png_b64()}]   # Valid PNG fixture; no mock provider in production.
    with client(tmp_path,provider_func=provider) as c:
        aid=add_account(c)
        assert add_job(c,aid).json()['queued']==2
        assert c.post('/api/settings',json={'workers':2}).json()['workers']==2
        c.post('/api/control',json={'command':'start'})
        assert wait_until(lambda:sum(j['state']=='done' for j in c.get('/api/state').json()['jobs'])==2)
        data=c.get('/api/state').json()
        assert len(data['assets'])==2 and len(calls)==2
        assert all(j['remote_id']=='remote_real_test_id' and j['progress']==100 for j in data['jobs'])
        assert len(list((tmp_path/'output').glob('*.png')))==2
        url=data['assets'][0]['url'];assert c.get(url).content.startswith(b'\x89PNG')
        assert c.post('/api/jobs/1/retry').status_code==409
        assert c.delete('/api/jobs/1').status_code==200
        assert c.get(url).status_code==200 # user output protected on disk


def test_retry_cancel_and_resume(tmp_path):
    def always_fail(job,acc,store,on_remote,on_status,canceled):
        raise RuntimeError('Bad key')
    with client(tmp_path,provider_func=always_fail) as c:
        aid=add_account(c)
        assert add_job(c,aid).status_code==201
        assert c.post('/api/jobs/1/cancel').status_code==200
        assert c.get('/api/state').json()['jobs'][-1]['state']=='canceled'
        assert c.post('/api/jobs/1/retry',json={'force_new':True}).status_code==200
        c.post('/api/control',json={'command':'start'})
        assert wait_until(lambda:all(j['state']=='failed' for j in c.get('/api/state').json()['jobs']))
        assert c.post('/api/jobs/retry-failed?project_id=1').status_code==200
        assert c.post('/api/control',json={'command':'pause'}).status_code==200
        assert c.delete('/api/accounts/'+str(aid)).status_code==409
    store=Store(tmp_path)
    store.update_job(1,state='running',remote_id='external-abc',endpoint='fal-ai/flux/dev',cancel_requested=0)
    resumed=[]
    def use_remote_id(job,acc,store,on_remote,on_status,canceled):
        resumed.append((job['remote_id'],job['endpoint']))
        return [{'b64_json':png_b64()}]
    with client(tmp_path,provider_func=use_remote_id) as c:
        c.post('/api/control',json={'command':'start'})
        assert wait_until(lambda:len(resumed)>0)
        assert resumed[0]==('external-abc','fal-ai/flux/dev')


def test_reference_validation_mapping_and_mode(tmp_path):
    with client(tmp_path) as c:
        aid=add_account(c)
        assert c.post('/api/references',files={'file':('notimage.png',b'nothing','image/png')}).status_code==422
        img=Image.new('RGB',(30,40))
        buf=io.BytesIO();img.save(buf,format='PNG')
        r=c.post('/api/references',files={'file':('sample.png',buf.getvalue(),'image/png')})
        assert r.status_code==201
        name=r.json()['name'];assert c.get('/media/references/'+name).status_code==200
        assert add_job(c,aid,ref_names=[name,'not-there.png']).status_code==422
        assert add_job(c,aid,kind='video',ref_names=[name,name]).status_code==201
        assert c.post('/api/jobs',json={'prompts':['hi'],'kind':'video','account_id':aid,'ratio':'4:3'}).status_code==422
        assert c.get('/media/output/../../credential.key').status_code!=200


def test_provider_payloads_and_url_rejection():
    job={'kind':'image','ratio':'9:16','duration':10,'prompt':'A girl','ref_name':None}
    assert fal_endpoint(job)=='fal-ai/flux/dev'
    assert fal_payload(job)['image_size']=='portrait_16_9'
    job['ref_name']='image.jpg';assert fal_endpoint(job).endswith('image-to-image')
    assert fal_payload(job,'https://fal.media/my.png')['image_url'].startswith('https://')
    job['kind']='video';assert fal_endpoint(job).endswith('image-to-video')
    assert fal_payload(job,'https://fal.media/my.png')['start_image_url'].startswith('https://')
    safe_media_url('https://storage.googleapis.com/example')
    for url in ('https://evil.net/image.png','http://fal.media/image.png','https://localhost/file','file:///etc/passwd'):
        try:safe_media_url(url)
        except ValueError:pass
        else:raise AssertionError('unsafe URL accepted')


def test_static_content_and_settings(tmp_path):
    with client(tmp_path) as c:
        assert 'Muse Multi Studio' in c.get('/').text
        assert c.get('/app.js').status_code==200
        assert c.get('/api/health').json()['status']=='ok'
        assert c.post('/api/settings',json={'workers':99}).status_code==422


def test_projects_are_persistent_and_job_separation(tmp_path):
    with client(tmp_path) as c:
        a=add_account(c)
        p=c.post('/api/projects',json={'name':'Video TikTok'});assert p.status_code==201
        pid=p.json()['id']
        assert c.post('/api/projects',json={'name':'Video TikTok'}).status_code==409
        assert c.put(f'/api/projects/{pid}',json={'name':'Video AI'}).status_code==200
        task=c.post('/api/jobs',json={'prompts':['tình huống 1'],'project_id':pid,'kind':'image','account_id':a})
        assert task.status_code==201
        assert c.get('/api/state').json()['jobs'][0]['project_id']==pid
        assert c.post(f'/api/projects/{pid}/renumber').json()['count']==1
        assert c.delete(f'/api/projects/{pid}').status_code==409
        assert c.delete(f'/api/jobs/{task.json()["ids"][0]}').status_code==200
        assert c.delete(f'/api/projects/{pid}').status_code==200
        assert c.delete('/api/projects/1').status_code==409


def test_fal_queue_submission_polling_contract(tmp_path,monkeypatch):
    """Exercises production HTTP adapter with mocked provider responses, never a sample result in app."""
    import httpx
    from app import providers
    real_client=httpx.Client
    captured=[]
    attempts={'polls':0}
    def handler(req):
        captured.append((req.method,str(req.url),req.headers.get('authorization','')))
        if req.method=='POST':
            assert req.url.path=='/fal-ai/flux/dev'
            assert b'portrait_16_9' in req.content
            return httpx.Response(200,json={'request_id':'abc123'})
        if str(req.url).endswith('/status?logs=1'):
            attempts['polls']+=1
            return httpx.Response(200,json={'status':'COMPLETED' if attempts['polls']>1 else 'IN_PROGRESS'})
        return httpx.Response(200,json={'images':[{'url':'https://fal.media/files/generate.jpg'}]})
    monkeypatch.setattr(providers.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw))
    from app.providers import call_fal
    store=Store(tmp_path)
    job={'kind':'image','ratio':'9:16','duration':5,'prompt':'Một người', 'ref_name':None, 'remote_id':None,'endpoint':None}
    remote=[];statuses=[]
    urls=call_fal(job,{'secret':'TEST-KEY','proxy':''},store,lambda *args:remote.append(args),statuses.append,lambda:False,sleep=lambda _:None)
    assert urls==['https://fal.media/files/generate.jpg']
    assert remote==[('abc123','fal-ai/flux/dev')]
    assert statuses==['IN_PROGRESS']
    assert len(captured)==4 and all(x[2]=='Key TEST-KEY' for x in captured)


def test_openai_image_real_endpoint_contract(tmp_path,monkeypatch):
    import httpx
    from app import providers
    real_client=httpx.Client
    seen=[]
    def handler(req):
        seen.append((str(req.url),req.headers.get('authorization')))
        assert req.method=='POST' and req.url.path=='/v1/images/generations'
        assert b'gpt-image-1' in req.content
        return httpx.Response(200,json={'data':[{'b64_json':'aGVsbG8='}]})
    monkeypatch.setattr(providers.httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(handler),**kw))
    job={'kind':'image','ratio':'9:16','prompt':'portrait','ref_name':None}
    res=providers.call_openai(job,{'secret':'MYKEY','proxy':''},Store(tmp_path),lambda *args:None,lambda s:None,lambda:False)
    assert res==[{'b64_json':'aGVsbG8='}]
    assert seen==[('https://api.openai.com/v1/images/generations','Bearer MYKEY')]
