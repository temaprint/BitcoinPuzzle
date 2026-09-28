#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Референсная реконструкция алгоритма генерации Bitcoin Puzzle Transaction (~1000 BTC).

Полная последовательность (как описал создатель saatoshi_rising в 2015):

    сид-фраза (BIP39)
      → PBKDF2-HMAC-SHA512(2048 итераций, salt="mnemonic"+passphrase) → 512-битный seed
      → BIP32: HMAC-SHA512(key="Bitcoin seed", seed) → мастер-ключ + chain code
      → 256 последовательных дочерних ключей CKD (child derivation)
      → стирание бит: у ключа #N остаются младшие N бит (сложность растёт как 2^N)
      → secp256k1: публичный ключ K = k*G (сжатый)
      → Hash160 = RIPEMD160(SHA256(K))
      → Base58Check(0x00 || Hash160) → P2PKH-адрес "1..."

Цитата создателя (bitcointalk): "There is no pattern. It is just consecutive keys
from a deterministic wallet (masked with leading 000...0001 to set difficulty)."

ВАЖНОЕ УТОЧНЕНИЕ (устанавливается по самим решённым ключам):
простое обнуление старших бит даёт число < 2^(N-1) с вероятностью 1/2, а у всех
83 решённых пазлов ключ имеет РОВНО N бит. Значит создатель принудительно
возвращал ключ в диапазон [2^(N-1), 2^N):  k_n = 2^(N-1) + (child mod 2^(N-1)).
В скрипте оба режима: mode="force" (так строился реальный пазл) и mode="mask"
(буквальное обнуление старших бит).

Проверить, какая именно сид-фраза/путь деривации использовались создателем,
публично НЕВОЗМОЖНО: HMAC однонаправлен, сид никогда не публиковался.
Скрипт самопроверяется на известных решённых ключах (см. selftest).

Зависимостей нет — только стандартная библиотека (hashlib, hmac).
Запуск:  python3 puzzle_generator.py            # selftest + демо-лестница
         python3 puzzle_generator.py --list 20  # первые 20 пазлов своей фразы
