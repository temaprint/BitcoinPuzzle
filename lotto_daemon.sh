#!/bin/bash
# Сид-лото в фоне. Режимы нагрузки CPU при запуске:
#   ./lotto_daemon.sh start [режим] [lines]
#     full  — как есть: одно ядро на 100%           (по умолчанию)
#     nice  — то же ядро, но приоритет -20: macOS отдаёт его любому другому
#             процессу первым, ноутбук холоднее и отзывчивее
#     eco   — мягкий троттлинг ~50% ядра (паузы между билетами)
#     ecoNN — свой процент, напр. eco25 → ~25% ядра
#   lines  — доп. аргумент: построчный вывод фраз в лог
#
#   ./lotto_daemon.sh stop | restart | status | log | hits
# Ротация: лог > 5 МБ сворачивается в lotto_run.log.1 (хранится один).

DIR="$(cd "$(dirname "$0")" && pwd)"
PIDF="$DIR/lotto.pid"
MODEF="$DIR/lotto.mode"
LOGF="$DIR/lotto_run.log"
STATS="$DIR/lotto_stats.json"
EVENTS="$DIR/lotto_events.log"
MAXLOG=$((5 * 1024 * 1024))

running() {
    [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF")" 2>/dev/null
}

case "$1" in
    start)
        if running; then
            echo "уже крутится: PID $(cat "$PIDF") (режим $(cat "$MODEF" 2>/dev/null))"
            exit 0
        fi
        CPU_MODE="${2:-full}"
        OUT_MODE="$3"
        if [ "$CPU_MODE" = "lines" ]; then        # start lines == start full lines
            OUT_MODE="lines"; CPU_MODE="full"
        fi
        ARGS=""
        case "$CPU_MODE" in
            full) LAUNCH=(python3 lotto_hunter.py) ;;
            nice) LAUNCH=(nice -n 20 python3 lotto_hunter.py) ;;
            eco|eco[0-9]*)
                PCT="${CPU_MODE#eco}"; [ -z "$PCT" ] && PCT=50
                LAUNCH=(python3 lotto_hunter.py)
                ARGS="--eco $PCT"
                CPU_MODE="eco$PCT" ;;
            *) echo "режимы: full | nice | eco | ecoNN"; exit 1 ;;
        esac
        [ "$OUT_MODE" = "lines" ] && ARGS="$ARGS --lines"

        if [ -f "$LOGF" ] && [ "$(wc -c < "$LOGF")" -gt "$MAXLOG" ]; then
            rm -f "$LOGF.1"
            mv "$LOGF" "$LOGF.1"
        fi
        echo "=== старт $(date '+%Y-%m-%d %H:%M:%S') режим=$CPU_MODE ===" >> "$LOGF"
        cd "$DIR" || exit 1
        nohup "${LAUNCH[@]}" $ARGS >> "$LOGF" 2>&1 &
        echo $! > "$PIDF"
        echo "$CPU_MODE" > "$MODEF"
        echo "лото крутится в фоне: PID $(cat "$PIDF") | режим: $CPU_MODE$([ "$OUT_MODE" = lines ] && echo ' + lines')"
        echo "лог: $LOGF | события: $EVENTS | статистика: $STATS"
        ;;
    stop)
        if running; then
            PID=$(cat "$PIDF")
            kill -TERM "$PID" 2>/dev/null
            for _ in 1 2 3 4 5 6 7 8 9 10; do
                kill -0 "$PID" 2>/dev/null || break
                sleep 0.5
            done
            kill -0 "$PID" 2>/dev/null && kill -9 "$PID" 2>/dev/null
            rm -f "$PIDF"
            echo "остановлено (PID $PID), итог — в конце лога"
        else
            rm -f "$PIDF"; echo "не запущено"
        fi
        ;;
    status)
        if running; then
            echo "крутится: PID $(cat "$PIDF") | режим: $(cat "$MODEF" 2>/dev/null)"
        else
            echo "не запущено. запустить: ./lotto_daemon.sh start [full|nice|eco|ecoNN] [lines]"
        fi
        if [ -f "$STATS" ]; then
            python3 - "$STATS" << 'EOF'
import json, sys
s = json.load(open(sys.argv[1]))
print(f"всего билетов : {s['tickets']:,}".replace(",", " "))
print(f"времени кручено: {s['seconds']/3600:.2f} ч | сессий: {s['sessions']}")
print(f"джекпотов     : {s['jackpots']} | лучший префикс: {s['best_lcp']} hex-зн.")
print(f"лототрон      : {s['tickets']/2**128*100:.2e}% исчерпано")
EOF
        else
            echo "статистики ещё нет"
        fi
        [ -f "$LOGF" ] && { echo "последние события:"; tail -3 "$LOGF"; }
        ;;
    log)
        tail -f "$LOGF"
        ;;
    hits)
        if [ -f "$DIR/JACKPOT.txt" ]; then
            echo "=== JACKPOT.txt ==="; cat "$DIR/JACKPOT.txt"
        else
            echo "джекпотов нет"
        fi
        if [ -f "$EVENTS" ]; then
            echo "=== события ==="; tail -10 "$EVENTS"
        fi
        ;;
    restart)
        "$0" stop; sleep 1; "$0" start "$2" "$3"
        ;;
    *)
        echo "использование: $0 {start [full|nice|eco|ecoNN] [lines]|stop|restart|status|log|hits}"
        exit 1
        ;;
esac
