"""SQLite persistence and encrypted local provider credentials."""
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from cryptography.fernet import Fernet


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ('output', 'references'):
            (self.root / folder).mkdir(exist_ok=True)
        self.db_path = self.root / 'muse.db'
        key_file = self.root / 'credential.key'
        if not key_file.exists():
            with open(key_file, 'xb') as f:
                f.write(Fernet.generate_key())
            if os.name != 'nt':
                key_file.chmod(0o600)
        self.cipher = Fernet(key_file.read_bytes())
        self.lock = threading.RLock()
        with sqlite3.connect(self.db_path) as first_db:
            first_db.execute('PRAGMA journal_mode = WAL')
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS projects (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS accounts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL,
              provider TEXT NOT NULL CHECK(provider IN ('fal','openai')),
              secret TEXT NOT NULL,
              proxy_secret TEXT DEFAULT '',
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              prompt TEXT NOT NULL,
              project_id INTEGER NOT NULL DEFAULT 1,
              sort_index INTEGER NOT NULL DEFAULT 0,
              kind TEXT NOT NULL CHECK(kind IN ('image','video')),
              account_id INTEGER NOT NULL,
              ratio TEXT NOT NULL,
              duration INTEGER NOT NULL DEFAULT 5,
              ref_name TEXT,
              state TEXT NOT NULL DEFAULT 'queued',
              remote_id TEXT,
              endpoint TEXT,
              progress INTEGER,
              error TEXT,
              cancel_requested INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT,
              FOREIGN KEY(account_id) REFERENCES accounts(id)
            );
            CREATE TABLE IF NOT EXISTS assets (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_id INTEGER NOT NULL REFERENCES jobs(id),
              filename TEXT NOT NULL,
              kind TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state,id);
            ''')
            columns=[r[1] for r in db.execute('PRAGMA table_info(jobs)').fetchall()]
            if 'project_id' not in columns: db.execute('ALTER TABLE jobs ADD COLUMN project_id INTEGER NOT NULL DEFAULT 1')
            if 'sort_index' not in columns: db.execute('ALTER TABLE jobs ADD COLUMN sort_index INTEGER NOT NULL DEFAULT 0')
            if 'remote_stage' not in columns: db.execute("ALTER TABLE jobs ADD COLUMN remote_stage TEXT NOT NULL DEFAULT 'new'")
            # Convert legacy asset rows to independent library entries (survive job deletion).
            cols={r[1] for r in db.execute('PRAGMA table_info(assets)')}
            keys=db.execute('PRAGMA foreign_key_list(assets)').fetchall()
            if 'prompt' not in cols or any(k[3]=='job_id' and str(k[6]).upper()!='SET NULL' for k in keys):
                db.execute('''CREATE TABLE assets_new (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER REFERENCES jobs(id) ON DELETE SET NULL,
                    filename TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,created_at TEXT NOT NULL,
                    prompt TEXT NOT NULL DEFAULT '',account_id INTEGER)''')
                db.execute('''INSERT INTO assets_new(id,job_id,filename,kind,created_at,prompt,account_id)
                    SELECT a.id,a.job_id,a.filename,a.kind,a.created_at,COALESCE(j.prompt,''),j.account_id
                    FROM assets a LEFT JOIN jobs j ON a.job_id=j.id''')
                db.execute('DROP TABLE assets')
                db.execute('ALTER TABLE assets_new RENAME TO assets')
            # Preserve legacy fal request IDs: never treat them as safe fresh submissions.
            db.execute("UPDATE jobs SET remote_stage='submitted' WHERE remote_id IS NOT NULL AND remote_stage='new'")
            db.execute("UPDATE jobs SET remote_stage='ambiguous' WHERE state='failed' AND remote_id IS NULL AND remote_stage='new'")
            db.execute("INSERT OR IGNORE INTO settings(name,value) VALUES('workers','2')")
            db.execute('INSERT OR IGNORE INTO projects(id,name,created_at) VALUES(1,?,?)',('Mặc định',stamp()))
            db.execute('UPDATE jobs SET sort_index=id WHERE sort_index=0')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        db.execute('PRAGMA busy_timeout = 30000')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def query(self, sql, params=()):
        with self.connect() as db:
            return [dict(x) for x in db.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        found = self.query(sql, params)
        return found[0] if found else None

    def execute(self, sql, params=()):
        with self.connect() as db:
            cursor = db.execute(sql, params)
            return cursor.lastrowid

    def list_projects(self):
        return self.query('SELECT id,name FROM projects ORDER BY id')

    def add_project(self, name):
        return self.execute('INSERT INTO projects(name,created_at) VALUES(?,?)',(name,stamp()))

    def get_setting(self, name, default=None):
        row=self.one('SELECT value FROM settings WHERE name=?',(name,))
        return row['value'] if row else default

    def set_setting(self, name, value):
        self.execute('INSERT INTO settings(name,value) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET value=excluded.value', (name,str(value)))

    def renumber(self, project_id):
        with self.connect() as db:
            ids=[r[0] for r in db.execute('SELECT id FROM jobs WHERE project_id=? ORDER BY sort_index DESC,id DESC',(project_id,))]
            for i,jid in enumerate(ids):
                db.execute('UPDATE jobs SET sort_index=? WHERE id=?',(len(ids)-i,jid))
            return len(ids)

    def add_account(self, name, provider, secret, proxy=''):
        return self.execute('INSERT INTO accounts(name,provider,secret,proxy_secret,created_at) VALUES (?,?,?,?,?)',
            (name, provider, self.cipher.encrypt(secret.encode()).decode(), self.cipher.encrypt(proxy.encode()).decode() if proxy else '', stamp()))

    def list_accounts(self):
        return [{'id': a['id'], 'name': a['name'], 'provider': a['provider'], 'has_proxy': bool(a['proxy_secret'])} for a in self.query('SELECT * FROM accounts ORDER BY id')]

    def get_account(self, aid):
        a = self.one('SELECT * FROM accounts WHERE id=?', (aid,))
        if a:
            a['secret'] = self.cipher.decrypt(a['secret'].encode()).decode()
            a['proxy'] = self.cipher.decrypt(a['proxy_secret'].encode()).decode() if a['proxy_secret'] else ''
        return a

    def queue(self, prompts, kind, aid, ratio, duration, ref_names, project_id=1):
        with self.connect() as db:
            ids = []
            for prompt, ref_name in zip(prompts,ref_names):
                cur = db.execute('INSERT INTO jobs(prompt,project_id,kind,account_id,ratio,duration,ref_name,state,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                    (prompt,project_id,kind,aid,ratio,duration,ref_name,'queued',stamp()))
                ids.append(cur.lastrowid)
                db.execute('UPDATE jobs SET sort_index=? WHERE id=?',(cur.lastrowid,cur.lastrowid))
            return ids

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE state='queued' AND cancel_requested=0 ORDER BY sort_index DESC,id DESC LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET state='running',started_at=?,progress=NULL WHERE id=?", (stamp(),row['id']))
            job = dict(row)
            job['state'] = 'running'
            return job

    def update_job(self, job_id, **fields):
        allowed = {'state','remote_id','endpoint','remote_stage','progress','error','cancel_requested','started_at','finished_at'}
        assert fields and fields.keys() <= allowed
        return self.execute('UPDATE jobs SET ' + ','.join(f'{f}=?' for f in fields) + ' WHERE id=?', (*fields.values(), job_id))

    def jobs(self, limit=None, offset=0, project_id=None):
        sql='''SELECT j.*, a.name as account_name, a.provider,
            (SELECT filename FROM assets WHERE job_id=j.id ORDER BY id LIMIT 1) as first_asset
            FROM jobs j LEFT JOIN accounts a ON a.id=j.account_id'''
        params=[]
        if project_id is not None:
            sql+=' WHERE j.project_id=?';params.append(project_id)
        sql+=' ORDER BY j.sort_index DESC,j.id DESC'
        if limit is not None:
            sql+=' LIMIT ? OFFSET ?';params.extend([limit,offset])
        rows=self.query(sql,tuple(params))
        for j in rows:
            j['asset_url'] = '/media/output/' + j['first_asset'] if j['first_asset'] else None
            j.pop('first_asset')
            j['reference_url'] = '/media/references/' + j['ref_name'] if j['ref_name'] else None
        return rows

    def commit_assets(self, job_id, filenames, kind):
        # Asset registration and DONE status form one database transaction.
        with self.connect() as db:
            row=db.execute('SELECT prompt,account_id,cancel_requested FROM jobs WHERE id=?',(job_id,)).fetchone()
            if not row or row['cancel_requested']:
                raise RuntimeError('Tác vụ không còn hợp lệ hoặc đã yêu cầu hủy')
            for filename in filenames:
                db.execute('INSERT INTO assets(job_id,filename,kind,created_at,prompt,account_id) VALUES(?,?,?,?,?,?)',
                           (job_id,filename,kind,stamp(),row['prompt'],row['account_id']))
            db.execute("UPDATE jobs SET state='done',progress=100,error=NULL,finished_at=?,remote_stage='complete' WHERE id=?",(stamp(),job_id))

    def add_asset(self, job_id, filename, kind):
        row=self.one('SELECT prompt,account_id FROM jobs WHERE id=?',(job_id,))
        return self.execute('INSERT INTO assets(job_id,filename,kind,created_at,prompt,account_id) VALUES(?,?,?,?,?,?)',
                            (job_id,filename,kind,stamp(),(row or {}).get('prompt',''),(row or {}).get('account_id')))

    def assets(self):
        arr = self.query('SELECT a.* FROM assets a ORDER BY a.id DESC')
        for item in arr:
            item['url']='/media/output/'+item['filename']
        return arr
