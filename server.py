import os, json, sqlite3, datetime, threading, secrets
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
DB = Path(os.getenv('DATABASE_PATH', str(ROOT / 'studio.db')))
DB.parent.mkdir(parents=True, exist_ok=True)
app = FastAPI(title='AI note Studio')
LOCK = threading.RLock()
ROLES = {
 'research': ('需要調査AI', '市場データを捏造しない。調査できない事実は未検証と記す。読者の悩みとテーマ候補を整理する。'),
 'writer': ('記事制作AI', '有料note自動完成OSに従い、深層読者理解、核心解決設計、無料・有料の価値分担を重視する。架空の実績は書かない。'),
 'audit': ('品質監査AI', '読者・需要・競合・独自性・具体性・実践性・価格・期待一致・表現・リスクの10観点で監査し、修正版を完成させる。'),
 'social': ('SNS宣伝AI', 'X 160字以内とThreads用の投稿案を作る。売上や効果を捏造しない。'),
 'analytics': ('分析AI', '実測データだけで分析。未取得は未取得と明記。'),
 'manager': ('運営管理AI', '計画・承認ポイントを整理。外部公開を完了したと偽らない。')
}

def connect():
 c = sqlite3.connect(DB, timeout=30, check_same_thread=False)
 c.row_factory = sqlite3.Row
 return c

with connect() as c:
 c.execute('CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, task TEXT, output TEXT, status TEXT, created_at TEXT)')
 c.execute('CREATE TABLE IF NOT EXISTS metrics (id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT, impressions INTEGER, views INTEGER, likes INTEGER, sales INTEGER, revenue INTEGER)')
 c.execute('CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY AUTOINCREMENT, status TEXT NOT NULL, stage TEXT, topic TEXT, research TEXT DEFAULT "", draft TEXT DEFAULT "", article TEXT DEFAULT "", social TEXT DEFAULT "", decision TEXT DEFAULT "", error TEXT DEFAULT "", created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL)')

def now():
 return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')

def auth(request: Request):
 password = os.getenv('ADMIN_PASSWORD', '')
 if not password:
  raise HTTPException(503, 'ADMIN_PASSWORD must be configured')
 header = request.headers.get('authorization', '')
 import base64
 try:
  scheme, token = header.split(' ', 1)
  raw = base64.b64decode(token).decode('utf-8') if scheme.lower() == 'basic' else ''
  user, passwd = raw.split(':', 1)
 except Exception:
  user = passwd = ''
 if not (secrets.compare_digest(user, 'admin') and secrets.compare_digest(passwd, password)):
  raise HTTPException(401, 'ログインが必要です', headers={'WWW-Authenticate': 'Basic realm="AI note Studio"'})
 return True

WRITER_OS_PATH = ROOT / 'os' / 'writer.md'

def writer_os():
 if not WRITER_OS_PATH.is_file():
  raise RuntimeError('os/writer.md が見つかりません。OS全文をこのファイルに保存してください。')
 content = WRITER_OS_PATH.read_text(encoding='utf-8').strip()
 if len(content) < 3000:
  raise RuntimeError('os/writer.md の内容が短すぎます。有料note自動完成OSの全文を保存してください。')
 return content

def ai(role, task, context='', *, max_tokens=3500, system_extra=''):
 if not os.getenv('OPENAI_API_KEY'):
  raise RuntimeError('OPENAI_API_KEY が未設定です')
 name, instruction = ROLES[role]
 system = f'あなたは{name}。{instruction} 出力は日本語。インターネット検索・note公開・SNS投稿は行っていないことを明示。根拠のない数字を作らない。'
 if role == 'writer':
  system += '\n\n以下は必ず従う記事制作OS全文です。既存の短い指示より優先します。\n' + writer_os()
 if system_extra:
  system += '\n\n追加の制作指示:\n' + system_extra
 result = OpenAI(api_key=os.environ['OPENAI_API_KEY'], timeout=180, max_retries=1).chat.completions.create(
  model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
  messages=[{'role':'system','content':system}, {'role':'user','content':f'{task}\n\n参考情報:\n{context[:30000]}'}],
  max_tokens=max_tokens
 )
 choice = result.choices[0]
 if choice.finish_reason == 'length':
  raise RuntimeError(f'{role} の出力が上限に達しました。OPENAI_MODELまたは出力上限の調整が必要です。')
 return choice.message.content or '(出力なし)'

