# QLOS-Lite — QQ / OneBot セーフティゲートウェイ

[简体中文](README.md) | [English](README.en.md) | 日本語

QLOS-Lite は QQ/OneBot と Hermes の間に置く薄い安全ゲートウェイです。送信者の身元、グループルール、リスク判定、添付メタデータ、永続キュー、監査ログ、返信配送を扱います。

## 機能

* Owner、friend、group、blocked のルーティング。
* QQ 用プロンプトと分割マーカーの整形。
* 添付ファイルのメタデータとプライベートメディア参照。
* 重複排除付きの永続メッセージキュー。
* Hermes Gateway と Hermi Gateway のクライアント。
* 承認ブリッジ、診断、trace、tool-guard 連携。

## ビルドと実行

Python 3.11 以上、外部 NapCatQQ、Hermes Agent/Gateway を用意します。

```powershell
python -m pip install -r requirements.txt
python -m pytest -q
python -m qlos_lite.onebot_server
```

スタック起動時は `NAPCAT_ROOT` を設定するか、`-NapCatDir` を指定してください。NapCatQQ のバイナリとログイン状態は含まれていません。

## 設定

`.env.example` と `secrets.local.env.example` をローカル設定へコピーし、`roles.example.json` を `roles.json` にコピーします。実際の QQ ID、token、メディア、キュー、ログは Git の外に置いてください。

## アーキテクチャ

```text
QQ -> NapCatQQ/OneBot -> QLOS-Lite :8766 -> Hermi :8789 -> Hermes :8642
```

Hermi は任意です。有効にすると、セッション、権限、利用量、承認をまとめて管理します。

## 依存関係

Python と外部 Hermes Gateway が必要です。NapCatQQ は外部の QQ/OneBot アダプターです。Hermi は任意のローカルゲートウェイです。

## ライセンス

このプロジェクトのオープンソースライセンスはまだ選択されていません。
