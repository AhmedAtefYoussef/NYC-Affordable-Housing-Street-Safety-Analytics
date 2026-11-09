"""The title stands alone and leads back to the top; the picture is the browser and home-screen icon: buildings inside
the 250 m ring the study draws around each one, and a crash point on the ring."""
from __future__ import annotations

import struct
from pathlib import Path

from app.ui import page

ASSETS = Path(__file__).resolve().parents[1] / "app" / "assets"


def test_the_title_alone_leads_back_to_the_top():
    brand = page._masthead().children[0]
    assert brand.children == "Housing & Streets, NYC" and brand.href == "#top" and brand.className == "brand"


def test_the_icons_are_the_new_picture_at_every_size():
    svg = (ASSETS / "favicon.svg").read_text(encoding="utf-8")
    assert "<circle" in svg and 'clip-path="url(#inside)"' in svg and svg.count("<rect") >= 4 and "#ff8f78" in svg
    # Read from the file headers, so the test needs no imaging library: an ICO lists its images in 16-byte entries
    # after a 6-byte header; a PNG gives its width and height right after the IHDR tag.
    ico = (ASSETS / "favicon.ico").read_bytes()
    _, kind, count = struct.unpack("<HHH", ico[:6])
    sizes = {(ico[6 + 16 * k] or 256, ico[7 + 16 * k] or 256) for k in range(count)}
    assert kind == 1 and {(16, 16), (32, 32), (48, 48)} <= sizes
    png = (ASSETS / "apple-touch-icon.png").read_bytes()
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", png[16:24]) == (180, 180)


def test_the_page_head_links_both_icons():
    source = (ASSETS.parent / "app.py").read_text(encoding="utf-8")
    assert 'href="/assets/favicon.svg"' in source and 'href="/assets/apple-touch-icon.png"' in source
