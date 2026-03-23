# Claude Code Long-term Memory

A long-term memory system for Claude Code that automatically saves and retrieves conversations across sessions.

## Features

- **Auto-save**: Automatically chunks and saves conversations to SQLite on session end via SessionEnd hook
- **Auto-inject**: Automatically retrieves related past memories and injects them into context on session start via SessionStart hook
- **FTS5 Full-text Search**: Japanese text search support using SQLite's trigram tokenizer
- **Time Decay**: Older memories score lower (half-life: 30 days)
- **Zero LLM Usage**: Rule-based chunking, no token consumption
- **Zero Dependencies**: Uses only Python's built-in `sqlite3` module
- **Global**: Accumulates and searches memories across all projects

## Files

| File | Role |
|---|---|
| `memory_save.py` | SessionEnd hook. Parses transcript, chunks it, saves to SQLite |
| `memory_search.py` | FTS5 search + time decay scoring. Outputs results in Markdown |
| `memory_hook.sh` | SessionStart hook. Searches related memories and injects into Claude's context |

## Installation

### 1. Place files

```bash
mkdir -p ~/.claude/memory-system
cp memory_save.py memory_search.py memory_hook.sh ~/.claude/memory-system/
chmod +x ~/.claude/memory-system/memory_hook.sh
chmod 700 ~/.claude/memory-system
```

### 2. Configure hooks

Add the following to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash $HOME/.claude/memory-system/memory_hook.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'python3 $HOME/.claude/memory-system/memory_save.py'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

### 3. Add to CLAUDE.md (optional)

```markdown
# Long-term Memory

- Past sessions are automatically saved and searched via SessionStart/SessionEnd hooks
- Manual search: `python3 ~/.claude/memory-system/memory_search.py --query "search term"`
```

## Usage

### Automatic (no action needed)

- Conversations are auto-saved when a session ends
- Related past memories are auto-injected when a new session starts

### Manual Search

```bash
# Keyword search
python3 ~/.claude/memory-system/memory_search.py --query "SwiftUI" --limit 5

# Filter by project
python3 ~/.claude/memory-system/memory_search.py --query "bug fix" --project "/path/to/project" --limit 3
```

## How It Works

### Save (SessionEnd)

1. Claude Code's SessionEnd hook fires
2. Receives `transcript_path` (JSONL conversation log path) via stdin
3. Parses JSONL into user utterance + assistant response pairs
4. Skips `thinking`, `tool_use`, `tool_result` blocks (noise reduction)
5. Saves to SQLite `chunks` table and syncs FTS5 index

### Search (SessionStart)

1. SessionStart hook fires
2. Searches FTS5 using project name from cwd (working directory)
3. Applies time decay scoring (half-life: 30 days)
4. Boosts chunks matching the current project
5. Outputs results as Markdown to stdout → injected into Claude's context

### SQLite Schema

```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    cwd TEXT NOT NULL,
    created_at TEXT NOT NULL,
    chunk_count INTEGER DEFAULT 0
);

CREATE TABLE chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    user_text TEXT NOT NULL,
    assistant_text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    user_text, assistant_text,
    content=chunks, content_rowid=id,
    tokenize="trigram"
);
```

## Requirements

- macOS (FTS5 trigram support confirmed with Python 3.9+ sqlite3)
- Claude Code 2.1+ (SessionStart / SessionEnd hooks support)
- Also works with Claude Code in the Claude Desktop app

## Future Plans (Phase 2)

- Vector search (Ruri v3-310m + sqlite-vec)
- RRF (Reciprocal Rank Fusion) combining FTS5 + vector search
- Auto-archiving of old memories

## References

