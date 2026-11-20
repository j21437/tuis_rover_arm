# tuis_rover_arm

アーム開発用リポジトリです。

## フォルダ構成

このリポジトリでは、次のフォルダにファイルを分類して保存します。

```text
tuis_rover_arm/
├── メモ/
│   └── 今までの会話、打ち合わせ内容、検討事項など
└── ロボットアーム_stlデータ/
    └── ロボットアームのSTLデータ
```

- `メモ/`：これまでの会話や打ち合わせ内容、設計の検討事項などを記録する場所です。
- `ロボットアーム_stlデータ/`：ロボットアームのSTLデータを保存する場所です。

## はじめに

### 必要なもの

- Git
- Visual Studio Code
- VS Code の拡張機能「GitHub Pull Requests」

リポジトリを初めて使う場合は、ターミナルで次のコマンドを実行します。

```bash
git clone https://github.com/j21437/tuis_rover_arm.git
cd tuis_rover_arm
code .
```

すでにリポジトリをクローンしている場合は、VS Code でリポジトリフォルダーを開きます。

## Git の基本操作

作業前に必ず、最新の `main` ブランチを取得します。

```bash
git switch main
git pull
```

その後、作業用のブランチを作成します。

```bash
# 例: アーム制御を作成するブランチ
git switch -c feature/arm-control
```

ブランチ名は、用途が分かる名前を付けてください。

変更を確認するには次のコマンドを使います。

```bash
git status
git diff
```

変更をコミットするには、次の手順を実行します。

```bash
# 特定のファイルだけをコミット対象にする
git add <ファイル名>

# 変更内容をまとめたコミットメッセージを付ける
git commit -m "アーム制御の動作を追加"
```

すべての変更を対象にする場合は次のコマンドを使います。

```bash
git add .
git commit -m "アーム制御の動作を追加"
```

作業ブランチをリモートリポジトリへ送信します。

```bash
git push -u origin feature/arm-control
```

作業ブランチを `main` の最新状態に更新するには、次のコマンドを使います。

```bash
git switch main
git pull
git switch feature/arm-control
git merge main
```

## VS Code での操作

### 変更の確認とコミット

1. 左サイドバーの「ソース管理」を開きます。
2. 「変更」一覧で変更内容を確認します。
3. ファイル名の横にある `+` を押すと、変更をステージします。
4. 上部のメッセージ欄にコミットメッセージを入力します。
5. 「コミット」を押します。
6. 「変更の同期」を押して、コミットを GitHub に送信します。

未コミットの変更が残っていないかは、ソース管理画面とステータスバーで確認できます。

### ブランチの作成と切り替え

1. 画面左下のブランチ名をクリックします。
2. 「ブランチの作成」を選択します。
3. ブランチ名を入力します。

切り替えも、画面左下のブランチ名から行えます。

### 最新の変更を取得する

画面左下の「変更の同期」アイコン、またはソース管理画面の「...」メニューから次を実行します。

- `Pull`：リモートから最新の変更を取得
- `Push`：ローカルのコミットをリモートへ送信
- `Fetch`：リモートの状態だけを確認

## コンフリクトへの対応

`git pull` または `git merge main` 後にコンフリクトが発生した場合、VS Code の対象ファイルには次の選択肢が表示されます。

- `Accept Current Change`
- `Accept Incoming Change`
- `Accept Both Changes`

ファイルを確認して正しい内容を選び、不要なコンフリクトマーカー（`<<<<<<<`、`=======`、`>>>>>>>`）を削除します。

コンフリクト解消後は、次の手順で完了します。

1. ソース管理画面で解消したファイルをステージする。
2. コミットする。
3. 「変更の同期」または `git push` で送信する。

## Pull Request を作成する

作業ブランチを GitHub に送信したら、GitHub 上で Pull Request を作成します。

1. リポジトリの「Pull requests」を開く。
2. 「New pull request」を押す。
3. `base` に `main`、`compare` に作業ブランチを選ぶ。
4. 変更内容を確認し、説明を書いて「Create pull request」を押す。

レビューが完了したら、GitHub 上で Pull Request をマージします。マージ後は、ローカルのブランチを最新状態に更新します。

```bash
git switch main
git pull
git branch -d feature/arm-control
```
