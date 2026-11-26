# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Подпись файлов с официального адреса программы — одна проверка на всё, что программа оттуда берёт: файл обновления
программы (update.py: update/latest.json) и каталог одобренных планов (plancat.py: plans/index.json).

Договорённость с инструментами выпуска (release/publish.py, release/plans.py): подпись — ECDSA P-256 над SHA-256 от
точных байтов файла; рядом с файлом лежит <файл>.sig — base64 от r‖s (64 байта). Проверяет сама Windows (bcrypt.dll)
открытым ключом, вписанным в программу (updatekey.py, его пишет publish.py keygen). Сторонних библиотек шифрования в
программе нет. Файл читается только после того, как подпись сошлась.
"""
import base64
import ctypes
import hashlib
import struct
import sys
import threading

# Открытый ключ P-256 в виде DER SubjectPublicKeyInfo: этот заголовок, затем 04 и точка X‖Y (по 32 байта)
SPKI_P256 = bytes.fromhex('3059301306072a8648ce3d020106082a8648ce3d030107034200')


class Refused(Exception):
    """Файл не принят. code — почему: sig (подпись не сошлась или не та), format (не тот файл), nokey (нечем
    проверять) и коды того, кто читает файл (older…); detail — подробность для журнала."""

    def __init__(self, code, detail=''):
        super().__init__('%s %s' % (code, detail))
        self.code, self.detail = code, detail


def public_point(spki):
    """Точка открытого ключа X‖Y (64 байта) из DER SubjectPublicKeyInfo ключа P-256 (байты или base64). Не такой
    ключ — None."""
    if isinstance(spki, str):
        try:
            spki = base64.b64decode(spki, validate=True)
        except ValueError:
            return None
    if not isinstance(spki, bytes) or len(spki) != 91 or not spki.startswith(SPKI_P256) or spki[26] != 4:
        return None
    return spki[27:]


def embedded_key():
    """Открытый ключ подписи, вписанный в программу (updatekey.py); не вписан — None."""
    try:
        import updatekey
    except ImportError:
        return None
    return public_point(getattr(updatekey, 'PUBLIC_KEY', None))


def key_name():
    """Отпечаток вписанного ключа (SHA-256 его DER) для журнала программы — сверить с тем, что назвал keygen; ключа нет —
    'none'."""
    try:
        import updatekey
    except ImportError:
        return 'none'
    return getattr(updatekey, 'FINGERPRINT', None) or 'none' if embedded_key() else 'none'


_BCRYPT = []
_BCRYPT_LOCK = threading.Lock()


def _bcrypt():
    """bcrypt.dll с объявленными типами аргументов (без них 64-битные описатели обрезаются)."""
    with _BCRYPT_LOCK:
        if not _BCRYPT:
            from ctypes import wintypes as w
            b = ctypes.WinDLL('bcrypt')
            h = ctypes.c_void_p
            b.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(h), w.LPCWSTR, w.LPCWSTR, w.ULONG]
            b.BCryptImportKeyPair.argtypes = [h, h, w.LPCWSTR, ctypes.POINTER(h), ctypes.c_char_p, w.ULONG, w.ULONG]
            b.BCryptVerifySignature.argtypes = [h, ctypes.c_void_p, ctypes.c_char_p, w.ULONG, ctypes.c_char_p, w.ULONG,
                                                w.ULONG]
            b.BCryptDestroyKey.argtypes = [h]
            b.BCryptCloseAlgorithmProvider.argtypes = [h, w.ULONG]
            for f in (b.BCryptOpenAlgorithmProvider, b.BCryptImportKeyPair, b.BCryptVerifySignature, b.BCryptDestroyKey,
                      b.BCryptCloseAlgorithmProvider):
                f.restype = ctypes.c_long           # NTSTATUS: 0 — успех
            _BCRYPT.append(b)
        return _BCRYPT[0]


def verify(data, signature, point):
    """Подпись r‖s (64 байта) над SHA-256 от data сделана закрытым ключом, чья открытая точка — point (X‖Y). Проверяет
    Windows (bcrypt.dll, ECDSA P-256)."""
    if sys.platform != 'win32' or not isinstance(signature, bytes) or len(signature) != 64 \
            or not isinstance(point, bytes) or len(point) != 64:
        return False
    b = _bcrypt()
    alg, key = ctypes.c_void_p(), ctypes.c_void_p()
    if b.BCryptOpenAlgorithmProvider(ctypes.byref(alg), 'ECDSA_P256', None, 0) != 0:
        return False
    try:
        blob = struct.pack('<LL', 0x31534345, 32) + point            # BCRYPT_ECDSA_PUBLIC_P256_MAGIC, длина X и Y
        if b.BCryptImportKeyPair(alg, None, 'ECCPUBLICBLOB', ctypes.byref(key), blob, len(blob), 0) != 0:
            return False
        try:
            digest = hashlib.sha256(data).digest()
            return b.BCryptVerifySignature(key, None, digest, 32, signature, 64, 0) == 0
        finally:
            b.BCryptDestroyKey(key)
    finally:
        b.BCryptCloseAlgorithmProvider(alg, 0)


def check(data, sig, point, limit):
    """Подпись файла с официального адреса: data — его точные байты (не больше limit), sig — содержимое файла .sig
    (base64 от r‖s), point — открытый ключ (X‖Y). Сошлась — ничего; нет — Refused: nokey (нечем проверять), format
    ('size' — не те размеры), sig (не base64, не та длина, не сошлась)."""
    if point is None:
        raise Refused('nokey')
    if not isinstance(data, bytes) or not 0 < len(data) <= limit:
        raise Refused('format', 'size')
    try:
        raw = base64.b64decode(bytes(sig or b'').strip(), validate=True)
    except (ValueError, TypeError):
        raise Refused('sig', 'not base64') from None
    if len(raw) != 64:
        raise Refused('sig', 'length %d' % len(raw))
    if not verify(data, raw, point):
        raise Refused('sig', 'does not match')
