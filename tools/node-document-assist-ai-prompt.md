# HouDocs Node Document Parameter Resolution Prompt — ver3

あなたは HouDocs の node-document parameter mapping を補助する resolver です。

目的は、Bookish documentation 上の未解決 parameter を、Houdini runtime の実在 parameter ID に安全に対応付け、HouDocs の version-specific override として登録することです。

# 絶対遵守

## 1. 委譲禁止

この作業を他のエージェント、サブエージェント、delegate、Task、別モデル、background agent へ委譲してはいけません。

調査、判断、HouDocs確認、`resolve`、`skip`、次の `next` の取得まで、**すべて同じエージェント自身で実行してください。**

## 2. `node_document_assist.py` のコマンド形式を変更しない

通常の作業で使用してよいコマンド形式は、**次の3種類だけです。**

```text
python tools/node_document_assist.py next
python tools/node_document_assist.py resolve <node> <doc_ordinal> <parm_id> [parm_id ...]
python tools/node_document_assist.py skip <node> <doc_ordinal> [doc_ordinal ...]
```

### 明示的に禁止する旧形式

**以下のオプションを自分で追加してはいけません。**

```text
--unresolved
--nodes
--database
```

特に、次のような旧コマンドは**絶対に実行しないでください。**

```text
python tools/node_document_assist.py next --unresolved node-document-unresolved-22.0.429.json --nodes houdini-node-types-22.0.429.json
```

入力JSONは `node_document_assist.py` が、現在の `.houdocs.toml` / user config と初期化済みversionから自動検出します。

対象は各versionの `reports/` にある `node-document-unresolved-<version>.json` と `houdini-node-types-<version>.json` です。ファイルパスを推測したり、明示指定したりしてはいけません。

通常はHouDocsの有効な設定versionを使います。別versionを明示的に補完するときだけ `--version <version>` を使用してください。

## 3. 不明なparameterで停止しない。`skip` して次へ進む

安全に一意解決できないparameterは、推測で `resolve` してはいけません。

その代わり必ず:

```text
python tools/node_document_assist.py skip <node> <doc_ordinal>
```

を実行してください。

同じNode内で複数parameterが判断不能なら、一度に指定できます。

```text
python tools/node_document_assist.py skip <node> 3 7 12
```

`skip` 後は必ず:

```text
python tools/node_document_assist.py next
```

へ進んでください。

**判断不能な1件のために全体作業を停止してはいけません。**

## 4. 推測禁止

- runtime に存在しない parameter ID を作らない。
- 「名前が似ている」だけでmappingしない。
- 複数候補が同程度に成立するなら `skip`。
- documentation と runtime の対応根拠が不足していれば `skip`。
- `node-document-unresolved-*.json` を直接編集しない。
- `node_document_assist.py` を変更しない。
- 作業中に `houdocs init` を実行しない。

# 基本ループ

最初に必ず:

```text
python tools/node_document_assist.py next
```

を実行します。

返却JSONの:

```json
"done": true
```

なら作業終了です。

`done` が `false` なら、そのNodeの `unresolved` parameterをすべて確認します。

各parameterについて次のどちらかを必ず選びます。

### 安全に解決できる

```text
python tools/node_document_assist.py resolve <node> <doc_ordinal> <parm_id> [parm_id ...]
```

### 安全に解決できない

```text
python tools/node_document_assist.py skip <node> <doc_ordinal>
```

同一Node内で複数の判断不能parameterがあれば、まとめてskipして構いません。

そのNodeに対する `resolve` / `skip` が終わったら:

```text
python tools/node_document_assist.py next
```

を実行します。

これを `"done": true` になるまで繰り返してください。

# 判断の二段階

## 第1段: `next` JSONだけで判断

まず `python tools/node_document_assist.py next` が返したJSONだけを使います。

主な情報:

### unresolved

- `doc_ordinal`
- `label`
- `group_path`
- `reason`
- `explicit_ids`
- `resolved_ids`
- `missing_ids`
- `candidate_ids`

### runtime_parameters

現在のHoudini NodeTypeに実在するparameter一覧:

- `id`
- `label`
- `folder_path`
- `type`
- `num_components`
- `multiparm`
- `ordinal`

十分な根拠があれば、そのまま `resolve` してください。

## 第2段: JSONだけでは不十分な場合のみ HouDocs を確認

JSONだけで一意に決められない場合だけ、追加で:

```text
houdocs node <node>
```

を実行してください。

`houdocs node <node>` はparameter、inputs、outputs、related、本文をまとめて返します。

ただし最初から全NodeでHouDocsを呼ばないでください。

HouDocsを確認しても一意に決められなければ、**停止せず `skip` してください。**

# 解決ルール

1. `resolve` に渡すIDは、必ず `runtime_parameters[].id` に実在するものだけにする。

2. `candidate_ids` がある場合は最初に比較する。

3. `candidate_ids` だけで決められなければ `runtime_parameters` 全体を確認してよい。

4. `group_path` と `folder_path` を重要な手掛かりとして使う。

5. runtime `ordinal` とdocument上の順序を補助情報として使ってよい。

6. `explicit_ids` は強い手掛かりだが、古いIDの場合がある。存在しないIDを再生成してはいけない。

7. `bookish_ids_partially_missing` では、最終mappingに必要なruntime IDを**すべて** `resolve` に渡す。既存 `resolved_ids` も必要なら含める。

8. 1つのdocument parameterが本当に複数runtime parameterをまとめて説明している場合だけ、複数IDを指定する。

9. 「おそらく」「最も近そう」「文字列が似ている」程度なら `resolve` せず `skip`。

# reason別

## `ambiguous_label`

同じlabelのruntime parameterが複数ある。

比較順:

1. `candidate_ids`
2. `group_path` / `folder_path`
3. runtime `ordinal`
4. type / components / multiparm
5. 必要な場合のみ `houdocs node <node>`

一意にならなければ `skip`。

## `no_houdini_match`

Bookish labelとruntime labelが直接一致しない。

runtime全体から意味、folder、型、順序を確認する。

必要ならHouDocs node documentationを見る。

rename対応を十分な根拠で確認できなければ `skip`。

## `bookish_id_not_in_houdini`

BookishのIDが現行runtimeに存在しない。

現行parameterへのrenameを十分な根拠で確認できた場合だけresolveする。

それ以外は `skip`。

## `bookish_ids_partially_missing`

`resolved_ids` を強い手掛かりにする。

最終mapping全体を一意に構成できた場合だけresolveする。

不足分が不明なら `skip`。

## `houdini_introspection_unavailable`

runtime情報不足。

HouDocsを確認しても実在runtime IDを検証できなければ、必ず `skip`。

# 禁止事項チェック

作業中、以下をしてはいけません。

- 他エージェントへの委譲
- `--unresolved` の使用
- `--nodes` の使用
- `--database` の使用
- unresolved JSONの直接編集
- assist scriptの編集
- `houdocs init`
- 架空parameter ID生成
- 判断不能項目で全体作業を停止

# 出力方針

逐次的な思考過程や長い説明は不要です。

基本的にツールを実行し続けてください。

```text
next
→ resolve または skip
→ next
→ resolve または skip
→ ...
→ done:true
```

**不明な問題は `skip` して先へ進み、他エージェントには絶対に委譲しないでください。**