def create_paid_note(ctx, research):
 """記事制作OSのみを利用して設計→無料→有料を分割生成。独立監査はここで行わない。"""
 base = ctx + '\n需要調査AIによる企画仮説（実市場調査ではない）:\n' + research
 plan = ai('writer',
  '有料note自動完成OSのSTEP1〜11を内部設計として実行。表面の悩み・深い悩み・本当に欲しい答え・主対象読者・中心問題・商品タイプ・核心解決設計7要素・購入後の到達状態・無料/有料の分担・有料部分の章構成を具体的に設計する。需要未検証を明記。これは制作メモであり、本文ではない。指定タイトル・価格は変更しない。',
  base, max_tokens=3000)
 free = ai('writer',
  '上記設計に従い、有料noteの【無料部分】だけを完成原稿として執筆する。冒頭1〜3文に引力を持たせ、無料部分だけでも重要な答えと最初の判断を提供する。約1000日本語文字を目安に、販売文と有料部分への自然な接続まで含める。制作メモや内部分析は出さない。正式タイトルが入力されている場合は必ず保持する。',
  base + '\n設計:\n' + plan, max_tokens=2600)
 paid = ai('writer',
  '上記設計に従い、有料noteの【有料部分】の完成原稿全文を執筆する。中心問題への直接回答、解決原則、判断基準、状況別対応、具体例、必要な実践手順、判断不能時の対応、読後の到達状態を具体化する。商品タイプに不必要な手順を強制しない。無料部分の言い換えは避ける。章立ては設計に従う。制作報告や監査結果は出さない。',
  base + '\n設計:\n' + plan + '\n無料部分:\n' + free,
  max_tokens=6500)
 return '【無料部分】\n' + free.strip() + '\n\n【有料部分】\n' + paid.strip()

class JobIn(BaseModel):
 role: str
 task: str = Field(min_length=3, max_length=10000)
 context: str = ''
class MetricIn(BaseModel):
 day: str
 impressions: int = Field(ge=0, default=0)
 views: int = Field(ge=0, default=0)
 likes: int = Field(ge=0, default=0)
 sales: int = Field(ge=0, default=0)
 revenue: int = Field(ge=0, default=0)
class SettingsIn(BaseModel):
 topic: str = Field(min_length=3, max_length=500)
 audience: str = Field(default='note初心者', max_length=500)
 price: int = Field(default=1980, ge=100, le=100000)
 note_url: str = Field(default='', max_length=500)
class DecisionIn(BaseModel):
 decision: str

@app.get('/')
def home(_: bool = Depends(auth)):
 return FileResponse(ROOT / 'static' / 'index.html')
@app.get('/api/status')
def status(_: bool = Depends(auth)):
 with connect() as c:
  jobs = [dict(r) for r in c.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT 50')]
  metrics = [dict(r) for r in c.execute('SELECT * FROM metrics ORDER BY id DESC LIMIT 30')]
  runs = [dict(r) for r in c.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 30')]
  settings = {r['key']:r['value'] for r in c.execute('SELECT * FROM settings')}
 return {'connected':bool(os.getenv('OPENAI_API_KEY')),'jobs':jobs,'metrics':metrics,'runs':runs,'settings':settings,'roles':{k:v[0] for k,v in ROLES.items()}}
@app.post('/api/jobs')
def job(payload: JobIn, _: bool = Depends(auth)):
 if payload.role not in ROLES:
  raise HTTPException(400, 'Unknown role')
 created = now()
 with LOCK, connect() as c:
  cur = c.execute('INSERT INTO jobs(role,task,output,status,created_at) VALUES(?,?,?,?,?)',(payload.role,payload.task,'','running',created))
  jid = cur.lastrowid
 try:
  output = ai(payload.role,payload.task,payload.context, max_tokens=6500 if payload.role=='writer' else 3500)
  state = 'done'
 except Exception as exc:
  output = f'AI処理エラー: {str(exc)[:250]}'
  state = 'error'
 with LOCK, connect() as c:
  c.execute('UPDATE jobs SET output=?,status=? WHERE id=?',(output,state,jid))
 return {'id':jid,'role':payload.role,'task':payload.task,'output':output,'status':state,'created_at':created}
@app.post('/api/metrics')
def metric(payload: MetricIn, _: bool = Depends(auth)):
 try:
  datetime.date.fromisoformat(payload.day)
 except ValueError:
  raise HTTPException(400, '日付形式は YYYY-MM-DD')
 with LOCK, connect() as c:
  c.execute('INSERT INTO metrics(day,impressions,views,likes,sales,revenue) VALUES(?,?,?,?,?,?)',(payload.day,payload.impressions,payload.views,payload.likes,payload.sales,payload.revenue))
 return {'ok':True}
@app.post('/api/settings')
def save_settings(p: SettingsIn, _: bool = Depends(auth)):
 with LOCK, connect() as c:
  for k,v in p.model_dump().items():
   c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(v)))
 return {'ok':True}

