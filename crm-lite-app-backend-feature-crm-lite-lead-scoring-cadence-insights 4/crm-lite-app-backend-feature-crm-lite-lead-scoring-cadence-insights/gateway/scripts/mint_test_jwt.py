"""Mint an HS256 JWT for testing the gateway (Postman, curl, ...) — pure
stdlib, no dependencies. NOT for production use: anyone with the shared
secret can mint a token for any employee_id/roles they like, which is fine
for local testing but is exactly why JWT_SECRET must be kept real in any
shared environment.

Usage:
    python scripts/mint_test_jwt.py --employee-id <uuid> --roles ADMIN,SALES
    python scripts/mint_test_jwt.py --employee-id <uuid> --roles ADMIN --secret my-secret --ttl 3600
"""
import argparse
import base64
import hashlib
import hmac
import json
import time


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint(employee_id: str, roles: list[str], secret: str, ttl_seconds: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "employee_id": employee_id,
        "roles": roles,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(payload).encode())}"
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64url(signature)}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--employee-id", required=True, help="Backend employee UUID (or any string for a quick check)")
    parser.add_argument("--roles", default="ADMIN", help="Comma-separated role codes, e.g. ADMIN,SALES")
    parser.add_argument("--secret", default="crm-lite-gateway-dev-secret-key-please-change-2026",
                        help="Must match the gateway's JWT_SECRET")
    parser.add_argument("--ttl", type=int, default=3600, help="Token lifetime in seconds")
    args = parser.parse_args()

    token = mint(args.employee_id, args.roles.split(","), args.secret, args.ttl)
    print(token)