"""

import argparse
import hashlib
import hmac
import sys

# ── secp256k1 ────────────────────────────────────────────────────────────────
P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
     0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)

G_BYTES = bytes.fromhex("0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798")


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % P == 0:
        return None
    if p == q:
        lam = (3 * p[0] * p[0]) * pow(2 * p[1], -1, P) % P
    else:
        lam = (q[1] - p[1]) * pow(q[0] - p[0], -1, P) % P
    x = (lam * lam - p[0] - q[0]) % P
    return (x, (lam * (p[0] - x) - p[1]) % P)


def point_mul(k: int):
    """k * G на secp256k1 (двойное сложение)."""
    R, A = None, G
    while k:
        if k & 1:
            R = _add(R, A)
        A = _add(A, A)
        k >>= 1
    return R


def compressed_pub(k: int) -> bytes:
    if k == 0:
        raise ValueError("k = 0 — точка на бесконечности, публичного ключа нет")
    x, y = point_mul(k)
    return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")


# ── хэши и адрес ─────────────────────────────────────────────────────────────
def hash160(b: bytes) -> bytes:
    return hashlib.new("ripemd160", hashlib.sha256(b).digest()).digest()


B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def base58check(payload: bytes) -> str:
    data = payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    num, s = int.from_bytes(data, "big"), ""
    while num:
        num, rem = divmod(num, 58)
        s = B58_ALPHABET[rem] + s
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + s


def p2pkh_address(k: int) -> str:
    return base58check(b"\x00" + hash160(compressed_pub(k)))


# ── BIP39: мнемоника → seed ─────────────────────────────────────────────────
def mnemonic_to_seed(mnemonic: str, passphrase: str = "") -> bytes:
    """PBKDF2-HMAC-SHA512, 2048 итераций, salt = 'mnemonic' + passphrase."""
    mnemonic = " ".join(mnemonic.split())  # нормализация пробелов
    salt = "mnemonic" + passphrase
    return hashlib.pbkdf2_hmac(
        "sha512", mnemonic.encode("utf-8"), salt.encode("utf-8"), 2048
    )


# ── BIP32: HD-дерево ────────────────────────────────────────────────────────
class BIP32Node:
    """Минимальный BIP32: мастер-ключ и деривация детей (hardened и обычных)."""

    def __init__(self, key: int, chain_code: bytes):
        self.key = key
        self.chain_code = chain_code

    @classmethod
    def from_seed(cls, seed: bytes) -> "BIP32Node":
        I = hmac.new(b"Bitcoin seed", seed, hashlib.sha512).digest()
        return cls(int.from_bytes(I[:32], "big"), I[32:])

    def derive_child(self, index: int) -> "BIP32Node":
        if index >= 0x80000000:  # hardened: 0x00 || ser256(k_par) || ser32(i)
            data = b"\x00" + self.key.to_bytes(32, "big") + index.to_bytes(4, "big")
        else:                    # normal: serP(K_par) || ser32(i)
            data = compressed_pub(self.key) + index.to_bytes(4, "big")
        I = hmac.new(self.chain_code, data, hashlib.sha512).digest()
        child = (int.from_bytes(I[:32], "big") + self.key) % N
        return BIP32Node(child, I[32:])


def master_from_mnemonic(mnemonic: str, passphrase: str = "") -> BIP32Node:
    return BIP32Node.from_seed(mnemonic_to_seed(mnemonic, passphrase))


# ── стирание бит — «лестница сложности» ─────────────────────────────────────
def erase_bits(child_key: int, n_bits: int, mode: str = "force") -> int:
    """
    Пазл #N: ключ лежит в [2^(N-1), 2^N), т.е. ровно N значащих бит,
    старшие 256-N бит стёрты.

    mode="force" — как в реальном пазле: младшие N-1 бит берутся от дочернего
                   ключа, старший бит принудительно 1:
                   k = 2^(N-1) | (child mod 2^(N-1))
                   (иначе у половины пазлов ключ выпал бы из диапазона —
                   что противоречит всем 83 решённым ключам)
    mode="mask"  — буквальное обнуление старших бит: k = child mod 2^N
                   (годится для иллюстрации, но не для точной реконструкции)
    """
    if n_bits < 1 or n_bits > 256:
        raise ValueError("n_bits должно быть 1..256")
    if mode == "force":
        top = 1 << (n_bits - 1)
        return top | (child_key & (top - 1))
    if mode == "mask":
        return child_key & ((1 << n_bits) - 1)
    raise ValueError("mode: 'force' | 'mask'")


def generate_puzzle(mnemonic: str, puzzle_no: int, *, mode: str = "force",
                    base_path: str = "m/0'", passphrase: str = "") -> dict:
    """
    Пазл #N из сид-фразы.
    base_path — путь до родителя (по умолчанию m/0', как в BIP44-кошельках
    аккаунт 0); дети берутся подряд: base_path/N для N = 1..256.
    Возвращает ключ, WIF-подобное представление не строим — только суть.
    """
    node = master_from_mnemonic(mnemonic, passphrase)
    for part in base_path[2:].split("/"):
        if not part:
            continue
        hardened = part.endswith(("'", "h"))
        idx = int(part[:-1] if hardened else part)
        node = node.derive_child(idx + 0x80000000 if hardened else idx)

    child = node.derive_child(puzzle_no)          # последовательный ребёнок #N
    k = erase_bits(child.key, puzzle_no, mode)    # стираем биты → сложность 2^N
    return {
        "puzzle": puzzle_no,
        "child_key": child.key,
        "puzzle_key": k,
        "pubkey": compressed_pub(k).hex(),
        "address": p2pkh_address(k),
    }


# ── самопроверка на реальных решённых пазлах ─────────────────────────────────
KNOWN = [  # (№, ключ hex, адрес) — проверено по winers.md / privatekeys.pw
    (1,  "1",                  "1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH"),
    (5,  "15",                 "1E6NuFjCi27W5zoXg8TRdcSRq84zJeBW3k"),
    (17, "1764f",              "1HduPEXZRdG26SUT5Yk83mLkPyjnZuJ7Bm"),
    (50, "22bd43c2e9354",      "1MEzite4ReNuWaL5Ds17ePKt2dCxWEofwk"),
    (66, "2832ed74f2b5e35ee",  "13zb1hQbWVsc2S7ZTZnP2G4undNNpdh5so"),
    (69, "101d83275fb2bc7e0c", "19vkiEajfhuZ8bs8Zu2jgmC6oqZbWqhxhG"),
]


def selftest() -> bool:
    print("SELFTEST: ключ → pubkey → Hash160 → Base58Check против известных адресов")
    ok = True
    for no, hexkey, addr in KNOWN:
        got = p2pkh_address(int(hexkey, 16))
        good = got == addr
        ok &= good
        print(f"  #{no:>3}  key=0x{hexkey:<20} → {got}  "
              f"[{'OK' if good else 'FAIL, ожидалось ' + addr}]")
    # контроль точки-генератора: 1*G
    assert compressed_pub(1) == G_BYTES, "secp256k1 сломан"
    print(f"  1*G = {G_BYTES.hex()[:16]}… (совпадает с эталоном secp256k1)")
    print("SELFTEST:", "пройден" if ok else "ПРОВАЛЕН")
    return ok


def demo(mnemonic: str, count: int = 8, mode: str = "force"):
    print(f"\nДЕМО: лестница сложности из сид-фразы (mode={mode}), первые {count} пазлов")
    print(f"  мнемоника: {mnemonic[:60]}…")
    seed = mnemonic_to_seed(mnemonic)
    m = BIP32Node.from_seed(seed)
    print(f"  seed (BIP39, 512 бит): {seed[:16].hex()}…")
    print(f"  мастер-ключ (BIP32):   {m.key:064x}")
    print(f"  chain code:            {m.chain_code.hex()[:32]}…")
    print()
    print(f"  {'#':>3} {'пазл-ключ (hex, младшие N бит)':>40} адрес")
    for no in range(1, count + 1):
        try:
            r = generate_puzzle(mnemonic, no, mode=mode)
            compact = hex(r["puzzle_key"])[2:]
            print(f"  {no:>3} {compact:>40} {r['address']}")
        except ValueError:
            print(f"  {no:>3} {'0':>40} — ключ выродился в 0 (не бывает в mode='force')")


def main():
    ap = argparse.ArgumentParser(description="Реконструкция генерации Bitcoin Puzzle")
    ap.add_argument("--mnemonic", default=None, help="своя сид-фраза (12/24 слова)")
    ap.add_argument("--list", type=int, default=0, metavar="N",
                    help="показать первые N пазлов для своей фразы")
    ap.add_argument("--mode", choices=["force", "mask"], default="force")
    args = ap.parse_args()

    if not selftest():
        sys.exit(1)

    # демо на стандартном BIP39-векторе (энтропия из нулей)
    demo("abandon abandon abandon abandon abandon abandon "
         "abandon abandon abandon abandon abandon about", 8, args.mode)

    if args.mnemonic:
        demo(args.mnemonic, args.list or 8, args.mode)
    elif args.list:
        print("\n(--list требует --mnemonic)")


if __name__ == "__main__":
    main()
