"""AI note Studio: additive five-stage production workflow.
Install alongside server.py, then add at the END of server.py:
    from studio_upgrade import install_studio_upgrade
    install_studio_upgrade(app, ai, connect, LOCK, now, writer_os, auth)
Does not replace existing routes or database tables.
"""
import json
import re
import sqlite3
from datetime import datetime
from html import escape
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

STAGES = ('ideas', 'outline', 'writing', 'titles', 'listing')
STAGE_LABELS = {'ideas':'ネタ出し','outline':'構成','writing':'文章','titles':'タイトル','listing':'出品準備'}

class StudioInput(BaseModel):
    stage: str = 'ideas'
    topic: str = Field(default='', max_length=500)
    official_title: str = Field(default='', max_length=500)
    audience: str = Field(default='', max_length=500)
    price: int | None = Field(default=None, ge=100, le=100000)
    article_type: str = 'paid'
    context: str = Field(default='', max_length=50000)
    previous: dict = Field(default_factory=dict)

class StudioUpdate(BaseModel):
    topic: str | None = Field(default=None, max_length=500)
    official_title: str | None = Field(default=None, max_length=500)
    audience: str | None = Field(default=None, max_length=500)
    price: int | None = Field(default=None, ge=100, le=100000)


def install_studio_upgrade(app, ai, connect, lock, now, writer_os, auth):
    with connect() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS studio_projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL,
            official_title TEXT NOT NULL DEFAULT '', audience TEXT NOT NULL DEFAULT '',
            price INTEGER, article_type TEXT NOT NULL DEFAULT 'paid',
            status TEXT NOT NULL, current_stage TEXT NOT NULL DEFAULT '',
            outputs TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')

    def build_context(p, outputs):
        known = {'topic':p.topic.strip(), 'official_title':p.official_title.strip(),
                 'audience':p.audience.strip(), 'price':p.price,
                 'article_type':p.article_type}
        return ('【ユーザー指定条件】\n' + json.dumps(known, ensure_ascii=False) +
                '\nタイトルが指定済みなら変更しない。価格がnullなら金額を創作しない。'
                '\n読者の問題を直接解決し、根拠のない数値・購入率・販売実績を創作しない。'
                '\n出品準備は実際のnote公開ではない。\n' +
                '【前工程の成果】\n' + json.dumps(outputs, ensure_ascii=False)[:85000] +
                '\n【参考情報】\n' + p.context[:25000])

    def run_stage(stage, p, outputs):
        ctx = build_context(p, outputs)
        if stage == 'ideas':
            prompt = ('ネタ出し担当。対象読者の具体的な悩みを起点に、note記事テーマを5件提案。'
                      '各案に読者状況、知りたい答え、無料/有料の適性と理由、独自の実用価値、'
                      '購入需要の検証方法を記す。外部調査未実施なら未検証と明記。'
                      '売れると断言しない。ユーザー指定テーマがあればそれを中心に展開。')
            return ai('research', prompt, ctx, max_tokens=3500)
        if stage == 'outline':
            prompt = ('構成担当。入力テーマとネタ出しの結果から読者の核心問題と直接回答を確定し、'
                      '無料部分と有料部分の独立した価値を設計。記事タイプがfreeなら無料記事だけ。'
                      '有料なら購入前に渡す価値と購入後の実用的追加価値を分ける。'
                      '章番号・章数・文字数を強制せず、各見出しに新しい解決価値を持たせる。'
                      '制作メモとして構成案を出力。')
            return ai('writer', prompt, ctx, max_tokens=4500)
        if stage == 'writing':
            prompt = ('記事本文担当。前工程の構成を踏まえ、コピーして使える完成原稿を執筆。'
                      '有料記事なら【無料部分】と【有料部分】を分ける。'
                      '無料記事なら無料部分だけを書く。読者が最初に求める答えを先に示し、'
                      '判断条件・実際の手順・例外時の対応を具体化。'
                      'タイトルが指定済みなら完全一致で使用。価格が未指定なら価格は書かない。'
                      '不必要な章番号や文字数水増し、制作メモ、虚偽の特典を禁止。')
            return ai('writer', prompt, ctx, max_tokens=14000)
        if stage == 'titles':
            prompt = ('タイトル選出担当。完成原稿の内容に合うタイトル候補を5件示し、'
                      '想定読者の「読みたい／読みたくない」と具体的な理由、'
                      '無料向き／有料向きと理由を比較する。点数化は禁止。'
                      '正式タイトルが指定済みなら変更提案は参考候補として区別し、'
                      '採用タイトルは指定タイトルをそのまま保持する。'
                      '未指定なら最も内容と一致するタイトルを1件選ぶ。')
            return ai('research', prompt, ctx, max_tokens=3600)
        if stage == 'listing':
            prompt = ('note出品準備担当。原稿と確定タイトルに基づき、出品時の紹介文、'
                      '無料/有料区切りの確認事項、タグ案、コピーして使える公開前チェック、'
                      'SNS告知案を作成。価格が未指定なら価格欄は未設定とする。'
                      '実際の公開・投稿・決済連携・売上取得は行わず、行ったと主張しない。'
                      '原稿に存在しない特典を約束しない。')
            return ai('manager', prompt, ctx, max_tokens=4200)
        raise HTTPException(422, '不正な工程です')

    def create_project(p):
        if p.article_type not in ('paid','free'):
            raise HTTPException(422, 'article_type は paid または free')
        if not p.topic.strip():
            raise HTTPException(422, 'テーマを入力してください')
        ts = now()
        with lock, connect() as c:
            cur = c.execute('INSERT INTO studio_projects(topic,official_title,audience,price,article_type,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                            (p.topic.strip(),p.official_title.strip(),p.audience.strip(),p.price,p.article_type,'running',ts,ts))
            return cur.lastrowid

    def save_project(pid, stage, outputs, status='running', error=''):
        with lock, connect() as c:
            c.execute('UPDATE studio_projects SET outputs=?,current_stage=?,status=?,error=?,updated_at=? WHERE id=?',
                      (json.dumps(outputs,ensure_ascii=False),stage,status,error,now(),pid))

    @app.post('/api/studio/stage')
    def studio_stage(p: StudioInput, _=Depends(auth)):
        if p.stage not in STAGES:
            raise HTTPException(422, '不正な工程です')
        if p.article_type not in ('paid','free'):
            raise HTTPException(422, 'article_type は paid または free')
        if not p.topic.strip() and p.stage != 'ideas':
            raise HTTPException(422, 'テーマを入力してください')
        if not isinstance(p.previous,dict):
            raise HTTPException(422, 'previous はオブジェクトが必要です')
        try:
            result = run_stage(p.stage,p,p.previous)
        except Exception as exc:
            raise HTTPException(502, 'AI処理に失敗しました: '+str(exc)[:220])
        return {'stage':p.stage,'label':STAGE_LABELS[p.stage],'output':result,'published':False}

    @app.post('/api/studio/run')
    def studio_run(p: StudioInput, _=Depends(auth)):
        # Synchronous endpoint: keeps a durable checkpoint after each step.
        pid = create_project(p)
        outputs = {}
        for stage in STAGES:
            try:
                outputs[stage] = run_stage(stage,p,outputs)
                save_project(pid,stage,outputs)
            except Exception as exc:
                save_project(pid,stage,outputs,'error',str(exc)[:300])
                raise HTTPException(502, f'{STAGE_LABELS[stage]}で停止。案件#{pid}に完了工程を保存しました: {str(exc)[:160]}')
        save_project(pid,'listing',outputs,'pending_approval')
        return {'id':pid,'status':'pending_approval','outputs':outputs,'published':False}

    @app.get('/api/studio/projects')
    def studio_projects(_=Depends(auth)):
        with connect() as c:
            rows = c.execute('SELECT id,topic,official_title,audience,price,article_type,status,current_stage,error,created_at,updated_at FROM studio_projects ORDER BY id DESC LIMIT 50').fetchall()
        return {'projects':[dict(r) for r in rows]}

    @app.get('/api/studio/projects/{pid}')
    def studio_project(pid:int,_=Depends(auth)):
        with connect() as c:
            row=c.execute('SELECT * FROM studio_projects WHERE id=?',(pid,)).fetchone()
        if not row:raise HTTPException(404,'案件がありません')
        result=dict(row)
        result['outputs']=json.loads(result['outputs'] or '{}')
        return result

    @app.post('/api/studio/projects/{pid}/settings')
    def studio_project_settings(pid:int,p:StudioUpdate,_=Depends(auth)):
        with lock,connect() as c:
            row=c.execute('SELECT * FROM studio_projects WHERE id=?',(pid,)).fetchone()
            if not row:raise HTTPException(404,'案件がありません')
            if row['status']=='running':raise HTTPException(409,'制作中は設定変更できません')
            changes=p.model_dump(exclude_unset=True)
            if not changes:return {'ok':True,'changed':False}
            if 'topic' in changes and not (changes['topic'] or '').strip():
                raise HTTPException(422,'テーマは空にできません')
            for key in ('topic','official_title','audience'):
                if key in changes:changes[key]=(changes[key] or '').strip()
            cols=','.join(k+'=?' for k in changes)
            c.execute('UPDATE studio_projects SET '+cols+",status='needs_revision',updated_at=? WHERE id=?",(*changes.values(),now(),pid))
        return {'ok':True,'changed':True,'requires_regeneration':True,'published':False}

    @app.get('/api/studio/projects/{pid}/html')
    def studio_html(pid:int,_=Depends(auth)):
        with connect() as c:
            row=c.execute('SELECT * FROM studio_projects WHERE id=?',(pid,)).fetchone()
        if not row:raise HTTPException(404,'案件がありません')
        outputs=json.loads(row['outputs'] or '{}')
        article=outputs.get('writing','')
        if not article:raise HTTPException(409,'原稿がありません')
        title=row['official_title'] or row['topic']
        html='<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(title)+'</title><style>body{max-width:760px;margin:40px auto;padding:0 18px;font:17px/1.9 system-ui,sans-serif;color:#24352f}article{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body><article>'+escape(article)+'</article></body></html>'
        return HTMLResponse(html,headers={'Content-Disposition':f'attachment; filename="note-{pid}.html"'})
