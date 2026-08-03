#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v kotlinc >/dev/null 2>&1 || ! command -v kotlin >/dev/null 2>&1; then
  echo "SKIP: Kotlin compiler/runtime unavailable."
  exit 0
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/com/google/gson/annotations" "$TMP/test"
cat > "$TMP/com/google/gson/annotations/SerializedName.kt" <<'KOTLIN'
package com.google.gson.annotations
@Target(AnnotationTarget.FIELD, AnnotationTarget.PROPERTY, AnnotationTarget.VALUE_PARAMETER)
annotation class SerializedName(val value: String)
KOTLIN
cat > "$TMP/test/Main.kt" <<'KOTLIN'
package test
import com.noamjan.homeguard.data.PairingPayload
import com.noamjan.homeguard.data.normalizeBaseUrl
import com.noamjan.homeguard.data.normalizeWebSocketUrl

fun main() {
    check(normalizeBaseUrl("http://192.168.1.9:8765") == "http://192.168.1.9:8765/")
    check(normalizeBaseUrl("https://homeguard.example") == "https://homeguard.example/")
    check(runCatching { normalizeBaseUrl("http://example.com") }.isFailure)
    check(normalizeWebSocketUrl("wss://signal.example.com/ws") == "wss://signal.example.com/ws")
    check(runCatching { normalizeWebSocketUrl("ws://signal.example.com") }.isFailure)
    check(runCatching { normalizeWebSocketUrl("wss://user:secret@signal.example.com") }.isFailure)
    check(runCatching { normalizeBaseUrl("ftp://192.168.1.9") }.isFailure)
    val raw = "homeguard://pair?url=http%3A%2F%2F192.168.1.9%3A8765&code=${"a".repeat(64)}"
    val payload = PairingPayload.parse(raw)
    check(payload.url == "http://192.168.1.9:8765/")
    check(payload.code.length == 64)
    println("Android pure Kotlin security checks passed")
}
KOTLIN
kotlinc \
  "$TMP/com/google/gson/annotations/SerializedName.kt" \
  "$ROOT/android-app/app/src/main/java/com/noamjan/homeguard/data/Models.kt" \
  "$TMP/test/Main.kt" \
  -d "$TMP/tests.jar"
kotlin -classpath "$TMP/tests.jar" test.MainKt
