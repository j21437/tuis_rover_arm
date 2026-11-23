# tuis_rover_arm

アーム開発用リポジトリです。

## フォルダ構成

現在の主なフォルダ構成は次のとおりです。

```text
tuis_rover_arm/
├── README.md
├── Git操作.md
├── アーム要件一覧.md
├── Robot_arm_stl/
│   ├── J2 hub clamp 1 pipe clamp (printed, goBILDA 1400 pattern).stl
│   ├── J2 hub clamp 2 pipe clamp (printed, goBILDA 1400 pattern).stl
│   ├── J2 hub plate Ø100 (pipe across, 2 clamps).stl
│   ├── J3 base housing + link1 shoe (one print).stl
│   ├── J3 shoe clamp 1 pipe clamp (printed, goBILDA 1400 pattern).stl
│   ├── J3 shoe clamp 2 pipe clamp (printed, goBILDA 1400 pattern).stl
│   └── 印刷済み/
│       └── test.txt
├── メモ/
│   ├── cycloidal_reducer_specification.md
│   ├── memo.md
│   ├── アーム打ち合わせ資料_1118.md
│   ├── アーム構成たたき台_v2.md
│   ├── アーム構成たたき台_v3.md
│   ├── 部品リスト.md
│   └── アーム構成たたき台_v9/
│       ├── arm_v9_geared.step
│       ├── arm_v9_gears.png
│       ├── arm_v9_shoulder.png
│       ├── arm_v9_spec.md
│       ├── arm_v9_stow.png
│       ├── arm_v9_tasks.gif
│       └── アーム構成たたき台_v9.md
```

- `Robot_arm_stl/`：ロボットアームのSTLデータを保存する場所です。`印刷済み/`には印刷済みデータを分類して保存します。
- `メモ/`：会話・打ち合わせ内容、設計の検討事項、部品リストなどを記録する場所です。
- `メモ/アーム構成たたき台_v9/`：アーム構成案 v9 に関する仕様書、画像、CADデータなどをまとめています。
- ルート直下：リポジトリの説明、Git操作、アーム要件一覧を配置しています。

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

### URL一覧

- [Jira プロジェクト管理](https://tuis-trc-urc.atlassian.net/jira/software/projects/TRCURC/list?jql=project+%3D+TRCURC+ORDER+BY+cf%5B10019%5D+ASC&atlOrigin=eyJpIjoiYTkwYWJhOWUyZTM5NDY4OTgyZTYzMmRiMTk1NTMwN2IiLCJwIjoiaiJ9)
- [fusion　アーム用プロジェクト](https://myedu39157.autodesk360.com/g/projects/202611081166885351/data/dXJuOmFkc2sud2lwcHJvZDpmcy5mb2xkZXI6Y28uakUwUlVrby1SUWl0R3QwNjR2OVdyQQ)



