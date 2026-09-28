#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
СИД-ЛОТО (оптимизированная версия: память O(1), лог — только события).

Что изменилось против первой версии:
  РАНЬШЕ                              ТЕПЕРЬ
  set из всех фраз в RAM (~1ГБ/день)  Bloom-фильтр на 2 МБ (фикс. память)
  каждый билет в lotto_tickets.log    только сводка раз в 100 + события
  повтор ищется по всему журналу      повтор ловится фильтром внутри сессии

Почему повторов можно не бояться между сессиями (математика дней рождения):
повтор становится вероятным лишь после ~2^64 билетов; при 68/сек это
~8.6e9 лет непрерывной работы. Bloom внутри сессии — страховка без затрат.

Файлы:
  lotto_stats.json  — счётчики (всего билетов, время, рекорды) — ~200 байт,
                      атомарная перезапись tmp+rename каждые 1000 билетов;
  lotto_events.log  — только редкие события (джекпот, новый рекорд префикса);
  JACKPOT.txt       — фраза-победитель, если вдруг;
  lotto_run.log     — stdout (сводки); ротация в lotto_daemon.sh.

Шансы не изменились: 1 из 2^128 ≈ 1 из 3.4e38 за билет.

Запуск:
  python3 lotto_hunter.py                 # сводка каждые 100 билетов
  python3 lotto_hunter.py --tickets 500   # конечная серия
  python3 lotto_hunter.py --lines         # построчно (фраза+результат) —
                                          # только для ручного просмотра
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import signal
import sys
import time

from puzzle_generator import (B58_ALPHABET, compressed_pub, erase_bits,
                              hash160, master_from_mnemonic)

WORDS = [w.strip() for w in open("bip39_english.txt") if w.strip()]
assert len(WORDS) == 2048

STATS_FILE = "lotto_stats.json"
EVENTS_LOG = "lotto_events.log"
JACKPOT_FILE = "JACKPOT.txt"
OLD_TICKETS = "lotto_tickets.log"   # архив первой версии, не перезаписывается
PROBE = (66, 71)
SPACE = 2 ** 128
REPORT_EVERY = 100
SAVE_EVERY = 1000


# ── билет ────────────────────────────────────────────────────────────────────
def random_phrase() -> str:
    ent = secrets.token_bytes(16)
    cs = hashlib.sha256(ent).digest()[0] >> 4
    total = (int.from_bytes(ent, "big") << 4) | cs
    return " ".join(
        WORDS[(total >> (11 * (11 - i))) & 0x7FF] for i in range(12)
    )


# ── повторы: Bloom-фильтр на фиксированных 2 МБ ──────────────────────────────
class Bloom:
    """k=3, m=2^24 бит. Ложных срабатываний ~0.2% до ~30 млн вставок;
    насыщение никак не ломает работу — просто изредка пропустит билет."""

    def __init__(self, m_bits: int = 1 << 24, k: int = 3):
        self.m, self.k = m_bits, k
        self.mem = bytearray(m_bits >> 3)

    def add(self, phrase: str) -> bool:
        """Отметить фразу. Вернуть True, если она, ПОХОЖЕ, уже была."""
        d = hashlib.blake2b(phrase.encode(), digest_size=16).digest()
        h1 = int.from_bytes(d[:8], "big")
        h2 = int.from_bytes(d[8:], "big") | 1
        seen = True
        for i in range(self.k):
            p = (h1 + i * h2) % self.m
            byte, bit = p >> 3, 1 << (p & 7)
            if not self.mem[byte] & bit:
                self.mem[byte] |= bit
                seen = False
        return seen


