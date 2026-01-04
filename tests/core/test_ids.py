"""Tests for core.ids - terminal-agnostic ID utilities"""

import pytest

from termsupervisor.core.ids import normalize_id, id_match


class TestNormalizeId:
    """Test normalize_id function"""

    def test_pure_uuid_unchanged(self):
        """Pure UUID should be returned unchanged"""
        uuid = "3EB79F67-40C3-4583-A9E4-AD8224807F34"
        assert normalize_id(uuid) == uuid

    def test_prefixed_uuid_extracts_uuid(self):
        """Prefixed UUID should extract the UUID part"""
        prefixed = "w0t1p1:3EB79F67-40C3-4583-A9E4-AD8224807F34"
        expected = "3EB79F67-40C3-4583-A9E4-AD8224807F34"
        assert normalize_id(prefixed) == expected

    def test_multiple_colons_takes_last_part(self):
        """Multiple colons should take the last part"""
        multi = "prefix:more:3EB79F67-40C3-4583-A9E4-AD8224807F34"
        expected = "3EB79F67-40C3-4583-A9E4-AD8224807F34"
        assert normalize_id(multi) == expected

    def test_empty_string(self):
        """Empty string should return empty string"""
        assert normalize_id("") == ""

    def test_lowercase_uuid(self):
        """Lowercase UUID should be handled"""
        uuid = "3eb79f67-40c3-4583-a9e4-ad8224807f34"
        assert normalize_id(uuid) == uuid

    def test_prefixed_lowercase(self):
        """Prefixed lowercase UUID should extract correctly"""
        prefixed = "w0t1p1:3eb79f67-40c3-4583-a9e4-ad8224807f34"
        expected = "3eb79f67-40c3-4583-a9e4-ad8224807f34"
        assert normalize_id(prefixed) == expected


class TestIdMatch:
    """Test id_match function"""

    def test_same_pure_uuids_match(self):
        """Same pure UUIDs should match"""
        uuid = "3EB79F67-40C3-4583-A9E4-AD8224807F34"
        assert id_match(uuid, uuid) is True

    def test_prefixed_vs_pure_uuid_match(self):
        """Prefixed vs pure UUID should match"""
        prefixed = "w0t1p1:3EB79F67-40C3-4583-A9E4-AD8224807F34"
        pure = "3EB79F67-40C3-4583-A9E4-AD8224807F34"
        assert id_match(prefixed, pure) is True
        assert id_match(pure, prefixed) is True

    def test_different_prefixes_same_uuid_match(self):
        """Different prefixes but same UUID should match"""
        id1 = "w0t1p1:3EB79F67-40C3-4583-A9E4-AD8224807F34"
        id2 = "w1t2p3:3EB79F67-40C3-4583-A9E4-AD8224807F34"
        assert id_match(id1, id2) is True

    def test_different_uuids_no_match(self):
        """Different UUIDs should not match"""
        uuid1 = "3EB79F67-40C3-4583-A9E4-AD8224807F34"
        uuid2 = "4EC89F78-51D4-5694-B0F5-BE9335918G45"
        assert id_match(uuid1, uuid2) is False

    def test_empty_strings_match(self):
        """Empty strings should match each other"""
        assert id_match("", "") is True

    def test_empty_vs_non_empty_no_match(self):
        """Empty vs non-empty should not match"""
        assert id_match("", "3EB79F67-40C3-4583-A9E4-AD8224807F34") is False
