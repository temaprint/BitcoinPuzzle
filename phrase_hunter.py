#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Охота за сид-фразой пазла (образовательная демонстрация).

Гипотеза: если угадать BIP39-фразу создателя, то по ней мгновенно вычисляются
ВСЕ 256 пазловых ключей (включая 78 нерешённых, ~903 BTC).

Метод: составляем фразы из словаря BIP39 (bip39_english.txt, 2048 слов),
прогоняем через конвейер puzzle_generator (фраза → BIP32 → дети → стирание
бит → адрес) и сверяем адреса детей со всеми 256 адресами пазла (b1000.jsonc).

Почему это самая тяжёлая дверь (считается ниже прямо во время прогона):
12-словная фраза несёт 128 бит энтропии (+ 4 бита контрольной суммы).
Валидных фраз 2^128 ≈ 3.4e38. При любой достижимой скорости перебора
остаток времени ~ 10^20 возрастов Вселенной. Для сравнения: решить самый
лёгкий нерешённый пазел #71 напрямую (2^71) в 2^57 ≈ 1.4e17 раз ПРОЩЕ,
чем найти 12-словную фразу. Т.е. идти через фразы — худшая стратегия из всех.

Запуск:  python3 phrase_hunter.py            # шутки + бенчмарк + охота
"""

import hashlib
import json
import random
import re
import sys
import time

from puzzle_generator import master_from_mnemonic, erase_bits, compressed_pub, hash160, B58_ALPHABET  # noqa

# ── словарь BIP39 и контрольная сумма ────────────────────────────────────────
WORDS = [w.strip() for w in open("bip39_english.txt") if w.strip()]
INDEX = {w: i for i, w in enumerate(WORDS)}
assert len(WORDS) == 2048


def phrase_is_valid(words: list[str]) -> bool:
    """BIP39: 12 слов = 132 бита = 128 энтропии + 4 бита SHA256-чексуммы."""
    if len(words) != 12:
        raise ValueError("демо работает с 12-словными фразами")
    bits = "".join(f"{INDEX[w]:011b}" for w in words)
    entropy, checksum = bits[:128], bits[128:]
    ent_bytes = int(entropy, 2).to_bytes(16, "big")
    good = f"{hashlib.sha256(ent_bytes).digest()[0]:08b}"[:4]
    return checksum == good


def patch_last_word(first11: list[str]) -> list[str]:
    """Подбирает 12-е слово так, чтобы фраза прошла контрольную сумму.
    Валидных вариантов всегда 2048/16 = 128 — шутка обязана кончаться
    одним из них, иначе это не кошелёк."""
    valid = []
    for w in WORDS:
        if phrase_is_valid(first11 + [w]):
            valid.append(w)
    return valid


# ── адреса всех 256 пазлов ──────────────────────────────────────────────────
def load_puzzle_addresses() -> dict[str, int]:
    raw = open("b1000.jsonc").read()
    data = json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M))
    return {p["address"]["value"]: p["key"]["bits"] for p in data["puzzles"]}


def b58check(payload: bytes) -> str:
    data = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    n, s = int.from_bytes(data, "big"), ""
    while n:
        n, r = divmod(n, 58)
        s = B58_ALPHABET[r] + s
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + s


def child_address(master, puzzle_no: int, mode: str = "force") -> str:
    """Адрес пазла #N для данной фразы (родитель m/0', ребёнок #N)."""
    child = master.derive_child(puzzle_no)
    k = erase_bits(child.key, puzzle_no, mode)
    return b58check(b"\x00" + hash160(compressed_pub(k)))


PROBE = (66, 71)  # дети для сверки: #66 решён (адрес известен), #71 цель сообщества


def check_phrase(mnemonic: str, targets: dict) -> bool:
    master = master_from_mnemonic(mnemonic)
    for no in PROBE:
        if child_address(master, no) in targets:
            return True
    return False


def joke_phrases(n: int, rng: random.Random) -> list[str]:
    """«Шутки»: случайные 11 слов + валидное по чексумме 12-е."""
    out = []
    while len(out) < n:
        first11 = rng.sample(WORDS, 11)
        endings = patch_last_word(first11)
        if endings:
            out.append(" ".join(first11 + [rng.choice(endings)]))
    return out


def fmt_seconds(s: float) -> str:
    uni = 4.35e17  # возраст Вселенной, сек
    if s < uni:
        return f"{s:.2e} сек"
    return f"{s / uni:.2e} возрастов Вселенной"


def main():
    print("=== 1. Шутка обязана пройти контрольную сумму BIP39 ===")
    for joke in (["evil", "zoo", "zebra"], ["absurd", "acid", "ahead"]):
        assert all(w in INDEX for w in joke), "слова не из словаря"
        first11 = joke + random.Random(joke[0]).sample(WORDS, 8)
        endings = patch_last_word(first11)
        print(f"  «{' '.join(first11)} …»")
        print(f"    валидных продолжений: {len(endings)}, например: {endings[:5]} …")
        print(f"    полный кошелёк: «{' '.join(first11 + [endings[0]])}»")

    targets = load_puzzle_addresses()
    print(f"\n=== 2. Сверка со всеми {len(targets)} адресами пазла ===")
    rng = random.Random(20260927)

    # бенчмарк скорости
    t0, N = time.time(), 50
    hits = sum(check_phrase(p, targets) for p in joke_phrases(N, rng))
    dt = time.time() - t0
    rate = N / dt
    print(f"  {N} шуток проверено за {dt:.1f}s → {rate:.1f} фраз/сек; совпадений: {hits}")

    space12, space24 = 2**128, 2**256
    print(f"\n=== 3. Математика двери ===")
    print(f"  12-словных фраз:   2^128 = {space12:.3e}")
    print(f"  при {rate:.0f} фраз/сек весь объём: {fmt_seconds(space12 / rate)}")
    print(f"  24-словных фраз:   2^256 (если фраза длиннее — ещё хуже)")
    print(f"  пазл #71 напрямую: 2^71  = {2**71:.3e} → в {2**57:.1e} раз ПРОЩЕ, чем фраза")
    print(f"  (для справки: все компьютеры Земли вместе ~10^22 оп/сек →")
    print(f"   2^128 заняло бы ~10^16 лет при идеальной скорости)")

    # короткая живая охота
    print(f"\n=== 4. Живая охота (200 фраз) ===")
    t0, hits = time.time(), 0
    for p in joke_phrases(200, rng):
        if check_phrase(p, targets):
            hits += 1
            print("  !!! СОВПАДЕНИЕ:", p)
    print(f"  проверено 200, совпадений: {hits} ({time.time()-t0:.0f}s)")
    print("\nВывод: логика верна, но дверь в 10^17 раз тяжелее самой сложной")
    print("прямой атаки. Фраза может «пересечься» только одним способом —")
    print("если она и есть фраза создателя. Математика её не найдёт;")
    print("найдёт только утечка: старый пост, ноутбук, фото, черновик 2015 года.")


if __name__ == "__main__":
    sys.exit(main())
