"""Tests for consent_capture/signing.py (name check, accepted signatures, JPEG)."""

import base64
import hashlib
import os

import pytest

from consent_capture.signing import (
    MAX_SIGNATURE_BYTES,
    SIGNED_WITH_LABELS,
    accepted_signed_with,
    clean_signature_jpeg,
    jpeg_info,
    name_key,
    same_name,
    statement_fingerprint,
)

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _asset(name):
    with open(os.path.join(ASSETS, name), "rb") as fh:
        return fh.read()


COLOR_JPEG = _asset("signature.jpg")        # 60 x 20, 3 components
GRAY_JPEG = _asset("signature-gray.jpg")    # 8 x 4, 1 component


class TestNameKey:
    def test_first_last_and_suffix(self):
        assert name_key("Robert Lopez Jr.") == ("robert", "lopez", "jr")

    def test_middle_names_and_initials_are_dropped(self):
        assert name_key("Maria L. Lopez") == ("maria", "lopez", "")
        assert name_key("Maria Luisa Ortega Lopez") == ("maria", "lopez", "")

    def test_case_periods_commas_and_spaces_are_ignored(self):
        assert name_key("  MARIA   lopez ") == ("maria", "lopez", "")
        assert name_key("Lopez, Maria") == ("lopez", "maria", "")

    def test_single_word_has_no_last_name(self):
        assert name_key("Maria") == ("maria", "", "")

    def test_suffix_alone_is_a_first_name(self):
        assert name_key("Jr") == ("jr", "", "")

    def test_empty(self):
        assert name_key("") == ("", "", "")
        assert name_key(None) == ("", "", "")


class TestSameName:
    @pytest.mark.parametrize(
        "a, b",
        [
            ("Maria L. Lopez", "Maria Lopez"),
            ("maria lopez", "Maria Lopez"),
            ("Maria  Lopez.", "Maria Lopez"),
            ("Robert Lopez Jr.", "robert lopez jr"),
            ("Robert Lopez III", "Robert A. Lopez III"),
        ],
    )
    def test_matches(self, a, b):
        assert same_name(a, b) is True

    @pytest.mark.parametrize(
        "a, b",
        [
            ("Robert Lopez Jr.", "Robert Lopez"),
            ("Robert Lopez Sr", "Robert Lopez Jr"),
            ("Maria Lopez-Garcia", "Maria Lopez"),
            ("julie", "Ana Lopez"),
            ("Ana Lopez", "Ana Lopes"),
            ("Ana", "Ana Lopez"),
        ],
    )
    def test_mismatches(self, a, b):
        assert same_name(a, b) is False


class TestAcceptedSignedWith:
    def test_defaults_finger_and_mouse(self):
        settings = {"accept_finger": True, "accept_mouse": True, "accept_typed": False}
        assert accepted_signed_with(settings) == ["finger", "mouse"]

    def test_all_three(self):
        settings = {"accept_finger": True, "accept_mouse": True, "accept_typed": True}
        assert accepted_signed_with(settings) == ["finger", "mouse", "typed"]

    def test_typed_only(self):
        settings = {"accept_finger": False, "accept_mouse": False, "accept_typed": True}
        assert accepted_signed_with(settings) == ["typed"]

    def test_labels_name_each_kind(self):
        assert SIGNED_WITH_LABELS["finger"] == "Signed on this device (finger or stylus)"
        assert SIGNED_WITH_LABELS["mouse"] == "Signed on this device (mouse or trackpad)"
        assert SIGNED_WITH_LABELS["typed"] == "Signed on this device (typed)"


class TestJpegInfo:
    def test_color_jpeg(self):
        assert jpeg_info(COLOR_JPEG) == (60, 20, 3)

    def test_grayscale_jpeg(self):
        assert jpeg_info(GRAY_JPEG) == (8, 4, 1)

    def test_not_a_jpeg(self):
        assert jpeg_info(b"\x89PNG\r\n\x1a\n....") is None
        assert jpeg_info(b"") is None
        assert jpeg_info(None) is None
        assert jpeg_info(b"nope") is None

    def test_truncated_before_frame(self):
        assert jpeg_info(COLOR_JPEG[:30]) is None

    def test_bad_marker_byte(self):
        assert jpeg_info(b"\xff\xd8\xff\xe0\x00\x04ab\x00\x00\x00\x00") is None

    def test_zero_length_segment(self):
        assert jpeg_info(b"\xff\xd8\xff\xe0\x00\x00\x00\x00") is None

    def test_fill_bytes_and_standalone_markers_are_skipped(self):
        # SOI, a fill byte, an RST marker (no length), then a baseline SOF0 frame.
        frame = b"\xff\xc0\x00\x0b\x08\x00\x02\x00\x03\x03\x01"
        data = b"\xff\xd8\xff\xff\xd0" + frame
        assert jpeg_info(data) == (3, 2, 3)

    def test_zero_size_frame_rejected(self):
        frame = b"\xff\xc0\x00\x0b\x08\x00\x00\x00\x03\x03\x01"
        assert jpeg_info(b"\xff\xd8" + frame) is None

    def test_cmyk_rejected(self):
        frame = b"\xff\xc0\x00\x0b\x08\x00\x02\x00\x03\x04\x01"
        assert jpeg_info(b"\xff\xd8" + frame) is None

    def test_frame_cut_short(self):
        assert jpeg_info(b"\xff\xd8\xff\xc0\x00\x0b\x08\x00") is None


class TestCleanSignatureJpeg:
    def test_data_url_accepted(self):
        raw = "data:image/jpeg;base64," + base64.b64encode(COLOR_JPEG).decode()
        data, width, height, components, error = clean_signature_jpeg(raw)
        assert (data, width, height, components, error) == (COLOR_JPEG, 60, 20, 3, None)

    def test_bare_base64_accepted(self):
        data, width, height, components, error = clean_signature_jpeg(base64.b64encode(GRAY_JPEG).decode())
        assert (width, height, components, error) == (8, 4, 1, None)

    def test_missing(self):
        assert clean_signature_jpeg("")[4] == "Add a signature before recording."
        assert clean_signature_jpeg(None)[4] == "Add a signature before recording."

    def test_not_base64(self):
        assert clean_signature_jpeg("@@@")[4] == "The signature couldn't be read. Please sign again."

    def test_not_a_jpeg(self):
        raw = base64.b64encode(b"\x89PNG\r\n\x1a\nxxxx").decode()
        assert clean_signature_jpeg(raw)[4] == "The signature couldn't be read. Please sign again."

    def test_too_large(self):
        raw = base64.b64encode(COLOR_JPEG + b"\x00" * MAX_SIGNATURE_BYTES).decode()
        assert clean_signature_jpeg(raw)[4] == "The signature image is too large. Please sign again."


class TestStatementFingerprint:
    def test_joins_paragraphs_and_hashes(self):
        text, digest = statement_fingerprint(["One.", "Two."])
        assert text == "One.\nTwo."
        assert digest == hashlib.sha256(b"One.\nTwo.").hexdigest()

    def test_any_edit_changes_the_hash(self):
        assert statement_fingerprint(["One."])[1] != statement_fingerprint(["One!"])[1]

    def test_empty(self):
        assert statement_fingerprint([]) == ("", hashlib.sha256(b"").hexdigest())
        assert statement_fingerprint(None)[0] == ""
