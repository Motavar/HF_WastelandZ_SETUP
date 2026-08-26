"""
hf_crypto.py — WastelandZ Gateway Encryption Module
=====================================================

XOR cipher + Base64 decryption for requests from Reforger.
Drop this file into the gateway/ directory alongside gateway.py.

HOW IT WORKS:
  1. Reforger encrypts JSON payload with XOR using API_KEY
  2. Base64 encodes the result for HTTP transport
  3. Sends: {"data": "<base64_encrypted>", "ts": <timestamp>}
  4. Gateway receives, Base64 decodes, XOR decrypts with same API_KEY
  5. Validates timestamp (reject requests older than MAX_AGE seconds)
  6. Returns the original JSON payload

USAGE IN gateway.py:
  from hf_crypto import decrypt_payload, decrypt_auth_token, validate_timestamp

  # For POST requests (encrypted body):
  data = request.get_json(force=True, silent=True)
  payload = decrypt_payload(data, API_KEY)

  # For GET requests (encrypted auth token):
  token = request.args.get('token', '')
  verb, timestamp = decrypt_auth_token(token, API_KEY)

"""

import base64
import time

# Reject requests older than this many seconds (prevents replay attacks)
MAX_REQUEST_AGE = 300  # 5 minutes


def xor_encrypt_decrypt(data_bytes: bytes, key: str) -> bytes:
    """
    XOR cipher — symmetric, same function for encrypt and decrypt.
    Key repeats cyclically over the data.
    """
    key_bytes = key.encode('utf-8')
    key_len = len(key_bytes)
    return bytes([b ^ key_bytes[i % key_len] for i, b in enumerate(data_bytes)])


def decrypt_payload(envelope: dict, api_key: str) -> dict:
    """
    Decrypt an encrypted POST body from Reforger.

    Expected envelope format:
        {"data": "<base64_xor_encrypted>", "ts": <unix_timestamp>}

    Returns:
        dict with decrypted JSON payload, or None on failure.

    Also validates timestamp to prevent replay attacks.
    """
    import json

    if not envelope or not isinstance(envelope, dict):
        return None

    encrypted_b64 = envelope.get('data', '')
    timestamp = envelope.get('ts', 0)

    if not encrypted_b64:
        return None

    # Validate timestamp
    if not validate_timestamp(timestamp):
        return None

    try:
        # Base64 decode
        encrypted_bytes = base64.b64decode(encrypted_b64)

        # XOR decrypt
        decrypted_bytes = xor_encrypt_decrypt(encrypted_bytes, api_key)

        # Parse JSON
        payload = json.loads(decrypted_bytes.decode('utf-8'))
        return payload

    except Exception as e:
        print(f"[HFCrypto] Decrypt failed: {e}")
        return None


def decrypt_auth_token(token_b64: str, api_key: str) -> tuple:
    """
    Decrypt a GET request auth token from Reforger.

    Token format (before encryption): "VERB:timestamp"
    Example: "PING:1708646400"

    Returns:
        (verb, timestamp) tuple, or (None, None) on failure.
    """
    if not token_b64:
        return None, None

    try:
        # Base64 decode
        encrypted_bytes = base64.b64decode(token_b64)

        # XOR decrypt
        decrypted_bytes = xor_encrypt_decrypt(encrypted_bytes, api_key)
        decrypted_str = decrypted_bytes.decode('utf-8')

        # Parse "VERB:timestamp"
        parts = decrypted_str.split(':', 1)
        if len(parts) != 2:
            return None, None

        verb = parts[0]
        timestamp = int(parts[1])

        # Validate timestamp
        if not validate_timestamp(timestamp):
            return None, None

        return verb, timestamp

    except Exception as e:
        print(f"[HFCrypto] Token decrypt failed: {e}")
        return None, None


def validate_timestamp(timestamp: int) -> bool:
    """
    Check that the timestamp is within MAX_REQUEST_AGE seconds of now.
    Prevents replay attacks.
    """
    if not timestamp:
        return False

    now = int(time.time())
    age = abs(now - timestamp)

    if age > MAX_REQUEST_AGE:
        print(f"[HFCrypto] Request rejected — too old ({age}s > {MAX_REQUEST_AGE}s max)")
        return False

    return True


def validate_get_request(request_args: dict, api_key: str, expected_verb: str = None) -> bool:
    """
    Validate a GET request's auth token.
    Use this in gateway endpoints to replace api_key URL param auth.

    Usage:
        if not validate_get_request(request.args, API_KEY, 'PING'):
            return jsonify({"status": "error", "message": "Unauthorized"}), 401
    """
    token = request_args.get('token', '')
    if not token:
        # Fallback: check for legacy api_key param (backward compatibility)
        legacy_key = request_args.get('api_key', '')
        if legacy_key == api_key:
            return True
        return False

    verb, timestamp = decrypt_auth_token(token, api_key)
    if verb is None:
        return False

    if expected_verb and verb != expected_verb:
        return False

    return True


def decrypt_post_body(request, api_key: str) -> dict:
    """
    Decrypt a POST request body. Handles both encrypted and legacy formats.

    Usage:
        data = decrypt_post_body(request, API_KEY)
        if data is None:
            return jsonify({"status": "error", "message": "Invalid request"}), 401
    """
    import json

    raw = request.get_json(force=True, silent=True)
    if not raw:
        return None

    # Check if this is an encrypted envelope
    if 'data' in raw and 'ts' in raw:
        # New encrypted format
        return decrypt_payload(raw, api_key)

    # Legacy: unencrypted JSON with api_key field
    if 'api_key' in raw or request.args.get('api_key') == api_key:
        return raw

    return None


# ============================================================
# SELF-TEST — run this file directly to verify
# python hf_crypto.py
# ============================================================
if __name__ == '__main__':
    print("=== HF Crypto Self-Test ===")

    test_key = "test-key-abc123"
    test_json = '{"money": 5000, "faction": "GREEN"}'

    # Test XOR roundtrip
    encrypted = xor_encrypt_decrypt(test_json.encode('utf-8'), test_key)
    decrypted = xor_encrypt_decrypt(encrypted, test_key)
    assert decrypted.decode('utf-8') == test_json, "XOR roundtrip failed!"
    print(f"XOR roundtrip: PASS")

    # Test Base64 + XOR roundtrip
    b64 = base64.b64encode(encrypted).decode('utf-8')
    back = xor_encrypt_decrypt(base64.b64decode(b64), test_key)
    assert back.decode('utf-8') == test_json, "Base64+XOR roundtrip failed!"
    print(f"Base64+XOR roundtrip: PASS")

    # Test full envelope
    import json
    ts = int(time.time())
    envelope = {"data": b64, "ts": ts}
    result = decrypt_payload(envelope, test_key)
    assert result == json.loads(test_json), "Envelope decrypt failed!"
    print(f"Envelope decrypt: PASS")

    # Test auth token
    token_plain = f"PING:{ts}"
    token_enc = base64.b64encode(
        xor_encrypt_decrypt(token_plain.encode('utf-8'), test_key)
    ).decode('utf-8')
    verb, token_ts = decrypt_auth_token(token_enc, test_key)
    assert verb == "PING" and token_ts == ts, "Auth token failed!"
    print(f"Auth token: PASS")

    # Test expired timestamp
    old_envelope = {"data": b64, "ts": ts - 600}
    result = decrypt_payload(old_envelope, test_key)
    assert result is None, "Should reject expired!"
    print(f"Expired rejection: PASS")

    print("\n=== ALL TESTS PASSED ===")
