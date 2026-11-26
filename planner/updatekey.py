# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-only
# Copyright © 2026 Sergei Labutin
# Additional terms under GPL-3.0 section 7: see NOTICE.md
"""Открытый ключ подписи обновлений программы (update.py проверяет им latest.json).

Этот файл пишет инструмент выпуска: python release/publish.py keygen — он создаёт закрытый ключ автора вне проекта
(%USERPROFILE%\\.poe2runbook\\release-key.pem) и вписывает сюда открытый. Руками не правится.
Ключа нет (None) — программа не принимает ни одного файла обновления: проверять подпись нечем.
"""
# DER SubjectPublicKeyInfo ключа ECDSA P-256, base64; отпечаток — SHA-256 этого DER (сверить ключ глазами)
PUBLIC_KEY = 'MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAExq998s6mun+c8u5gnmLJ/Vw6Yvi0OHxXLmN0CX3wCVgIUYu//WvOg72k0munNI0tM/E1OnKF3mkJgUedfAe7HA=='
FINGERPRINT = 'bd38b13f5a075b60b1e27e45540308b129c3394785894e7d37fc9b23b2ef3e1c'
