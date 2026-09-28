# Bitcoin Puzzle Lab

**Educational reconstruction of the ~1000 BTC Bitcoin Puzzle generation pipeline + an honest "seed lottery" demonstration.**
**Образовательная реконструкция конвейера генерации Bitcoin Puzzle (~1000 BTC) + честная демонстрация «сид-лото».**

Python 3.9+ · zero dependencies (stdlib only) · macOS / Linux / Windows

---

# Русский

## Что это и зачем

15 января 2015 года аноним saatoshi_rising создал транзакцию на 256 адресов —
**Bitcoin Puzzle Transaction**. У каждого адреса #N приватный ключ лежит в
диапазоне [2^(N-1), 2^N): чем больше номер, тем меньше бит ключа стёрто —
и тем сложнее его найти. Призовой фонд ~988 BTC, решено 83 пазла из 256,
на нерешённых лежит ~903 BTC.

Этот проект отвечает на вопрос: **«как этот пазл был создан?»** — от
сид-фразы до адреса, с проверкой каждого звена на реальных данных.
Плюс «сид-лото»: генератор случайных фраз, который наглядно (и честно)
показывает, почему поиск фразы создателя — самая тяжёлая дверь в пазле.

> Это образовательный проект. Никакой цели «взломать» пазл нет:
> вероятности ниже — см. раздел «Математика безнадёжности».

## Состав проекта

| Файл | Что это |
|------|---------|
| `puzzle_generator.py` | Референсный конвейер: фраза → BIP39 → BIP32 → стирание бит → secp256k1 → адрес. Самопроверка на известных пазлах |
| `winers.md` | Все 83 решённых пазла: адреса, полные ключи, WIF, даты. Каждый ключ криптографически верифицирован |
| `bip32_check.md` | Анализ: использовалась ли BIP32, что проверяемо, что нет; обзор библиотек |
| `phrase_hunter.py` | Демонстрация охоты за фразой: шутки-фразы, контрольная сумма, сверка с 256 адресами, бенчмарк |
| `lotto_hunter.py` | Сид-лото: случайные фразы на CSPRNG, Bloom-фильтр, счётчики в JSON |
| `lotto_daemon.sh` | Фоновый менеджер лото: start/stop/status/log/hits, 3 режима нагрузки |
| `update_repo.sh` | Обновление GitHub-репы одним вызовом: init → коммит → пуш |
| `bip39_english.txt` | Словарь BIP39 (2048 слов) — «библиотека фраз» |
| `b1000.jsonc` | Датасет всех 256 пазлов (из крейта `boha`, MIT) || `lotto_stats.json` | Накопленные счётчики лото (всего билетов и пр.) |

## Быстрый старт

```bash
# 1. Конвейер: самопроверка + демо-лестница сложности
python3 puzzle_generator.py

#    своя фраза, первые 20 «пазлов» из неё
python3 puzzle_generator.py --mnemonic "your twelve words here ..." --list 20

# 2. Почему чистое стирание бит не работает (наглядно)
python3 puzzle_generator.py --mode mask

# 3. Демонстрация охоты за фразой
python3 phrase_hunter.py

# 4. Сид-лото в фоне
./lotto_daemon.sh start nice   # режим нагрузки: full | nice | eco | eco25...
./lotto_daemon.sh status       # статистика
./lotto_daemon.sh log          # живой хвост лога
./lotto_daemon.sh hits         # события и джекпоты
./lotto_daemon.sh stop
```

## Конвейер генерации пазла

```
сид-фраза (12/24 слова BIP39)
   │  PBKDF2-HMAC-SHA512, 2048 итераций, salt = "mnemonic" + passphrase
   ▼
512-битный seed
   │  HMAC-SHA512(key = "Bitcoin seed")
   ▼
мастер-ключ (256 бит) + chain code (256 бит)        ← BIP32
   │  CKD: I = HMAC-SHA512(cc, data); k_child = IL + k_parent mod n
   ▼
256 последовательных дочерних ключей (m/0'/N)
   │  стирание бит: ключ #N приводится к диапазону [2^(N-1), 2^N)
   ▼
пазловые ключи: #1 = 1 бит … #160 = 160 бит
   │  K = k × G на secp256k1 (сжатый)
   │  Hash160 = RIPEMD160(SHA256(K))
   ▼
P2PKH-адреса "1..." (Base58Check)
```

