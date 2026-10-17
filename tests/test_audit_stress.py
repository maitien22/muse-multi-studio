import base64, threading, time, io
from PIL import Image
from fastapi.testclient import TestClient
from app.main import create_app

def test_8_workers_100_jobs_each_processed_once(tmp_path):
    lock=threading.Lock()
    active=0;peak=0;seen=[]
    buf=io.BytesIO();Image.new('RGB',(18,32)).save(buf,format='PNG')
    encoded=base64.b64encode(buf.getvalue()).decode()
    def provider(job,account,store,remote,status,canceled):
        nonlocal active,peak
        with lock:
            active+=1;peak=max(peak,active);seen.append(job['id'])
        time.sleep(.015)
        with lock:active-=1
        return [{'b64_json':encoded}]
    with TestClient(create_app(tmp_path,provider_func=provider)) as c:
        acct=c.post('/api/accounts',json={'name':'A','provider':'fal','api_key':'FAKE-TEST'}).json()['id']
        c.post('/api/settings',json={'workers':8})
        r=c.post('/api/jobs',json={'prompts':[f'prompt{i}' for i in range(100)],'account_id':acct,'kind':'image'})
        assert r.status_code==201
        c.post('/api/control',json={'command':'start'})
        stop=time.monotonic()+10
        while time.monotonic()<stop:
            jobs=c.get('/api/state').json()['jobs']
            if sum(job['state']=='done' for job in jobs)==100:break
            time.sleep(.03)
        assert len(seen)==100 and len(set(seen))==100
        assert peak<=8 and peak>=2
        assert sum(job['state']=='done' for job in jobs)==100
