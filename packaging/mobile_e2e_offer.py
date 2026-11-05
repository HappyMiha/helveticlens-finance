"""Create a fresh one-time pairing offer on the e2e server (offers expire after 5 minutes)."""
import os
import sys
from pathlib import Path

from financial_lens.api import mobile_v1
from financial_lens.service import FinancialLens
from financial_lens.tls import fingerprint

dsn, host_for_phone, data = sys.argv[1], sys.argv[2], Path(sys.argv[3])
lens = FinancialLens(dsn, data)
lens.open_organization("Personal")
print(mobile_v1.create_offer(lens, host_for_phone, fingerprint(data / "tls" / "tls-cert.pem"), ("upload", "read", "review"))["uri"])