- [sui-memory (concept article, Japanese)](https://zenn.dev/noprogllama/articles/7c24b2c2410213)
- [Claude Code Hooks Documentation](https://code.claude.com/docs/en/hooks-guide)

## License

MIT

---

# Claude Code 長期記憶

Claude Code のセッション間で会話を自動保存・検索する長期記憶システム。

## 特徴

- **自動保存**: SessionEnd hook でセッション終了時に会話を自動でチャンク化して SQLite に保存
- **自動注入**: SessionStart hook でセッション開始時に関連する過去の記憶をコンテキストに自動注入
- **FTS5 全文検索**: SQLite の trigram トークナイザで日本語テキスト検索に対応
- **時間減衰**: 古い記憶ほどスコアが下がる（半減期30日）
- **LLM 不使用**: トークン消費ゼロ。ルールベースのチャンク分割
- **依存パッケージなし**: Python 標準ライブラリ（sqlite3）のみで動作
- **グローバル動作**: 全プロジェクト横断で記憶を蓄積・検索

## ファイル構成

| ファイル | 役割 |
|---|---|
| `memory_save.py` | SessionEnd hook。transcript を解析してチャンク化し SQLite に保存 |
| `memory_search.py` | FTS5 検索 + 時間減衰スコアリング。結果を Markdown で出力 |
| `memory_hook.sh` | SessionStart hook。関連記憶を検索して Claude のコンテキストに注入 |

## インストール

### 1. ファイルを配置

```bash
mkdir -p ~/.claude/memory-system
cp memory_save.py memory_search.py memory_hook.sh ~/.claude/memory-system/
chmod +x ~/.claude/memory-system/memory_hook.sh
chmod 700 ~/.claude/memory-system
```

### 2. hooks を設定

`~/.claude/settings.json` に以下を追加:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash $HOME/.claude/memory-system/memory_hook.sh",
            "timeout": 10
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "bash -c 'python3 $HOME/.claude/memory-system/memory_save.py'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

### 3. CLAUDE.md に追記（任意）

```markdown
# Long-term Memory

- SessionStart/SessionEnd hook で過去セッションの記憶が自動保存・検索される
- 手動で記憶検索したい場合: `python3 ~/.claude/memory-system/memory_search.py --query "検索ワード"`
```

## 使い方

### 自動（何もしなくてOK）

- セッション終了時に会話が自動保存される
- 次のセッション開始時に関連する過去の記憶が自動注入される

### 手動検索

```bash
# キーワード検索
python3 ~/.claude/memory-system/memory_search.py --query "SwiftUI" --limit 5

# プロジェクト絞り込み
python3 ~/.claude/memory-system/memory_search.py --query "バグ修正" --project "/path/to/project" --limit 3
```

## 仕組み

### 保存（SessionEnd）

1. Claude Code の SessionEnd hook が発火
2. stdin から `transcript_path`（会話ログの JSONL ファイルパス）を受け取る
3. JSONL をパースし、ユーザー発話 + アシスタント応答のペアに分割
4. `thinking`, `tool_use`, `tool_result` はスキップ（ノイズ除去）
5. SQLite の `chunks` テーブルに保存、FTS5 インデックスを同期

### 検索（SessionStart）

1. SessionStart hook が発火
2. cwd（作業ディレクトリ）のプロジェクト名で FTS5 検索
3. 時間減衰スコアを適用（半減期30日）
4. プロジェクト一致のチャンクをブースト
5. 結果を Markdown 形式で stdout に出力 → Claude のコンテキストに注入

## 動作環境

- macOS（Python 3.9+ の sqlite3 で FTS5 trigram 対応を確認済み）
- Claude Code 2.1+（SessionStart / SessionEnd hooks 対応）
- Claude Desktop アプリ内の Claude Code でも動作

## 今後の拡張（Phase 2）

- ベクトル検索の追加（Ruri v3-310m + sqlite-vec）
- FTS5 + ベクトルの RRF（Reciprocal Rank Fusion）統合
- 古い記憶の自動アーカイブ

## 参考

- [sui-memory（コンセプト記事）](https://zenn.dev/noprogllama/articles/7c24b2c2410213)
- [Claude Code Hooks ドキュメント](https://code.claude.com/docs/en/hooks-guide)

## ライセンス

MIT
