"""
diag_tls.py - run inside the venv:  python diag_tls.py
Tries several TLS setups against the portal and reports which (if any) work.
Certificate checking is OFF for the raw-socket probes ONLY so we can see whether
the handshake itself is the problem. Nothing is sent except the handshake.
"""
import socket
import ssl

HOST, PORT = "www.ecustoms.gov.qa", 443

print("Python OpenSSL:", ssl.OPENSSL_VERSION)


def probe(label, ctx):
    try:
        with socket.create_connection((HOST, PORT), timeout=15) as s:
            with ctx.wrap_socket(s, server_hostname=HOST) as t:
                print(f"[OK]   {label}: {t.version()} / {t.cipher()[0]}")
    except Exception as e:
        print(f"[FAIL] {label}: {type(e).__name__}: {e}")


def base():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


# 1. Python defaults
probe("default", base())

# 2. Legacy-tolerant (what the adapter does)
c = base()
c.set_ciphers("DEFAULT:@SECLEVEL=0")
c.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
probe("legacy ciphers + legacy connect", c)

# 3. TLS 1.2 only
c = base()
c.minimum_version = c.maximum_version = ssl.TLSVersion.TLSv1_2
probe("TLS 1.2 only", c)

# 4. TLS 1.3 only
c = base()
c.minimum_version = c.maximum_version = ssl.TLSVersion.TLSv1_3
probe("TLS 1.3 only", c)

# 5. TLS 1.0 / 1.1 allowed
c = base()
c.set_ciphers("ALL:@SECLEVEL=0")
try:
    c.minimum_version = ssl.TLSVersion.TLSv1
except Exception:
    pass
probe("TLS 1.0+ with all ciphers", c)

# 6. The real app session (uses LegacyTLSAdapter)
print()
try:
    import hs_lookup
    r = hs_lookup.SESSION.get("https://www.ecustoms.gov.qa/qccswui/", timeout=15)
    print("[OK]   hs_lookup.SESSION ->", r.status_code)
except Exception as e:
    print("[FAIL] hs_lookup.SESSION ->", type(e).__name__, str(e)[:200])

# 7. Browser-fingerprint client, if installed (pip install curl_cffi)
try:
    from curl_cffi import requests as cr
    r = cr.get("https://www.ecustoms.gov.qa/qccswui/", impersonate="chrome", timeout=15)
    print("[OK]   curl_cffi (chrome fingerprint) ->", r.status_code)
except ImportError:
    print("[SKIP] curl_cffi not installed")
except Exception as e:
    print("[FAIL] curl_cffi ->", type(e).__name__, str(e)[:200])
