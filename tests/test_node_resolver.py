from houdocs.node.resolver import _group_matches_folder


class TestGroupMatchesFolder:
    def test_exact_match_succeeds(self):
        assert _group_matches_folder(("Transform",), ("Transform",)) is True

    def test_suffix_match_succeeds(self):
        assert _group_matches_folder(("Transform",), ("Folder1", "Transform")) is True

    def test_longer_suffix_match_succeeds(self):
        assert _group_matches_folder(("A", "B"), ("X", "A", "B")) is True

    def test_trailing_label_only_fails(self):
        assert _group_matches_folder(("A", "B"), ("X", "Y", "B")) is False

    def test_different_trailing_labels_fail(self):
        assert _group_matches_folder(("Transform",), ("Folder1", "Rotation")) is False

    def test_empty_group_path_fails(self):
        assert _group_matches_folder((), ("Transform",)) is False

    def test_empty_folder_path_fails(self):
        assert _group_matches_folder(("Transform",), ()) is False

    def test_group_longer_than_folder_fails(self):
        assert _group_matches_folder(("A", "B", "C"), ("A", "B")) is False
