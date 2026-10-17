"""Local-only API + Dark Pro frontend."""
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, UnidentifiedImageError
from .store import Store, stamp
from .engine import Engine

APP_DIR=Path(__file__).resolve().parent

def default_data_dir():
    if os.environ.get('MUSE_DATA_DIR'):
        return Path(os.environ['MUSE_DATA_DIR']).expanduser()
    if os.name=='nt':
        return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData'/'Local')))/'MuseMultiStudio'
    return Path.home()/'.muse-multistudio'

class AccountIn(BaseModel):
    name: str = Field(min_length=1,max_length=80)
    provider: str
    api_key: str = Field(min_length=6,max_length=4096)
    proxy: str = Field(default='',max_length=500)

class JobsIn(BaseModel):
    prompts: list[str] = Field(min_length=1,max_length=150)
    project_id: int = 1
    kind: str
    account_id: int
    ratio: str = '9:16'
    duration: int = 5
    ref_name: str | None = None
    ref_names: list[str | None] | None = None

class ControlIn(BaseModel):
    command: str

class ProjectIn(BaseModel):
    name: str = Field(min_length=1,max_length=60)

class RetryIn(BaseModel):
    force_new: bool = False

class SettingsIn(BaseModel):
    workers: int = Field(ge=1,le=8)


