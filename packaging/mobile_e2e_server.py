"""Start a throwaway Financial Lens with TLS for the Android end-to-end test; prints the pairing URI."""
import os
import sys
import tempfile
from pathlib import Path

from financial_lens.api import mobile_v1
from financial_lens.service import FinancialLens
from financial_lens.tls import ensure_certificate

dsn, host_for_phone = sys.argv[1], sys.argv[2]
data = Path(tempfile.mkdtemp())
cert, key, fp = ensure_certificate(data / "tls")
lens = FinancialLens(dsn, data)
lens.migrate()
lens.open_organization("Personal")
offer = mobile_v1.create_offer(lens, host_for_phone, fp, ("upload", "read", "review"))
Path("/tmp/fl-pair-uri").write_text(offer["uri"])
Path("/tmp/fl-data").write_text(str(data))
print("PAIR_URI", offer["uri"], flush=True)
os.environ.update(FL_DSN=dsn, FL_DATA=str(data), FL_ORG="Personal")
import uvicorn  # noqa: E402

uvicorn.run("financial_lens.api.app:app", host="127.0.0.1", port=8766, ssl_certfile=str(cert), ssl_keyfile=str(key))
