"""AI note Studio five-stage workflow with editorial audit and repair.
Drop-in replacement for studio_upgrade.py. Existing server.py integration stays unchanged.
No external publishing is performed.
"""
import json
import logging
from html import escape
from fastapi import Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

LOG = logging.getLogger('ai_note_studio.upgrade')
STAGES = ('ideas', 'outline', 'writing', 'titles', 'listing')
LABELS = {'ideas':'ネタ出し','outline':'構成','writing':'文章','titles':'タイトル','listing':'出品準備'}
PERSPECTIVES = (
    ('読者理解', '想定読者の具体的状況・今困っていること・知りたい答えを正確に扱う'),
    ('問題の優先順位', '購入前の集客課題と購入後のフォローを混同せず、原因と対策の順序を守る'),
    ('核心への回答', '冒頭から読者の中心的な問いに答え、一般論で引き延ばさない'),
    ('無料部分の価値', '無料部分だけでも独立した実用価値があり、予告ばかりにしない'),
    ('有料部分の独自価値', '購入後に初めて得られる実践手順・判断表・具体例が実際に本文にある'),
    ('実行可能性', '状況別の判断・手順・例外・失敗時の代替策がある'),
    ('事実と根拠', '市場・購入率・価格・効果・体験談・数値を捏造せず、架空例は明示する'),
    ('構成と重複', '同じ説明の繰り返しを避け、見出し数や文字数を不必要に固定しない'),
    ('約束との整合', 'タイトル・無料部分・紹介文が実際の有料本文と一致し、架空特典を約束しない'),
    ('購入者保護', '強引な販売や結果保証を避け、購入者が自分で判断できる内容にする'),
)

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
        # Preserve previous outputs; interrupted runs can be resumed explicitly.
        c.execute("UPDATE studio_projects SET status='interrupted',error='サーバー再起動で中断。再実行できます。' WHERE status='running'")

    def check(p, require_topic=True):
        if p.article_type not in ('paid', 'free'):
            raise HTTPException(422, 'article_type は paid または free')
        if require_topic and not p.topic.strip():
            raise HTTPException(422, 'テーマを入力してください')

    def context(p, outputs):
        fixed = {'topic':p.topic.strip(), 'official_title':p.official_title.strip(),
                 'audience':p.audience.strip(), 'price':p.price,
                 'article_type':p.article_type}
        return ('【入力条件（変更禁止）】\n'+json.dumps(fixed,ensure_ascii=False)+
                '\n正式タイトルがあれば完全一致で維持。未指定なら提案してよい。'
                '\n価格がnullなら金額を捏造・補完しない。対象読者が空なら仮説として推定する。'
                '\n外部検索を行っていない場合、市場・競合・購入実績は未検証と明記。'
                '\n販売成功や売上を保証しない。出品準備は実際のnote公開ではない。'
                '\n【これまでの工程】\n'+json.dumps(outputs,ensure_ascii=False)[:115000]+
                '\n【ユーザー参考情報】\n'+p.context[:25000])

    def ask(role, prompt, ctx, tokens=4500, json_mode=False):
        return ai(role, prompt, ctx, max_tokens=tokens, json_mode=json_mode)

    def json_answer(role, prompt, ctx, tokens=4500):
        raw = ask(role, prompt, ctx, tokens, True)
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise RuntimeError('AIのJSON応答が不正です') from exc
        if not isinstance(obj, dict):
            raise RuntimeError('AIのJSON応答がオブジェクトではありません')
        return obj

    def stage(stage_name, p, outputs):
        ctx = context(p, outputs)
        if stage_name == 'ideas':
            return ask('research',
                'ネタ出し担当。テーマを中心に読者が今解決したい問題を深掘りし、候補を最大5件提案。'
                '各候補に読者状況、核心の疑問、具体的に提供できる解決、無料／有料適性と理由、'
                '購入需要を確かめるために必要な公開データを示す。外部調査は行っていないので未検証と記す。'
                '売れると断言しない。', ctx, 3600)
        if stage_name == 'outline':
            return ask('writer',
                '記事構成の制作メモを作る。読者の核心問題→直接回答→解決の順番→実践成果物を設計。'
                '有料記事は無料で完結する価値と有料で初めて得られる追加価値を区別する。'
                '無料記事は無料部分のみ。章数・章番号・文字数を固定しない。'
                '各見出しに別の解決機能を持たせる。',ctx,5500)
        if stage_name == 'writing':
            return ask('writer',
                '完成原稿だけを執筆。前工程の構成を踏まえ、読者が最初に欲しい答えを早く示す。'
                '有料なら【無料部分】と【有料部分】をそれぞれ一度だけ記載。無料なら【無料部分】だけ。'
                '有料部は具体的な診断の仕方、判断基準、実践手順、状況別の分岐、失敗時の対処を実際に書く。'
                '一件も売れていない人に販売後フォローを主要原因として押し付けない。'
                '価格が原因と確認できないまま値下げを勧めない。架空の実績を作らない。'
                '読者が使えると約束したシート等は本文内に実物を掲載する。'
                '正式タイトルがあればそのまま使う。未指定の価格を表示しない。'
                '章番号・固定文字数・制作者向け説明・水増しは禁止。省略せず完成原稿を返す。',ctx,15500)
        if stage_name == 'titles':
            return ask('research',
                '原稿と一致するタイトル候補を5件提示。各候補について想定読者が「読みたい／読みたくない」'
                'のどちらと判断しそうか、理由、無料向き／有料向きと理由を示す。点数禁止。'
                '正式タイトルが指定されている場合は採用タイトルを変えず、他候補は参考案に留める。'
                '未指定なら最も本文に忠実な候補を1件選ぶ。',ctx,4000)
        if stage_name == 'listing':
            return ask('manager',
                '原稿の事実に忠実な出品準備を作る。短く具体的な紹介文、無料／有料区切り、'
                'タグ、公開前の実物照合チェック、SNS告知文。本文にない特典・実績・価格を記載しない。'
                '無料記事なら有料販売を前提にしない。noteへの投稿・公開・決済は行わない。',ctx,4400)
        raise HTTPException(422, '不正な工程です')

    def mechanical_issues(article, p):
        issues=[]
        if not isinstance(article,str) or len(article.strip()) < 350:
            issues.append('原稿が短すぎる、または空です')
            return issues
        if article.count('【無料部分】') != 1:
            issues.append('【無料部分】は一度だけ必要です')
        if p.article_type=='paid' and article.count('【有料部分】') != 1:
            issues.append('有料記事には【有料部分】が一度だけ必要です')
        if p.article_type=='free' and '【有料部分】' in article:
            issues.append('無料記事に有料部分が含まれています')
        if p.official_title.strip() and p.official_title.strip() not in article[:1200]:
            issues.append('指定された正式タイトルが冒頭にありません')
        if p.price is None and __import__('re').search(r'販売価格\s*[：:]\s*[\d,]+\s*円',article):
            issues.append('価格未指定なのに販売価格が記載されています')
        if any(x in article for x in ('ここに本文を','以下省略','本編概要','※以下は一部要約')):
            issues.append('未完成・省略の表現が残っています')
        return issues

    def audit(p, outputs):
        article=outputs.get('writing','')
        if not article:
            raise RuntimeError('文章工程の原稿がありません')
        perspectives=[{'name':name,'check':desc} for name,desc in PERSPECTIVES]
        prompt=('独立した10の専門視点で記事の欠陥を検査する。実際の10人の読者調査ではなくAIによる視点別監査。'
                '採点・点数・架空の購入率は禁止。すべての視点についてpassまたはreviseで判定し、'
                '本文の根拠evidenceと具体的修正指示fixを記載する。根拠がないpassは禁止。'
                '対象視点:'+json.dumps(perspectives,ensure_ascii=False)+'。'
                'JSONオブジェクトのみで返す。形式: '
                '{"checks":[{"name":"視点名","status":"pass または revise","evidence":"本文根拠","fix":"修正指示"}],'
                '"overall":"pass または revise","fix_instructions":"具体的な改稿指示"}。'
                '外部市場調査を実施したと主張しない。')
        data=json_answer('audit',prompt,context(p,{'writing':article}),6500)
        checks=data.get('checks')
        if not isinstance(checks,list) or len(checks)!=len(PERSPECTIVES):
            raise RuntimeError('監査項目が10件揃っていません')
        expected={name for name,_ in PERSPECTIVES}
        found={str(x.get('name','')) for x in checks if isinstance(x,dict)}
        if found!=expected:
            raise RuntimeError('監査視点の名称が不一致です')
        if any(not isinstance(x,dict) or x.get('status') not in ('pass','revise') or not str(x.get('evidence','')).strip() for x in checks):
            raise RuntimeError('監査判定または根拠が不完全です')
        mechanical=mechanical_issues(article,p)
        passed=(all(x['status']=='pass' for x in checks) and not mechanical and data.get('overall')=='pass')
        return {'passed':passed,'verdict':'公開準備候補' if passed else '要修正',
                'checks':checks,'structural_issues':mechanical,
                'fix_instructions':str(data.get('fix_instructions','')),
                'market_verified':False,'competition_verified':False,
                'notice':'AIによる編集監査であり、売上や実際の読者反応を保証しません。'}

    def revise(p, outputs, report):
        old=outputs['writing']
        prompt=('原稿を監査に基づき改訂する。修正が必要な部分を直し、有益な部分を残す。'
                '読者の核心問題・対策の優先順位・具体的手順・有料独自価値・事実性を強化。'
                '指定タイトルを変更せず、価格未指定なら価格を書かない。'
                '無料／有料の区切りを維持し、記事全文を省略せず返す。'
                '監査報告や制作メモは本文に書かない。'
                '【監査報告】\n'+json.dumps(report,ensure_ascii=False)[:22000])
        return ask('writer',prompt,context(p,{'writing':old,'outline':outputs.get('outline','')}),15500)

    def quality_loop(p, outputs, save=None, rounds=3):
        history=[]
        for number in range(1,rounds+1):
            report=audit(p,outputs)
            report['round']=number
            history.append(report)
            outputs['quality_audits']=history
            if save:
                save('品質監査 '+str(number),outputs)
            if report['passed']:
                return True
            if number<rounds:
                outputs['writing']=revise(p,outputs,report)
                if save:
                    save('記事自動修正 '+str(number),outputs)
        return False

    def save_project(pid, step, outputs, status='running', error=''):
        with lock,connect() as c:
            c.execute('UPDATE studio_projects SET outputs=?,current_stage=?,status=?,error=?,updated_at=? WHERE id=?',
                      (json.dumps(outputs,ensure_ascii=False),step,status,error,now(),pid))

    def get_project(pid):
        with connect() as c:
            row=c.execute('SELECT * FROM studio_projects WHERE id=?',(pid,)).fetchone()
        if not row:
            raise HTTPException(404,'案件がありません')
        result=dict(row)
        result['outputs']=json.loads(result['outputs'] or '{}')
        return result

    def from_project(row):
        return StudioInput(topic=row['topic'],official_title=row['official_title'],audience=row['audience'],
                           price=row['price'],article_type=row['article_type'])

    def execute(pid,p,outputs,begin='ideas'):
        steps=STAGES[STAGES.index(begin):]
        try:
            for name in steps:
                if name=='titles' and 'writing' in outputs:
                    if not quality_loop(p,outputs,lambda s,o:save_project(pid,s,o)):
                        save_project(pid,'品質監査',outputs,'needs_revision',
                                     '記事が監査を通過していません。指摘を確認して修正してください。')
                        return {'id':pid,'status':'needs_revision','outputs':outputs,'published':False}
                outputs[name]=stage(name,p,outputs)
                save_project(pid,name,outputs)
            save_project(pid,'listing',outputs,'pending_approval')
            return {'id':pid,'status':'pending_approval','outputs':outputs,'published':False}
        except Exception as exc:
            LOG.exception('studio project %s failed',pid)
            save_project(pid,'処理失敗',outputs,'error',str(exc)[:350])
            raise HTTPException(502,f'案件#{pid}で停止。保存済み工程は維持しました: {str(exc)[:180]}')

    @app.post('/api/studio/stage')
    def studio_stage(p:StudioInput,_=Depends(auth)):
        if p.stage not in STAGES:
            raise HTTPException(422,'不正な工程です')
        check(p,require_topic=(p.stage!='ideas'))
        outputs=dict(p.previous)
        if p.stage=='listing' and 'writing' in outputs and outputs.get('quality_audits'):
            if not outputs['quality_audits'][-1].get('passed'):
                raise HTTPException(409,'記事が監査未通過です。修正してください')
        try:
            result=stage(p.stage,p,outputs)
        except Exception as exc:
            raise HTTPException(502,'AI処理に失敗しました: '+str(exc)[:220])
        return {'stage':p.stage,'label':LABELS[p.stage],'output':result,'published':False}

    @app.post('/api/studio/run')
    def studio_run(p:StudioInput,_=Depends(auth)):
        check(p)
        timestamp=now()
        with lock,connect() as c:
            cur=c.execute('INSERT INTO studio_projects(topic,official_title,audience,price,article_type,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                          (p.topic.strip(),p.official_title.strip(),p.audience.strip(),p.price,p.article_type,'running',timestamp,timestamp))
            pid=cur.lastrowid
        return execute(pid,p,{})

    @app.get('/api/studio/projects')
    def studio_projects(_=Depends(auth)):
        with connect() as c:
            rows=c.execute('SELECT id,topic,official_title,audience,price,article_type,status,current_stage,error,created_at,updated_at FROM studio_projects ORDER BY id DESC LIMIT 50').fetchall()
        return {'projects':[dict(r) for r in rows]}

    @app.get('/api/studio/projects/{pid}')
    def studio_project(pid:int,_=Depends(auth)):
        return get_project(pid)

    @app.post('/api/studio/projects/{pid}/settings')
    def studio_project_settings(pid:int,p:StudioUpdate,_=Depends(auth)):
        with lock,connect() as c:
            row=c.execute('SELECT * FROM studio_projects WHERE id=?',(pid,)).fetchone()
            if not row:
                raise HTTPException(404,'案件がありません')
            if row['status']=='running':
                raise HTTPException(409,'制作中は設定変更できません')
            changes=p.model_dump(exclude_unset=True)
            if not changes:
                return {'ok':True,'changed':False}
            if 'topic' in changes and not (changes['topic'] or '').strip():
                raise HTTPException(422,'テーマは空にできません')
            for key in ('topic','official_title','audience'):
                if key in changes:
                    changes[key]=(changes[key] or '').strip()
            columns=','.join(k+'=?' for k in changes)
            c.execute('UPDATE studio_projects SET '+columns+",status='needs_revision',updated_at=? WHERE id=?",
                      (*changes.values(),now(),pid))
        return {'ok':True,'changed':True,'requires_regeneration':True,'published':False}

    @app.post('/api/studio/projects/{pid}/regenerate')
    def studio_regenerate(pid:int,_=Depends(auth)):
        with lock,connect() as c:
            row=c.execute('SELECT * FROM studio_projects WHERE id=?',(pid,)).fetchone()
            if not row:
                raise HTTPException(404,'案件がありません')
            if row['status']=='running':
                raise HTTPException(409,'すでに制作中です')
            c.execute("UPDATE studio_projects SET status='running',error='',updated_at=? WHERE id=?",(now(),pid))
        p=from_project(row)
        # Regenerate from scratch after any settings change; keep previous output until new run saves first checkpoint.
        return execute(pid,p,{})

    @app.get('/api/studio/projects/{pid}/html')
    def studio_html(pid:int,_=Depends(auth)):
        row=get_project(pid)
        article=row['outputs'].get('writing','')
        if not article:
            raise HTTPException(409,'原稿がありません')
        title=row['official_title'] or row['topic']
        html=('<!doctype html><html lang="ja"><head><meta charset="utf-8">'
              '<meta name="viewport" content="width=device-width,initial-scale=1"><title>'+escape(title)+'</title>'
              '<style>body{max-width:760px;margin:40px auto;padding:0 18px;font:17px/1.9 system-ui,sans-serif;color:#24352f}'
              'article{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body><article>'+
              escape(article)+'</article></body></html>')
        return HTMLResponse(html,headers={'Content-Disposition':f'attachment; filename="note-{pid}.html"'})
