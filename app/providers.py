"""Real AI API adapters; never produce sample or synthetic output."""
import base64
import io
import ipaddress
import mimetypes
import socket
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx


class JobCanceled(Exception):
    pass


class ProviderTerminalError(Exception):
    """Provider explicitly rejected or failed a request; safe to submit a fresh one."""
    pass


def safe_media_url(url):
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    # Restrict output retrieval to known fal and OpenAI storage CDN origins.
    allow = ('fal.media','fal.ai','storage.googleapis.com','openai.com','oaidalleapiprodscus.blob.core.windows.net')
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('URL kết quả không an toàn')
    if not any(host == item or host.endswith('.' + item) for item in allow):
        raise ValueError('CDN kết quả không thuộc danh sách hỗ trợ: ' + host)
    return url


def download_media(url, destination, proxy=''):
    safe_media_url(url)
    with httpx.Client(timeout=httpx.Timeout(45, connect=15), proxy=proxy or None, follow_redirects=False) as client:
        for _ in range(4):
            with client.stream('GET',url) as resp:
                if resp.status_code in (301,302,303,307,308):
                    new_url = resp.headers.get('location','')
                    from urllib.parse import urljoin
                    url=urljoin(url,new_url)
                    safe_media_url(url)
                    continue
                resp.raise_for_status()
                size = 0
                with open(destination,'wb') as output:
                    for chunk in resp.iter_bytes(128 * 1024):
                        size += len(chunk)
                        if size > 500 * 1024 * 1024:
                            raise ValueError('Tệp vượt quá 500 MB')
                        output.write(chunk)
                if size == 0:
                    raise ValueError('Tệp kết quả trống')
                return
    raise ValueError('Quá nhiều redirect')


def fal_endpoint(job):
    if job['kind'] == 'image':
        return 'fal-ai/flux/dev/image-to-image' if job['ref_name'] else 'fal-ai/flux/dev'
    return 'fal-ai/kling-video/v2.6/pro/image-to-video' if job['ref_name'] else 'fal-ai/kling-video/v2.6/pro/text-to-video'


def fal_payload(job, reference=None):
    prompt=job['prompt']
    if job['kind']=='image':
        payload={'prompt':prompt, 'num_images':1,'output_format':'jpeg'}
        if reference:
            payload['image_url']=reference
            payload['strength']=0.65
        else:
            payload['image_size']={'9:16':'portrait_16_9','16:9':'landscape_16_9','1:1':'square_hd','4:3':'landscape_4_3'}[job['ratio']]
        return payload
    payload={'prompt':prompt,'duration':str(job['duration']),'generate_audio':False}
    if reference:
        payload['start_image_url']=reference
    else:
        payload['aspect_ratio']=job['ratio']
    return payload


def data_image(path):
    data = Path(path).read_bytes()
    mime = mimetypes.guess_type(path)[0] or 'image/png'
    return f'data:{mime};base64,' + base64.b64encode(data).decode()




def retry_safe_get(client, url, *, params=None, sleep=time.sleep):
    """Retry only idempotent GET. Never blindly replay paid POST on HTTP 5xx."""
    for attempt in range(5):
        try:
            response=client.get(url,params=params)
        except (httpx.TimeoutException,httpx.TransportError):
            if attempt==4:raise
        else:
            if response.status_code not in (429,500,502,503,504) or attempt==4:
                return response
        sleep(min(2**attempt,12))
    raise RuntimeError('GET retry exhausted')

