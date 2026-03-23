#!/usr/bin/env python3
"""SessionEnd hook: transcript を解析してチャンク化し SQLite に保存する
Version: 20260323B
"""
import json
import os
import sqlite3
import sys
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.db")
MAX_USER_CHARS = 2000
MAX_ASSISTANT_CHARS = 4000
MAX_PAIRS = 500


def init_db(conn):
    """テーブルがなければ作成する"""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            cwd TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            chunk_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            user_text TEXT NOT NULL,
            assistant_text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        );

        CREATE INDEX IF NOT EXISTS idx_chunks_session ON chunks(session_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_created ON chunks(created_at);
        CREATE INDEX IF NOT EXISTS idx_sessions_cwd ON sessions(cwd);

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            user_text,
            assistant_text,
            content=chunks,
            content_rowid=id,
            tokenize="trigram"
        );
    """)


def extract_cwd_from_transcript(transcript_path):
    """JSONLファイルの先頭付近からcwdフィールドを抽出する"""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 20:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "system":
                    cwd = obj.get("cwd", "")
                    if cwd:
                        return cwd
    except (OSError, IOError):
        pass
    return None


def backfill_unsaved_sessions():
    """未保存のtranscriptを回収してDBに保存する"""
    projects_dir = os.path.expanduser("~/.claude/projects/")
    if not os.path.isdir(projects_dir):
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)

        # 保存済みsession_idの一覧を取得
        saved_ids = set()
        for row in conn.execute("SELECT session_id FROM sessions"):
            saved_ids.add(row[0])
    finally:
        conn.close()

    now = time.time()
    deadline = now + 5.0

    # projects直下のディレクトリを走査
    for dir_name in os.listdir(projects_dir):
        if time.time() > deadline:
            break
        dir_path = os.path.join(projects_dir, dir_name)
        if not os.path.isdir(dir_path):
            continue

        for file_name in os.listdir(dir_path):
            if time.time() > deadline:
                break
            if not file_name.endswith(".jsonl"):
                continue
            file_path = os.path.join(dir_path, file_name)
            if not os.path.isfile(file_path):
                continue

            session_id = file_name[:-6]  # .jsonl を除去
            if session_id in saved_ids:
                continue

            # アクティブセッション回避: mtime が直近5分以内ならスキップ
            try:
                mtime = os.path.getmtime(file_path)
                if now - mtime < 300:
                    continue
            except OSError:
                continue

            try:
                cwd = extract_cwd_from_transcript(file_path)
                if not cwd:
                    continue

                pairs = parse_transcript(file_path)
                if not pairs:
                    continue

                save_to_db(session_id, cwd, pairs)
            except Exception:
                continue


def parse_transcript(transcript_path):
    """JSONL transcript をパースして (user_text, assistant_text) ペアのリストを返す"""
    pairs = []
    current_user_text = None
    current_assistant_texts = []

    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            obj_type = obj.get("type", "")

            if obj_type == "user":
                content = obj.get("message", {}).get("content", "")
                # string = ユーザー直接入力、list = tool_result（スキップ）
                if isinstance(content, str) and content.strip():
                    # 前のペアをフラッシュ
                    if current_user_text and current_assistant_texts:
                        pairs.append((
                            current_user_text[:MAX_USER_CHARS],
                            "\n".join(current_assistant_texts)[:MAX_ASSISTANT_CHARS]
                        ))
                        if len(pairs) >= MAX_PAIRS:
                            break
                    current_user_text = content.strip()
                    current_assistant_texts = []

            elif obj_type == "assistant":
                blocks = obj.get("message", {}).get("content", [])
                for block in blocks:
                    if block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            current_assistant_texts.append(text)
                    # thinking, tool_use → スキップ

            # progress, queue-operation, system, last-prompt → スキップ

    # 最後のペアをフラッシュ
    if current_user_text and current_assistant_texts and len(pairs) < MAX_PAIRS:
        pairs.append((
            current_user_text[:MAX_USER_CHARS],
            "\n".join(current_assistant_texts)[:MAX_ASSISTANT_CHARS]
        ))

    return pairs


def save_to_db(session_id, cwd, pairs):
    """チャンクをSQLiteに保存する"""
    conn = sqlite3.connect(DB_PATH)
    try:
        init_db(conn)

        # 冪等性: 既にこのsession_idが保存済みならスキップ
        existing = conn.execute(
            "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if existing:
            return

        # H1修正: 明示的トランザクションで一貫性を保証
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO sessions (session_id, cwd, chunk_count) VALUES (?, ?, ?)",
                (session_id, cwd, len(pairs))
            )

            for seq, (user_text, assistant_text) in enumerate(pairs):
                cursor = conn.execute(
                    "INSERT INTO chunks (session_id, seq, user_text, assistant_text) VALUES (?, ?, ?, ?)",
                    (session_id, seq, user_text, assistant_text)
                )
                # FTS5 に手動で同期
                # NOTE: content=テーブル使用時、DELETE/UPDATEも手動同期が必要。
                # 将来チャンク削除機能を追加する場合はFTSも同期すること。
                conn.execute(
                    "INSERT INTO chunks_fts (rowid, user_text, assistant_text) VALUES (?, ?, ?)",
                    (cursor.lastrowid, user_text, assistant_text)
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

    finally:
        conn.close()

    # DB パーミッション 600（初回のみ意味がある）
    try:
        os.chmod(DB_PATH, 0o600)
    except OSError:
        pass


def main():
    # --backfill モード
    if "--backfill" in sys.argv:
        try:
            backfill_unsaved_sessions()
        except Exception:
            pass
        sys.exit(0)

    try:
        # stdin から JSON を読む
        input_data = json.load(sys.stdin)
        session_id = input_data.get("session_id", "")
        transcript_path = input_data.get("transcript_path", "")
        cwd = input_data.get("cwd", "")

        if not session_id or not transcript_path:
            sys.exit(0)

        if not os.path.exists(transcript_path):
            sys.exit(0)

        pairs = parse_transcript(transcript_path)
        if not pairs:
            sys.exit(0)

        save_to_db(session_id, cwd, pairs)

    except Exception as e:
        # M3修正: エラーをstderrにログ出力（デバッグ用）
        print(f"memory_save error: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
