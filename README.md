# 🐼 AI note Studio — iPhone / Cloud Edition

Safariで使うモバイル対応AIオフィス。企画→原稿→10観点監査→SNS投稿案をクラウドで生成し、**承認待ちで停止**します。note・X・Threadsへの公開や売上の自動取得は未実装です。需要調査はAIによる仮説作成で、ライブWeb検索ではありません。

## クラウド公開手順（RenderなどDocker対応ホスティング）

1. ZIPを展開し、このフォルダを**非公開GitHubリポジトリ**にアップロード（`.env` と `*.db` は絶対にアップロードしない）。
2. Render等でWeb Serviceを作成し、リポジトリを接続。**Docker**としてデプロイ。
3. 環境変数 `OPENAI_API_KEY`, `ADMIN_PASSWORD`, `CRON_SECRET` を設定。`ADMIN_PASSWORD` と `CRON_SECRET` は別々の十分長いランダムな値にする。`OPENAI_MODEL` は任意。
4. データを再起動後も保持するには永続ディスクを `/data` にマウントし、`DATABASE_PATH=/data/studio.db` を設定。永続ディスクがないホストではデータが失われる場合があります。**無料プランでは永続ディスクや常時稼働に制限がある場合があります。**
5. ホストが発行した HTTPS URLをiPhoneのSafariで開く。Basic認証画面でユーザー名 `admin` と `ADMIN_PASSWORD` を入力。Safariの「共有」→「ホーム画面に追加」でアプリ風に使えます。
6. 画面の「完全自動ワークフロー」にテーマ・読者・価格を入力し、設定保存。ボタンから一度試運転します。
7. 定期実行にはホスティングのCronまたは外部スケジューラで、次のHTTP POSTを毎日などの間隔で呼びます（時刻はスケジューラ側のタイムゾーンに注意）。

```bash
curl -fsS -X POST 'https://YOUR-APP-URL/api/cron' -H 'X-Cron-Secret: YOUR_CRON_SECRET'
```

※ Cron URLや秘密鍵は公開ページ・SNS・GitHubに書かず、スケジューラのシークレット設定に保存してください。常時起動しないホスティングではバックグラウンド処理が中断され得ます。確実な運用にはワーカー／ジョブキューと永続DBへの移行を推奨します。

## ローカル起動

```bash
python -m pip install -r requirements.txt
cp .env.example .env
# .envを編集してAPIキー、管理パスワード、cron秘密鍵を設定。ローカルではDATABASE_PATH=./studio.db
uvicorn server:app --host 127.0.0.1 --port 8000
```

ブラウザで `http://127.0.0.1:8000` を開きます。

## セキュリティと制限

- 必ずHTTPSで公開してください。HTTP Basic認証はHTTPSなしでは安全ではありません。
- APIキーはサーバー環境変数にのみ保存。画面やJavaScriptには入れないでください。
- 管理者1名向けの試作版です。外部公開前にはレート制限、CSRF対策、運用監視、コスト上限、バックアップを追加してください。
- 生成AI利用にはAPI従量課金が発生します。1回の自動実行で4回のモデル呼び出しが行われます。
- スケジューラは**別途設定が必要**です。デプロイしただけでは定期実行されません。
- 「承認」はDBへの記録のみ。noteやSNSへの投稿は実行しません。公開は手動で行ってください。
