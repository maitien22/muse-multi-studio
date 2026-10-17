"""Real concurrent executor with atomic media publication and cost-aware recovery."""
import base64
import concurrent.futures
import os
import threading
import uuid
from pathlib import Path
from .media_validation import verify_media, normalize_image
from .providers import generate, download_media, JobCanceled, ProviderTerminalError
from .store import stamp


class JobInterrupted(Exception):
    """Local backend is closing; persist remote ID for resumable fal requests."""


class Engine:
    def __init__(self, store, provider_func=generate, download_func=download_media):
        self.store=store
        self.provider_func=provider_func
        self.download_func=download_func
        self.worker_count=max(1,min(8,int(store.get_setting('workers','2'))))
        self.paused=True  # Safe restart: requires explicit user confirmation before billing.
        self.stopping=threading.Event()
        self.thread=None
        self.active={}
        self.lock=threading.RLock()

    def start(self):
        # A crash during a paid POST without a saved remote request ID is ambiguous.
        # Never silently submit such requests a second time after restart.
        self.store.execute("""UPDATE jobs SET state='failed',remote_stage='ambiguous',
            error='Ứng dụng dừng khi chưa lưu remote ID; phải xác minh trước khi gửi yêu cầu tính phí mới',
            finished_at=? WHERE state='running' AND remote_id IS NULL AND cancel_requested=0""",(stamp(),))
        self.store.execute("UPDATE jobs SET state='queued' WHERE state='running' AND remote_id IS NOT NULL AND cancel_requested=0")
        self.store.execute("UPDATE jobs SET state='canceled',finished_at=? WHERE state='running' AND cancel_requested=1",(stamp(),))
        if not self.thread or not self.thread.is_alive():
            self.stopping.clear()
            self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=8,thread_name_prefix='muse-worker')
            self.thread=threading.Thread(target=self._schedule,name='muse-scheduler',daemon=True)
            self.thread.start()

    def shutdown(self):
        self.paused=True
        self.stopping.set()
        if self.thread:self.thread.join(timeout=1)
        if hasattr(self,'pool'):self.pool.shutdown(wait=False,cancel_futures=True)

    def _schedule(self):
        while not self.stopping.is_set():
            with self.lock:
                for jid,future in list(self.active.items()):
                    if future.done():
                        del self.active[jid]
                if not self.paused:
                    while len(self.active)<self.worker_count:
                        job=self.store.claim()
                        if not job:break
                        self.active[job['id']]=self.pool.submit(self._work,job)
            self.stopping.wait(.15)

    def status(self):
        with self.lock:
            return {'paused':self.paused,'workers':self.worker_count,'active':len(self.active)}

    def _work(self,job):
        jid=job['id']
        account=self.store.get_account(job['account_id'])
        published=[]
        staged=[]
        remote_result=False

        def canceled():
            row=self.store.one('SELECT cancel_requested FROM jobs WHERE id=?',(jid,))
            if self.stopping.is_set():raise JobInterrupted()
            return bool(row and row['cancel_requested'])

        def remote(rid,endpoint):
            self.store.update_job(jid,remote_id=rid,endpoint=endpoint,remote_stage='submitted')

        def remote_status(_):
            self.store.update_job(jid,progress=None)

        def set_stage(stage):
            self.store.update_job(jid,remote_stage=stage)

        try:
            if not account:raise ValueError('Tài khoản đã bị xóa')
            if not job['remote_id']:
                set_stage('submitting')
            results=self.provider_func(job,account,self.store,remote,remote_status,canceled)
            remote_result=True
            if not results:raise ValueError('Nhà cung cấp không trả kết quả')
            set_stage('result_ready')
            if canceled():raise JobCanceled()
            for item in results:
                if canceled():raise JobCanceled()
                ext='.mp4' if job['kind']=='video' else '.img'
                fname=f'{jid}_{uuid.uuid4().hex[:16]}{ext}'
                stage=self.store.root/'output'/('.pending_'+fname)
                staged.append(stage)
                if isinstance(item,dict) and 'b64_json' in item:
                    raw=base64.b64decode(item['b64_json'],validate=True)
                    if len(raw)>40*1024*1024:raise ValueError('Ảnh vượt 40MB')
                    stage.write_bytes(raw)
                else:
                    self.download_func(item,stage,account['proxy'])
                verify_media(stage,job['kind'])
                if job['kind']=='image':
                    normalize_image(stage,job['ratio'])
                    verify_media(stage,job['kind'])
                # Keep existing media type for browser/download compatibility.
                if job['kind']=='image':
                    from PIL import Image
                    with Image.open(stage) as im:
                        ext={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp'}[im.format]
                final=self.store.root/'output'/(fname.rsplit('.',1)[0]+ext)
                os.replace(stage,final)
                staged.remove(stage)
                published.append(final)
            if canceled():raise JobCanceled()
            self.store.commit_assets(jid,[x.name for x in published],job['kind'])
            published.clear()
        except JobCanceled:
            self.store.update_job(jid,state='canceled',finished_at=stamp())
        except JobInterrupted:
            # Remote state can be safely resumed only with a persisted request ID.
            row=self.store.one('SELECT remote_id FROM jobs WHERE id=?',(jid,))
            if not row or not row['remote_id']:
                self.store.update_job(jid,state='failed',remote_stage='ambiguous',
                    error='Ứng dụng đóng khi request chưa có ID; cần xác minh trước khi chạy lại',finished_at=stamp())
        except ProviderTerminalError as exc:
            self.store.update_job(jid,state='failed',remote_stage='provider_failed',
                error=self._sanitize(exc,account),finished_at=stamp())
        except Exception as exc:
            row=self.store.one('SELECT remote_id,remote_stage FROM jobs WHERE id=?',(jid,)) or {}
            if remote_result:
                stage='download_failed' if row.get('remote_id') else 'ambiguous'
            elif row.get('remote_id'):
                stage='submitted'  # keep known ID; safe to poll same request on retry
            elif row.get('remote_stage')=='provider_failed':
                stage='provider_failed'
            else:
                stage='ambiguous'  # unknown if billed; force confirmation to resubmit
            self.store.update_job(jid,state='failed',remote_stage=stage,
                error=self._sanitize(exc,account),finished_at=stamp())
        finally:
            # No partial gallery rows: rollback staged and promoted files on failures.
            for f in staged+published:
                f.unlink(missing_ok=True)

    @staticmethod
    def _sanitize(exc,account):
        msg=str(exc)
        if account:
            for secret in (account.get('secret'),account.get('proxy')):
                if secret:msg=msg.replace(secret,'[REDACTED]')
        return msg[:900]