def call_fal(job, account, store, on_remote, on_status, cancelled, sleep=time.sleep):
    """Queue, poll and obtain actual results with persisted remote_id to allow resuming."""
    endpoint = job['endpoint'] or fal_endpoint(job)
    key=account['secret']
    headers={'Authorization':'Key '+key,'Content-Type':'application/json'}
    proxy=account.get('proxy') or None
    with httpx.Client(headers=headers,timeout=httpx.Timeout(60,connect=15),proxy=proxy) as client:
        rid=job['remote_id']
        if not rid:
            if cancelled(): raise JobCanceled()
            ref=data_image(str(store.root/'references'/job['ref_name'])) if job['ref_name'] else None
            resp=client.post('https://queue.fal.run/'+endpoint,json=fal_payload(job,ref))
            if resp.status_code in (400,401,403,404,422,429):
                raise ProviderTerminalError(f'Nhà cung cấp từ chối gửi tác vụ (HTTP {resp.status_code})')
            resp.raise_for_status()
            rid=resp.json()['request_id']
            on_remote(rid,endpoint)
        status_url=f'https://queue.fal.run/{endpoint}/requests/{rid}/status'
        response_url=f'https://queue.fal.run/{endpoint}/requests/{rid}'
        for _ in range(1800):  # 2.5 hours at 5s polling
            if cancelled():
                # Explicit cancellation attempts remote cancellation as well.
                try: client.put('https://queue.fal.run/'+endpoint+'/requests/'+rid+'/cancel',timeout=10)
                except httpx.HTTPError: pass
                raise JobCanceled()
            resp=retry_safe_get(client,status_url,params={'logs':'1'},sleep=sleep)
            resp.raise_for_status()
            s=resp.json()
            state=s.get('status','UNKNOWN')
            if state=='COMPLETED':
                if s.get('error'):
                    raise ProviderTerminalError(str(s['error']))
                break
            if state in ('FAILED','CANCELED'):
                raise ProviderTerminalError('Nhà cung cấp báo '+state+': '+str(s.get('error','')))
            if state not in ('IN_QUEUE','IN_PROGRESS'):
                raise RuntimeError('Trạng thái không xác định từ fal.ai: '+str(state))
            on_status(state)
            sleep(5)
        else:
            raise TimeoutError('Tác vụ quá thời gian theo dõi (150 phút); có thể kiểm tra lại sau')
        resp=retry_safe_get(client,response_url,sleep=sleep)
        resp.raise_for_status()
        result=resp.json()
        urls=([o['url'] for o in result.get('images',[]) if isinstance(o,dict) and o.get('url')]
             if job['kind']=='image' else [result['video']['url']])
        if not urls: raise ValueError('Dịch vụ không trả về tệp kết quả')
        return urls


def call_openai(job, account, store, on_remote, on_status, cancelled, sleep=time.sleep):
    if job['kind']!='image':
        raise ValueError('Tài khoản OpenAI chỉ hỗ trợ tạo ảnh trong bản này; video dùng fal.ai')
    if cancelled(): raise JobCanceled()
    with httpx.Client(timeout=httpx.Timeout(180,connect=15),proxy=account.get('proxy') or None,
      headers={'Authorization':'Bearer '+account['secret']}) as client:
        if job['ref_name']:
            path=store.root/'references'/job['ref_name']
            with open(path,'rb') as f:
                files=[('image',(path.name, f.read(),mimetypes.guess_type(path)[0] or 'image/png'))]
            response=client.post('https://api.openai.com/v1/images/edits',
              data={'model':'gpt-image-1','prompt':job['prompt'],'size':{'9:16':'1024x1536','16:9':'1536x1024','1:1':'1024x1024','4:3':'1536x1024'}[job['ratio']]},files=files)
        else:
            response=client.post('https://api.openai.com/v1/images/generations',
              json={'model':'gpt-image-1','prompt':job['prompt'],'size':{'9:16':'1024x1536','16:9':'1536x1024','1:1':'1024x1024','4:3':'1536x1024'}[job['ratio']]})
        if response.status_code in (400,401,403,404,422,429):
            raise ProviderTerminalError(f'OpenAI từ chối request (HTTP {response.status_code})')
        response.raise_for_status()
        result=response.json()
        on_status('IN_PROGRESS')
        data=result.get('data') or []
        if not data:
            raise ValueError('OpenAI không trả về ảnh')
        return [{'b64_json':obj['b64_json']} if obj.get('b64_json') else obj['url'] for obj in data]


def generate(job, account, store, on_remote, on_status, cancelled):
    if account['provider']=='fal':
        return call_fal(job,account,store,on_remote,on_status,cancelled)
    if account['provider']=='openai':
        return call_openai(job,account,store,on_remote,on_status,cancelled)
    raise ValueError('Provider chưa hỗ trợ')
