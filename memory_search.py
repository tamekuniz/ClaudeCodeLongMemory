#!/usr/bin/env python3
"""FTS5検索 + 時間減衰スコアリング。結果をMarkdown形式で stdout に出力する"""
import argparse
import math
import os
import sqlite3
import sys
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory.db")
TIME_DECAY_HALF_LIFE_DAYS = 30


def search(query, project=None, limit=5):
    """FTS5検索を実行し、時間減衰を適用してスコア順に返す"""
    if not os.path.exists(DB_PATH):
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # FTS5 trigram 検索
        # trigram は3文字以上必要
        if len(query) < 3:
            return []

        # FTS5のMATCH用にクエリをエスケープ（ダブルクォートで囲む）
        safe_query = '"' + query.replace('"', '""') + '"'

        rows = conn.execute("""
            SELECT c.id, c.session_id, c.user_text, c.assistant_text,
                   c.created_at, s.cwd, c.seq,
                   rank
            FROM chunks_fts
            JOIN chunks c ON chunks_fts.rowid = c.id
            JOIN sessions s ON c.session_id = s.session_id
            WHERE chunks_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (safe_query, limit * 4)).fetchall()  # 多めに取って後でフィルタ

        # 時間減衰スコアリング
        now = datetime.now()
        scored = []
        for row in rows:
            try:
                created = datetime.fromisoformat(row["created_at"])
            except (ValueError, TypeError):
                created = now
            age_days = max((now - created).total_seconds() / 86400, 0)
            time_factor = math.exp(-0.693 * age_days / TIME_DECAY_HALF_LIFE_DAYS)
            # rank は負の値（0に近いほど高マッチ）
            base_score = -row["rank"] if row["rank"] else 0
            final_score = base_score * time_factor

            # プロジェクトフィルタ: cwdが一致するものをブースト
            if project:
                project_name = os.path.basename(project.rstrip("/"))
                row_project = os.path.basename(row["cwd"].rstrip("/")) if row["cwd"] else ""
                if project_name == row_project:
                    final_score *= 1.5

            scored.append({
                "user_text": row["user_text"],
                "assistant_text": row["assistant_text"],
                "created_at": row["created_at"],
                "cwd": row["cwd"],
                "score": final_score,
            })

        # スコア順にソートして上位を返す
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    finally:
        conn.close()


def format_results(results):
    """検索結果をMarkdown形式でフォーマットする"""
    if not results:
        return ""

    lines = ["## Related Past Conversations", ""]
    for i, r in enumerate(results, 1):
        project = os.path.basename(r["cwd"].rstrip("/")) if r["cwd"] else "unknown"
        date = r["created_at"][:10] if r["created_at"] else "?"

        user_preview = r["user_text"][:150].replace("\n", " ")
        assistant_preview = r["assistant_text"][:300].replace("\n", " ")

        lines.append(f"### {i}. [{date}] Project: {project}")
        lines.append(f"**Q**: {user_preview}")
        lines.append(f"**A**: {assistant_preview}")
        lines.append("")

    lines.append("---")
    lines.append(f"_{len(results)} results from long-term memory (FTS5)_")
    return "\n".join(lines)


def recent_by_project(project, limit=5):
    """同じcwdの最近のチャンクを返す（FTS検索なし）"""
    if not os.path.exists(DB_PATH) or not project:
        return []

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # C1修正: cwd完全一致でWHERE句を使い、フルスキャンを回避
        rows = conn.execute("""
            SELECT c.user_text, c.assistant_text, c.created_at, s.cwd
            FROM chunks c
            JOIN sessions s ON c.session_id = s.session_id
            WHERE s.cwd = ?
            ORDER BY c.created_at DESC
            LIMIT ?
        """, (project, limit)).fetchall()

        return [{
            "user_text": row["user_text"],
            "assistant_text": row["assistant_text"],
            "created_at": row["created_at"],
            "cwd": row["cwd"],
            "score": 0,
        } for row in rows]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Search long-term memory")
    parser.add_argument("--query", "-q", required=True, help="Search query")
    parser.add_argument("--project", "-p", default=None, help="Project path for boosting")
    parser.add_argument("--limit", "-l", type=int, default=5, help="Max results")
    args = parser.parse_args()

    results = search(args.query, args.project, args.limit)

    # FTS検索で結果がなければ、同じプロジェクトの最近のチャンクを返す
    if not results and args.project:
        results = recent_by_project(args.project, args.limit)

    output = format_results(results)
    if output:
        print(output)


if __name__ == "__main__":
    main()
