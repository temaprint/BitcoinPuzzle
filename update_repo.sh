#!/bin/bash
# Обновление GitHub-репозитория git@github.com:temaprint/BitcoinPuzzle.git
# Первый запуск: инициализирует git, привязывает remote, пушит.
# Дальнейшие: коммитит изменения и пушит.
#
#   ./update_repo.sh                  # авто-сообщение «обновление YYYY-MM-DD HH:MM»
#   ./update_repo.sh "моё сообщение"  # свой текст коммита
set -e

REMOTE="git@github.com:temaprint/BitcoinPuzzle.git"
BRANCH="main"
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# 1. первый запуск: init + привязка remote
if [ ! -d .git ]; then
    git init -b "$BRANCH" >/dev/null
    git remote add origin "$REMOTE"
    echo "git инициализирован, remote: $REMOTE (ветка $BRANCH)"
fi

# 2. коммитим изменения, если есть
git add -A
if git diff --cached --quiet; then
    echo "изменений нет — просто пушу"
else
    MSG="${1:-обновление $(date '+%Y-%m-%d %H:%M')}"
    git commit -m "$MSG"
    echo "коммит: $MSG"
fi

# 3. пуш
if git push -u origin "$BRANCH" 2>&1; then
    echo "готово: $REMOTE ($BRANCH) обновлён"
else
    echo ""                                                        >&2
    echo "пуш не прошёл. Если репа на GitHub создавалась с README/" >&2
    echo "LICENSE, подтяни её историю и повтори:"                  >&2
    echo "  git pull --rebase origin $BRANCH --allow-unrelated-histories" >&2
    echo "  ./update_repo.sh"                                      >&2
    exit 1
fi
