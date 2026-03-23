#!/bin/bash
# SessionStart hook: 関連する過去の記憶を検索してstdoutに出力する
# stdout は Claude のコンテキストとして自動注入される
# Version: 20260323B
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DB_PATH="$SCRIPT_DIR/memory.db"

# 未保存セッションを回収（初回はDBも作成される）
python3 "$SCRIPT_DIR/memory_save.py" --backfill 2>/dev/null || true

# DB が存在しない場合は何もしない（初回セッション）
if [ ! -f "$DB_PATH" ]; then
    exit 0
fi

# stdin から JSON を読む
INPUT=$(cat)
CWD=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || echo "")

# C2修正: cwd完全一致の最近のチャンクをメインに、FTS検索は補助的に使う
QUERY=""
if [ -n "$CWD" ]; then
    QUERY=$(basename "$CWD" 2>/dev/null || echo "")
fi

# クエリが3文字未満でもrecent_by_projectのフォールバックがあるので続行
# ただしFTS5検索自体は3文字未満ではスキップされる

# H2修正: 1回だけ実行して結果を変数に保持
if [ ${#QUERY} -ge 3 ]; then
    RESULT=$(python3 "$SCRIPT_DIR/memory_search.py" --query "$QUERY" --project "$CWD" --limit 5 2>/dev/null || true)
else
    # 3文字未満のプロジェクト名: recent_by_projectだけが動く
    RESULT=$(python3 "$SCRIPT_DIR/memory_search.py" --query "___" --project "$CWD" --limit 5 2>/dev/null || true)
fi

# stdout出力（Claudeのコンテキストに注入される）
if [ -n "$RESULT" ]; then
    echo "$RESULT"

    # フォールバック: session-context.md にも書き出す
    MEMORY_DIR="$HOME/.claude/memory"
    if [ -d "$MEMORY_DIR" ]; then
        echo "$RESULT" > "$MEMORY_DIR/session-context.md" 2>/dev/null || true
    fi
fi

exit 0
