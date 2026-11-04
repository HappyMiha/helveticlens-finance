import io
import os
import random
import uuid

import pytest

PG = os.environ.get("FL_TEST_DSN")


def render_invoice_photo(lines, qr_payload=None, tilt=1.2, noise=True) -> bytes:
    """Render a document and degrade it like a phone photo (tilt, blur, noise, JPEG)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
    bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 34)
    page = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(page)
    y = 90
    for i, text in enumerate(lines):
        draw.text((90, y), text, fill=(25, 25, 25), font=bold if i == 0 else font)
        y += 52
    if qr_payload:
        import qrcode

        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=2)
        qr.add_data(qr_payload)
        img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        page.paste(img, (760, 1150))
    photo = Image.new("RGB", (1400, 1900), (182, 170, 150))
    photo.paste(page.rotate(tilt, expand=False, fillcolor="white"), (80, 70))
    photo = photo.filter(ImageFilter.GaussianBlur(0.8))
    if noise:
        rnd = random.Random(7)
        px = photo.load()
        for _ in range(40000):
            x, yy = rnd.randrange(photo.width), rnd.randrange(photo.height)
            r, g, b = px[x, yy]
            d = rnd.randint(-40, 40)
            px[x, yy] = (max(0, min(255, r + d)),) * 3
    buf = io.BytesIO()
    photo.save(buf, "JPEG", quality=82)
    return buf.getvalue()


@pytest.fixture
def lens(tmp_path):
    if not PG:
        pytest.skip("FL_TEST_DSN not set (PostgreSQL required; SQLite is not allowed)")
    import psycopg

    from financial_lens.service import FinancialLens

    schema = "t_" + uuid.uuid4().hex[:10]
    admin = psycopg.connect(PG, autocommit=True)
    admin.execute(f"CREATE SCHEMA {schema}")
    dsn = f"{PG} options=-csearch_path={schema}"
    fl = FinancialLens(dsn, tmp_path, actor="user:test")
    fl.migrate()
    fl.open_organization("Test household", "personal")
    yield fl
    fl.close()
    admin.execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()