# ── цели ─────────────────────────────────────────────────────────────────────
def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58_ALPHABET.index(c)
    return b"\x00" * (len(s) - len(s.lstrip("1"))) + n.to_bytes((n.bit_length() + 7) // 8, "big")


def load_targets() -> dict[str, int]:
    data = json.loads(re.sub(r"^\s*//.*$", "", open("b1000.jsonc").read(), flags=re.M))
    return {b58decode(p["address"]["value"])[1:21].hex(): p["key"]["bits"]
            for p in data["puzzles"]}


def child_h160(master, puzzle_no: int) -> str:
    k = erase_bits(master.derive_child(puzzle_no).key, puzzle_no, "force")
    return hash160(compressed_pub(k)).hex()


def lcp(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


# ── накопление: крошечный JSON + события ─────────────────────────────────────
def load_stats() -> dict:
    s = {"tickets": 0, "seconds": 0.0, "jackpots": 0, "best_lcp": 0,
         "sessions": 0, "last_phrase": ""}
    if os.path.exists(STATS_FILE):
        s.update(json.load(open(STATS_FILE)))
    elif os.path.exists(OLD_TICKETS):          # миграция: учёт архива 1-й версии
        with open(OLD_TICKETS) as f:
            s["tickets"] = sum(1 for _ in f)
        s["migrated_from"] = OLD_TICKETS
    return s


def save_stats(s: dict) -> None:
    tmp = STATS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATS_FILE)                # атомарно, без порчи при краше


def event(msg: str) -> None:
    with open(EVENTS_LOG, "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


# ── основной цикл ────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Сид-лото против Bitcoin Puzzle")
    ap.add_argument("--tickets", type=int, default=0, help="0 = бесконечно")
    ap.add_argument("--lines", action="store_true", help="построчный вывод")
    ap.add_argument("--eco", type=int, metavar="P", default=0,
                    help="целевая загрузка CPU в процентах (1-100);"
                         " после каждого билета пауза, P=50 → ~50%% ядра")
    args = ap.parse_args()
    if args.eco and not 1 <= args.eco <= 100:
        sys.exit("--eco: нужно 1..100")

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    stats = load_stats()
    targets = load_targets()
    target_hex = list(targets)
    bloom = Bloom()
    save_stats(stats)                          # счётчики видны сразу (status)
    print(f"СИД-ЛОТО | целей: {len(targets)} | всего билетов до старта: "
          f"{stats['tickets']} | память фильтра: {len(bloom.mem)>>20} МБ")

    n = skips = hits = 0
    best_lcp, last_phrase = 0, ""
    t0 = time.time()
    try:
        while args.tickets == 0 or n < args.tickets:
            t_ticket = time.perf_counter()
            phrase = random_phrase()
            if bloom.add(phrase):              # защита от повторов, O(1)
                skips += 1
                continue

            master = master_from_mnemonic(phrase)
            hit_info = ""
            for no in PROBE:
                h = child_h160(master, no)
                if h in targets:
                    hits += 1
                    hit_info = f"ДЖЕКПОТ пазл #{targets[h]}"
                    with open(JACKPOT_FILE, "a") as jf:
                        jf.write(f"{phrase}\n  puzzle #{targets[h]} hash160={h}\n")
                    event(f"ДЖЕКПОТ: {phrase} -> #{targets[h]} {h}")
                    print(f"\n!!! ДЖЕКПОТ: {phrase} → пазл #{targets[h]}", flush=True)
                else:
                    m = max(lcp(h, t) for t in target_hex)
                    if m > best_lcp:
                        best_lcp, last_phrase = m, phrase
                        if m > stats["best_lcp"] and m >= 4:
                            event(f"рекорд префикса {m} hex: {phrase}")

            n += 1
            last_phrase = phrase

            if args.eco and args.eco < 100:   # троттлинг: держим целевой % CPU
                pause = (time.perf_counter() - t_ticket) * (100.0 / args.eco - 1.0)
                if pause > 0:
                    time.sleep(pause)

            if args.lines:
                print(f"{time.strftime('%H:%M:%S')} | #{n:>7} | {phrase} | "
                      f"{hit_info or 'нет совпадений'}", flush=True)
            elif n % REPORT_EVERY == 0:
                rate = n / (time.time() - t0)
                print(f"{time.strftime('%H:%M:%S')} | +{n} | {rate:.1f}/сек | "
                      f"всего {stats['tickets'] + n} | "
                      f"последняя: {phrase} | {hit_info or 'нет совпадений'}",
                      flush=True)
            if n % SAVE_EVERY == 0:
                save_stats({**stats, "tickets": stats["tickets"] + n,
                            "seconds": stats["seconds"] + time.time() - t0,
                            "jackpots": stats["jackpots"] + hits,
                            "best_lcp": max(stats["best_lcp"], best_lcp),
                            "sessions": stats["sessions"],
                            "last_phrase": last_phrase})
    except KeyboardInterrupt:
        pass
    finally:
        dt = time.time() - t0
        stats.update(tickets=stats["tickets"] + n, seconds=stats["seconds"] + dt,
                     jackpots=stats["jackpots"] + hits,
                     best_lcp=max(stats["best_lcp"], best_lcp),
                     sessions=stats["sessions"] + 1, last_phrase=last_phrase)
        save_stats(stats)
        print(f"\nИтог сессии: +{n} билетов за {dt:.0f}с ({n/max(dt,1e-9):.1f}/сек), "
              f"пропущено повторов: {skips}, джекпотов: {hits}")
        print(f"Всего за всё время: {stats['tickets']} билетов, "
              f"{stats['seconds']/3600:.1f} ч работы")
        print(f"Исчерпано лототрона: {stats['tickets']/SPACE*100:.2e}%")


if __name__ == "__main__":
    main()