def create_app(data_dir=None,provider_func=None,download_func=None):
    store=Store(data_dir or default_data_dir())
    kwargs={}
    if provider_func: kwargs['provider_func']=provider_func
    if download_func: kwargs['download_func']=download_func
    engine=Engine(store,**kwargs)
    @asynccontextmanager
    async def lifespan(app):
        engine.start()
        yield
        engine.shutdown()
    app=FastAPI(title='Muse Multi Studio',version='0.2.0',lifespan=lifespan)
    app.state.store=store
    app.state.engine=engine

    @app.middleware('http')
    async def guard(request:Request,call_next):
        # Local installation: disallow cross-site mutations and rebinding attacks.
        hostname=request.url.hostname or ''
        if hostname not in ('127.0.0.1','localhost','testserver'):
            return JSONResponse({'detail':'Chỉ cho phép truy cập localhost'},status_code=403)
        origin=request.headers.get('origin')
        if origin:
            p=urlparse(origin)
            if p.hostname not in ('127.0.0.1','localhost'):
                return JSONResponse({'detail':'Nguồn yêu cầu không hợp lệ'},status_code=403)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['X-Frame-Options']='DENY'
        return response

    @app.get('/api/health')
    def health():
        return {'status':'ok','version':'0.2.0','data_dir':str(store.root)}

    @app.get('/api/state')
    def state():
        return {'engine':engine.status(),'jobs':store.jobs(),'projects':store.list_projects(),'accounts':store.list_accounts(),'assets':store.assets()}

    @app.get('/api/jobs')
    def list_jobs(project_id:int|None=None,limit:int=100,offset:int=0):
        if limit<1 or limit>500 or offset<0:raise HTTPException(422,'limit 1-500, offset >= 0')
        sql='SELECT COUNT(*) as c FROM jobs'
        params=()
        if project_id is not None:
            sql+=' WHERE project_id=?';params=(project_id,)
        return {'items':store.jobs(limit=limit,offset=offset,project_id=project_id),
                'total':store.one(sql,params)['c'],'limit':limit,'offset':offset}

    @app.get('/api/projects')
    def projects():
        return store.list_projects()

    @app.post('/api/projects',status_code=201)
    def add_project(payload:ProjectIn):
        if not payload.name.strip(): raise HTTPException(422,'Tên dự án không được trống')
        try: pid=store.add_project(payload.name.strip())
        except Exception as exc:
            from sqlite3 import IntegrityError
            if isinstance(exc,IntegrityError): raise HTTPException(409,'Tên dự án đã tồn tại')
            raise
        return {'id':pid}

    @app.put('/api/projects/{pid}')
    def edit_project(pid:int,payload:ProjectIn):
        if not store.one('SELECT id FROM projects WHERE id=?',(pid,)):
            raise HTTPException(404,'Không thấy dự án')
        if not payload.name.strip(): raise HTTPException(422,'Tên dự án không được trống')
        try: store.execute('UPDATE projects SET name=? WHERE id=?',(payload.name.strip(),pid))
        except Exception as exc:
            from sqlite3 import IntegrityError
            if isinstance(exc,IntegrityError): raise HTTPException(409,'Tên dự án đã tồn tại')
            raise
        return {'ok':True}

    @app.delete('/api/projects/{pid}')
    def delete_project(pid:int):
        if pid==1: raise HTTPException(409,'Không xóa dự án Mặc định')
        if store.one('SELECT 1 FROM jobs WHERE project_id=?',(pid,)):
            raise HTTPException(409,'Dự án có tác vụ; hãy xóa tác vụ trước')
        store.execute('DELETE FROM projects WHERE id=?',(pid,))
        return {'ok':True}

    @app.post('/api/projects/{pid}/renumber')
    def renumber_project(pid:int):
        if not store.one('SELECT 1 FROM projects WHERE id=?',(pid,)):
            raise HTTPException(404,'Không thấy dự án')
        return {'count':store.renumber(pid)}

    @app.get('/api/accounts')
    def accounts():
        return store.list_accounts()

    @app.post('/api/accounts',status_code=201)
    def account_create(payload:AccountIn):
        if not payload.name.strip(): raise HTTPException(422,'Tên tài khoản không được trống')
        if payload.provider not in ('fal','openai'):
            raise HTTPException(422,'Provider phải là fal hoặc openai')
        if payload.proxy:
            p=urlparse(payload.proxy)
            if p.scheme not in ('http','https') or not p.hostname:
                raise HTTPException(422,'Proxy phải là http:// hoặc https:// hợp lệ')
        aid=store.add_account(payload.name.strip(),payload.provider,payload.api_key.strip(),payload.proxy.strip())
        return {'id':aid,'message':'Đã lưu thông tin kết nối (chưa xác minh API key)'}

    @app.delete('/api/accounts/{aid}')
    def account_delete(aid:int):
        if not store.one('SELECT 1 FROM accounts WHERE id=?',(aid,)):
            raise HTTPException(404,'Không tìm thấy tài khoản')
        if store.one('SELECT 1 FROM jobs WHERE account_id=?',(aid,)):
            raise HTTPException(409,'Tài khoản đã có lịch sử tác vụ; không thể xóa để tránh mất khả năng chạy lại')
        store.execute('DELETE FROM accounts WHERE id=?',(aid,))
        return {'ok':True}

    @app.post('/api/references',status_code=201)
    async def upload_reference(file:UploadFile=File(...)):
        raw=await file.read(12*1024*1024 + 1)
        if not raw or len(raw)>12*1024*1024:
            raise HTTPException(413,'Ảnh phải từ 1 byte đến 12MB')
        import io
        try:
            with Image.open(io.BytesIO(raw)) as im:
                im.verify()
            with Image.open(io.BytesIO(raw)) as im:
                if im.width*im.height>48_000_000: raise ValueError('Ảnh quá lớn')
                if im.format not in ('JPEG','PNG','WEBP'):
                    raise ValueError('Chỉ hỗ trợ JPEG/PNG/WebP')
                ext={'JPEG':'jpg','PNG':'png','WEBP':'webp'}[im.format]
        except (UnidentifiedImageError,OSError,ValueError) as e:
            raise HTTPException(422,'Ảnh không hợp lệ: '+str(e))
        fname=uuid.uuid4().hex+'.'+ext
        (store.root/'references'/fname).write_bytes(raw)
        return {'name':fname,'url':'/media/references/'+fname}

    @app.post('/api/jobs',status_code=201)
    def submit_jobs(payload:JobsIn):
        if payload.kind not in ('image','video') or payload.ratio not in ('9:16','16:9','1:1','4:3'):
            raise HTTPException(422,'Loại tác vụ hoặc tỷ lệ không hỗ trợ')
        if payload.kind=='video' and (payload.duration not in (5,10) or payload.ratio=='4:3'):
            raise HTTPException(422,'Video: 5 hoặc 10 giây, tỷ lệ 9:16/16:9/1:1')
        if not store.one('SELECT 1 FROM projects WHERE id=?',(payload.project_id,)):
            raise HTTPException(404,'Không tìm thấy dự án')
        acct=store.get_account(payload.account_id)
        if not acct: raise HTTPException(404,'Chưa chọn tài khoản AI hợp lệ')
        if acct['provider']=='openai' and payload.kind=='video':
            raise HTTPException(422,'OpenAI video API không còn khả dụng; chọn tài khoản fal.ai')
        if payload.ref_names is not None and len(payload.ref_names)!=len(payload.prompts):
            raise HTTPException(422,'Số ảnh ghép cặp phải bằng số prompt')
        refs = payload.ref_names if payload.ref_names is not None else [payload.ref_name]*len(payload.prompts)
        for ref in refs:
            if ref and (not re.fullmatch(r'[a-f0-9]{32}\.(jpg|png|webp)',ref) or not (store.root/'references'/ref).is_file()):
                raise HTTPException(422,'Ảnh tham chiếu không tồn tại')
        prompts=[p.strip() for p in payload.prompts]
        if any(not p or len(p)>10000 for p in prompts):
            raise HTTPException(422,'Mỗi prompt từ 1 đến 10.000 ký tự')
        ids=store.queue(prompts,payload.kind,payload.account_id,payload.ratio,payload.duration,refs,payload.project_id)
        return {'ids':ids,'queued':len(ids)}

    @app.post('/api/control')
    def control(payload:ControlIn):
        if payload.command=='start': engine.paused=False
        elif payload.command=='pause': engine.paused=True
        else: raise HTTPException(422,'command phải là start hoặc pause')
        return engine.status()

    @app.post('/api/settings')
    def settings(payload:SettingsIn):
        store.set_setting('workers',payload.workers)
        engine.worker_count=payload.workers
        return engine.status()

    def perform_retry(row,force_new=False):
        stage=row.get('remote_stage') or 'new'
        rid=row['remote_id']
        # Never submit another billable request while old remote ID could still be running.
        if stage in ('submitting','ambiguous') and not force_new and not rid:
            raise HTTPException(409,'Trạng thái request chưa rõ; xác minh chi phí AI, sau đó chọn tạo request mới nếu cần')
        if row['state']=='canceled' and not force_new:
            raise HTTPException(409,'Tác vụ đã hủy; xác nhận tạo request mới để tránh tính phí trùng')
        fresh=force_new or stage in ('provider_failed','new')
        if not fresh and not rid:
            raise HTTPException(409,'Không có request ID an toàn để tiếp tục; cần xác nhận tạo mới')
        store.update_job(row['id'],state='queued',error=None,progress=None,
            remote_id=None if fresh else rid,
            endpoint=None if fresh else row['endpoint'],
            remote_stage='new' if fresh else stage,
            cancel_requested=0,started_at=None,finished_at=None)

    @app.post('/api/jobs/{jid}/retry')
    def retry(jid:int,payload:RetryIn|None=None):
        row=store.one('SELECT * FROM jobs WHERE id=?',(jid,))
        if not row:raise HTTPException(404,'Không tìm thấy tác vụ')
        if row['state'] not in ('failed','canceled'):
            raise HTTPException(409,'Chỉ chạy lại tác vụ lỗi hoặc đã hủy')
        perform_retry(row,bool(payload and payload.force_new))
        return {'ok':True}

    @app.post('/api/jobs/{jid}/cancel')
    def cancel(jid:int):
        row=store.one('SELECT * FROM jobs WHERE id=?',(jid,))
        if not row: raise HTTPException(404,'Không tìm thấy tác vụ')
        if row['state']=='queued':
            store.update_job(jid,state='canceled',cancel_requested=1,finished_at=stamp())
        elif row['state']=='running':
            store.update_job(jid,cancel_requested=1)
        else: raise HTTPException(409,'Tác vụ không còn đang chờ hoặc chạy')
        return {'ok':True}

    @app.delete('/api/jobs/{jid}')
    def delete_job(jid:int):
        row=store.one('SELECT * FROM jobs WHERE id=?',(jid,))
        if not row: raise HTTPException(404,'Không tìm thấy tác vụ')
        if row['state']=='running': raise HTTPException(409,'Hãy hủy tác vụ đang chạy trước')
        with store.connect() as db:
            # ON DELETE SET NULL retains immutable library history, files and prompt snapshots.
            db.execute('DELETE FROM jobs WHERE id=?',(jid,))
        # Keep generated media files on disk to avoid accidental data loss.
        return {'ok':True}

    @app.post('/api/jobs/retry-failed')
    def retry_failed(project_id:int|None=None):
        if project_id is None:
            raise HTTPException(422,'Phải chọn project_id để tránh chạy lại nhầm dự án')
        if not store.one('SELECT id FROM projects WHERE id=?',(project_id,)):
            raise HTTPException(404,'Không tìm thấy dự án')
        # Skip ambiguous jobs: user must inspect and explicitly confirm one-by-one.
        rows=store.query("SELECT * FROM jobs WHERE state='failed' AND project_id=?",(project_id,))
        retried=0; skipped=[]
        for row in rows:
            try:
                perform_retry(row)
                retried+=1
            except HTTPException:
                skipped.append(row['id'])
        return {'ok':True,'retried':retried,'skipped':skipped}

    @app.get('/media/{folder}/{name}')
    def media(folder:str,name:str):
        if folder not in ('output','references') or not re.fullmatch(r'[a-zA-Z0-9_\-]+\.(png|jpg|jpeg|webp|mp4)',name):
            raise HTTPException(404,'Không tìm thấy file')
        path=store.root/folder/name
        if not path.is_file(): raise HTTPException(404,'Không tìm thấy file')
        return FileResponse(path)

    app.mount('/', StaticFiles(directory=APP_DIR/'static',html=True), name='frontend')
    return app

app=create_app()
