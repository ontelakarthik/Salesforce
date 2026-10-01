"""One-off diagnostic: trigger a real POST /email-intake/poll (exactly what
Cloud Scheduler does every 5 minutes) and print the exact structured result,
plus a SAFE read-only peek at what's still sitting UNSEEN afterward (opens
the mailbox read-only and uses BODY.PEEK so nothing gets marked \\Seen by
this script itself)."""
import imaplib

import httpx

from src.config.config_reader import get_settings

settings = get_settings()

resp = httpx.post(
    "https://crm-lite-backend-twts2uvgoa-el.a.run.app/api/v1/email-intake/poll",
    headers={"X-Email-Intake-Secret": settings.EMAIL_INTAKE_SECRET},
    timeout=60,
)
print("poll status:", resp.status_code)
print("poll body:", resp.text)

print("\n--- read-only peek at what's still UNSEEN (does not mark anything as read) ---")
with imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT, timeout=20) as imap:
    imap.login(settings.IMAP_USERNAME, settings.IMAP_PASSWORD)
    imap.select("INBOX", readonly=True)
    status, data = imap.search(None, "UNSEEN")
    nums = data[0].split() if status == "OK" else []
    print(f"{len(nums)} still unseen")
    for num in nums:
        fs, hdr = imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if fs == "OK" and hdr and hdr[0]:
            print("  ", hdr[0][1].decode("utf-8", errors="replace").replace("\r\n", " | "))