**Ключевое открытие проекта.** У всех 83 решённых ключей ровно N бит —
значит создатель не просто обнулял старшие биты (тогда у половины пазлов
ключ выпал бы из диапазона, вероятность совокупного совпадения 2^-83), а
приводил ключ в диапазон принудительно:

```python
k = 2**(n-1) | (child_key % 2**(n-1))   # режим "force"
```

Следствие: адрес пазла **#1 одинаков для любой сид-фразы** — ключ всегда
равен 1, это публичный ключ точки-генератора secp256k1.

## Что проверено (валидация)

| Проверка | Результат |
|----------|-----------|
| Все 83 решённых ключа → k×G → Hash160 → Base58Check | 83/83 адреса совпали |
| Битовая длина каждого ключа = номеру пазла | 83/83 |
| Реализация BIP32 против официальных векторов спецификации | 17/17 (включая hardened-ветку с префиксом 0x00) |
| BIP39-сид против библиотеки `mnemonic` | совпадение |
| Реализация secp256k1 | 1×G = эталонный генератор |

Использовалась ли BIP32 создателем — криптографически подтвердить нельзя
(HMAC однонаправлен, сид не публиковался), но все публичные данные с ней
согласованы. Подробности — в `bip32_check.md`.

## Математика безнадёжности (сид-лото)

| Событие | Вероятность |
|---|---|
| Билет лото = фраза создателя (12 слов) | 1 из 2^128 ≈ 1 из 3.4×10^38 |
| Джекпот Powerball | 1 из 2.9×10^8 |
| Решить пазл #71 напрямую | 2^71 — в 1.4×10^17 раз проще, чем искать фразу |
| Решить пазл #160 (kangaroo) | 2^80 — всё равно в 2^48 раз проще фразы |

При ~66 билетах/сек полный объём — 1.7×10^19 возрастов Вселенной.
Фраза может «пересечься» с пазлом только одним способом: если она и есть
фраза создателя. Найдёт её не математика, а утечка (старый пост, черновик,
фото). Лото оставлено как честная игра с бесплатными билетами.

## Ресурсы лото

- Память: **O(1)** — Bloom-фильтр 2 МБ вместо множества всех фраз; RSS ~23 МБ всегда
- Диск: события + JSON-счётчики; run-лог с ротацией на 5 МБ (потолок ~10 МБ)
- Нагрузка: `full` (100% ядра), `nice` (приоритет 20, скорость та же),
  `eco`/`ecoNN` (адаптивный троттлинг, замер: eco → ~45%, eco25 → ~24%)

## Источники данных