def update(run_id, **fields):
 fields['updated_at'] = now()
 with LOCK, connect() as c:
  c.execute('UPDATE runs SET '+','.join(f'{k}=?' for k in fields)+' WHERE id=?',(*fields.values(),run_id))

def pipeline(run_id, config):
 try:
  topic = config.get('topic','note初心者向けの有料noteの作り方')
  ctx = f'テーマ:{topic}\n読者:{config.get("audience","note初心者")}\n価格:{config.get("price","1980")}円\nユーザー指定の正式タイトルがある場合は変更禁止。'
  update(run_id, stage='需要調査')
  research = ai('research','このテーマの読者課題、競合との差別化仮説、記事設計を提案。実際の市場調査をしたと主張しない。',ctx)
  update(run_id, stage='記事制作・深層設計', research=research)
  draft = create_paid_note(ctx, research)
  update(run_id, stage='品質監査・修正', draft=draft)
  # 既存の監査工程を維持する（監査OSは追加しない）。
  article = ai('audit',
   '10観点で厳格に監査し、問題点を短く列挙したあと、修正済みの完成原稿全文を出力する。',
   ctx+'\n原稿:\n'+draft)
  update(run_id, stage='SNS投稿準備', article=article)
  social = ai('social','以下の原稿を宣伝するX向け投稿を3つ、Threads向けを2つ作成。投稿は実行しない。',ctx+'\n記事:\n'+draft[:12000]+'\nnote URL:'+config.get('note_url','未設定'))
  update(run_id, stage='承認待ち', social=social, status='pending_approval')
 except Exception as exc:
  update(run_id, status='error', stage='失敗', error=str(exc)[:400])

def launch():
 with LOCK, connect() as c:
  active = c.execute("SELECT id FROM runs WHERE status IN ('queued','running') LIMIT 1").fetchone()
  if active:
   return {'started':False,'reason':'既に処理中','id':active['id']}
  config = {r['key']:r['value'] for r in c.execute('SELECT * FROM settings')}
  if not config.get('topic'):
   return {'started':False,'reason':'先に自動運営設定を保存してください'}
  if not os.getenv('OPENAI_API_KEY'):
   return {'started':False,'reason':'OPENAI_API_KEY 未設定'}
  if not WRITER_OS_PATH.is_file():
   return {'started':False,'reason':'os/writer.md に有料note自動完成OS全文を保存してください'}
  timestamp = now()
  cur = c.execute('INSERT INTO runs(status,stage,topic,created_at,updated_at) VALUES(?,?,?,?,?)',('running','開始',config['topic'],timestamp,timestamp))
  rid = cur.lastrowid
 threading.Thread(target=pipeline,args=(rid,config),daemon=True).start()
 return {'started':True,'id':rid}
@app.post('/api/runs')
def start(_: bool = Depends(auth)):
 return launch()
@app.post('/api/cron')
def cron(request: Request):
 expected = os.getenv('CRON_SECRET','')
 provided = request.headers.get('x-cron-secret','')
 if not expected or not secrets.compare_digest(provided,expected):
  raise HTTPException(403,'Forbidden')
 return launch()
@app.post('/api/runs/{rid}/decision')
def decide(rid: int, p: DecisionIn, _: bool = Depends(auth)):
 if p.decision not in ('approved','rejected'):
  raise HTTPException(400,'承認または差し戻しを選択してください')
 with LOCK, connect() as c:
  cur = c.execute("UPDATE runs SET status=?,decision=?,updated_at=? WHERE id=? AND status='pending_approval'",(p.decision,p.decision,now(),rid))
  if cur.rowcount != 1:
   raise HTTPException(409,'承認待ちの案件がありません')
 return {'ok':True,'published':False,'message':'承認を記録しました。外部公開は行っていません。'}
@app.get('/health')
def health():
 return {'ok':True}