- [privatekeys.pw — puzzle tracker](https://privatekeys.pw/puzzles/bitcoin-puzzle-tx)
- [oritwoen/boha — датасет b1000.jsonc](https://github.com/oritwoen/boha) (MIT)
- [BIP32 спецификация + тест-векторы](https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki)
- [Тема пазла на bitcointalk](https://bitcointalk.org/index.php?topic=5218972)

---

# English

## What & Why

On January 15, 2015 an anonymous user saatoshi_rising created a transaction
funding 256 addresses — the **Bitcoin Puzzle Transaction**. Each puzzle #N
has its private key inside [2^(N-1), 2^N): the higher the number, the fewer
bits were erased from the key — and the harder it is to find. Prize pool
~988 BTC, 83 of 256 puzzles solved, ~903 BTC still waiting.

This project answers the question: **"how was this puzzle created?"** —
from a seed phrase to an address, with every stage verified against real
data. Plus a "seed lottery": a random-phrase generator that honestly
demonstrates why searching for the creator's phrase is the heaviest door
in the whole puzzle.

> Educational project. There is no intent to "crack" the puzzle — see the
> odds table below.

## Project contents

| File | What it is |
|------|------------|
| `puzzle_generator.py` | Reference pipeline: phrase → BIP39 → BIP32 → bit erasure → secp256k1 → address. Self-tests against known puzzles |
| `winers.md` | All 83 solved puzzles: addresses, full keys, WIF, dates. Every key cryptographically verified |
| `bip32_check.md` | Analysis: was BIP32 used, what is checkable and what isn't; library overview |
| `phrase_hunter.py` | Phrase-hunt demo: joke phrases, checksum rules, matching against 256 addresses, benchmark |
| `lotto_hunter.py` | Seed lottery: CSPRNG phrases, Bloom filter, JSON counters |
| `lotto_daemon.sh` | Background lottery manager: start/stop/status/log/hits, 3 load modes |
| `update_repo.sh` | One-call GitHub repo update: init → commit → push |
| `bip39_english.txt` | BIP39 wordlist (2048 words) — the "phrase library" |
| `b1000.jsonc` | Dataset of all 256 puzzles (from the `boha` crate, MIT) || `lotto_stats.json` | Accumulated lottery counters (all-time tickets etc.) |

## Quick start

```bash
# 1. Pipeline: self-test + difficulty-ladder demo
python3 puzzle_generator.py

#    your own phrase → first 20 "puzzles" from it
python3 puzzle_generator.py --mnemonic "your twelve words here ..." --list 20

# 2. See why plain bit-masking cannot work
python3 puzzle_generator.py --mode mask

# 3. Phrase-hunt demo
python3 phrase_hunter.py

# 4. Seed lottery in the background
./lotto_daemon.sh start nice   # load mode: full | nice | eco | eco25...
./lotto_daemon.sh status       # stats
./lotto_daemon.sh log          # live log tail
./lotto_daemon.sh hits         # events & jackpots
./lotto_daemon.sh stop
```

## The puzzle generation pipeline

```
seed phrase (12/24 BIP39 words)
   │  PBKDF2-HMAC-SHA512, 2048 iterations, salt = "mnemonic" + passphrase
   ▼
512-bit seed
   │  HMAC-SHA512(key = "Bitcoin seed")
   ▼
master key (256 bits) + chain code (256 bits)        ← BIP32
   │  CKD: I = HMAC-SHA512(cc, data); k_child = IL + k_parent mod n
   ▼
256 consecutive child keys (m/0'/N)
   │  bit erasure: key #N forced into [2^(N-1), 2^N)
   ▼
puzzle keys: #1 = 1 bit … #160 = 160 bits
   │  K = k × G on secp256k1 (compressed)
   │  Hash160 = RIPEMD160(SHA256(K))
   ▼
P2PKH "1..." addresses (Base58Check)
```

**Key finding of this project.** All 83 solved keys have exactly N bits —
so the creator did not simply zero out the top bits (half of the keys would
have fallen out of range; joint probability of the observed outcome 2^-83).
Instead the key was forced back into the range:

```python
k = 2**(n-1) | (child_key % 2**(n-1))   # "force" mode
```

Corollary: puzzle **#1's address is identical for every seed phrase** — the
key is always 1, the public key of the secp256k1 generator point.

## What was verified

| Check | Result |
|-------|--------|
| All 83 solved keys → k×G → Hash160 → Base58Check | 83/83 addresses match |
| Bit-length of each key equals its puzzle number | 83/83 |
| BIP32 implementation vs official spec test vectors | 17/17 (incl. hardened branch with the 0x00 prefix) |
| BIP39 seed vs the `mnemonic` library | match |
| secp256k1 implementation | 1×G equals the canonical generator |

Whether BIP32 is what the creator actually used cannot be proven
cryptographically (HMAC is one-way, the seed was never published), but all
public data is consistent with it. Details in `bip32_check.md`.

## The mathematics of futility (seed lottery)

| Event | Odds |
|---|---|
| One lottery ticket = creator's 12-word phrase | 1 in 2^128 ≈ 1 in 3.4×10^38 |
| Powerball jackpot | 1 in 2.9×10^8 |
| Solve puzzle #71 directly | 2^71 — 1.4×10^17 times easier than finding the phrase |
| Solve puzzle #160 (kangaroo) | 2^80 — still 2^48 times easier than the phrase |

At ~66 tickets/sec the full space takes 1.7×10^19 ages of the universe.
A phrase can only "intersect" the puzzle if it *is* the creator's phrase —
which will be found by a leak (an old post, a draft, a photo), not by math.
The lottery stays as an honest game with free tickets.

## Lottery resource profile

- Memory: **O(1)** — a 2 MB Bloom filter instead of a set of all phrases; RSS ~23 MB flat
- Disk: events + JSON counters only; run log rotated at 5 MB (~10 MB ceiling)
- Load: `full` (100% of one core), `nice` (priority 20, same speed),
  `eco`/`ecoNN` (adaptive throttling; measured: eco → ~45%, eco25 → ~24%)

## Data sources

- [privatekeys.pw — puzzle tracker](https://privatekeys.pw/puzzles/bitcoin-puzzle-tx)
- [oritwoen/boha — b1000.jsonc dataset](https://github.com/oritwoen/boha) (MIT)
- [BIP32 spec + test vectors](https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki)
- [Puzzle thread on bitcointalk](https://bitcointalk.org/index.php?topic=5218972)
