import io
import errno
from unittest.mock import patch
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comfymobile_bridge.filesystem import FileAccessError, Root, copy_to_input, delete_file, list_files, relative_parts, resolve, write_upload


class FileSystemTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.folder = self.base / "input"
        self.folder.mkdir()
        self.root = Root("input", "Inputs", "input", self.folder, True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_rejects_posix_and_windows_escape_paths(self):
        for value in ["../secret", "a/../../secret", "C:\\secret", "C:secret", "\\\\host\\share", "/etc/passwd", "a\\..\\secret", "file:stream", "a\x00b"]:
            with self.subTest(value=value), self.assertRaises(FileAccessError):
                resolve(self.root, value, must_exist=False)

    def test_accepts_nested_unicode_and_windows_separators(self):
        self.assertEqual(relative_parts("Krea 2\\日本\\image.png"), ("Krea 2", "日本", "image.png"))

    def test_deletes_only_the_selected_file_and_preserves_parent_folder(self):
        folder = self.folder / "nested"
        folder.mkdir()
        (folder / "a + 日本.png").write_bytes(b"selected")
        (folder / "keep.png").write_bytes(b"keep")
        delete_file(self.root, "nested/a + 日本.png")
        self.assertEqual(list(folder.iterdir()), [folder / "keep.png"])
        with self.assertRaises(FileNotFoundError):
            delete_file(self.root, "nested/a + 日本.png")

    def test_deletion_rejects_roots_directories_traversal_and_symlinks(self):
        (self.folder / "nested").mkdir()
        outside = self.base / "outside.png"
        outside.write_bytes(b"outside")
        target = self.folder / "keep.png"
        target.write_bytes(b"inside")
        (self.folder / "inside-link.png").symlink_to(target)
        (self.folder / "outside-link.png").symlink_to(outside)
        for path in ["", ".", "nested", "../outside.png", "C:\\outside.png", "inside-link.png", "outside-link.png"]:
            with self.subTest(path=path), self.assertRaises(FileAccessError):
                delete_file(self.root, path)
        self.assertEqual(target.read_bytes(), b"inside")
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_model_deletion_uses_the_first_matching_location(self):
        root, extra = self.merged_root()
        primary = self.folder / "shared.bin"
        secondary = extra / "shared.bin"
        primary.write_bytes(b"primary")
        secondary.write_bytes(b"secondary")
        (extra / "unique.bin").write_bytes(b"unique")
        delete_file(root, "shared.bin")
        self.assertFalse(primary.exists())
        self.assertEqual(secondary.read_bytes(), b"secondary")
        self.assertEqual(resolve(root, "shared.bin"), secondary.resolve())
        delete_file(root, "unique.bin")
        self.assertFalse((extra / "unique.bin").exists())

    def test_external_symlinks_are_not_listed_or_read(self):
        outside = self.base / "secret.txt"
        outside.write_text("private")
        (self.folder / "link.txt").symlink_to(outside)
        with self.assertRaises(FileAccessError):
            resolve(self.root, "link.txt")
        self.assertEqual(list_files(self.root)["total"], 0)

    def test_symlink_parent_cannot_receive_upload(self):
        (self.folder / "external").symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(FileAccessError):
            write_upload(self.root, "file.txt", io.BytesIO(b"x"), "external")

    def test_pagination_and_directories_first(self):
        (self.folder / "z folder").mkdir()
        for name in ["B.png", "a.png", "c.png"]:
            (self.folder / name).write_bytes(b"image")
        first = list_files(self.root, limit=2)
        second = list_files(self.root, offset=first["nextOffset"], limit=2)
        self.assertEqual([v["name"] for v in first["entries"]], ["z folder", "a.png"])
        self.assertEqual([v["name"] for v in second["entries"]], ["B.png", "c.png"])
        self.assertIsNone(second["nextOffset"])

    def test_upload_never_overwrites_existing_file(self):
        first = write_upload(self.root, "image.png", io.BytesIO(b"first"), "nested")
        second = write_upload(self.root, "image.png", io.BytesIO(b"second"), "nested")
        self.assertEqual(first["path"], "nested/image.png")
        self.assertEqual(second["path"], "nested/image_1.png")
        self.assertEqual(resolve(self.root, first["path"]).read_bytes(), b"first")

    def test_rejects_large_upload_and_cleans_temporary_file(self):
        with self.assertRaises(FileAccessError):
            write_upload(self.root, "large.bin", io.BytesIO(b"12345"), max_bytes=3)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_readonly_model_root_rejects_upload(self):
        root = Root("model:loras:0", "LoRAs", "models", self.folder)
        with self.assertRaises(FileAccessError):
            write_upload(root, "model.safetensors", io.BytesIO(b"x"))

    def test_copy_output_to_input_preserves_source(self):
        output = self.base / "output"
        output.mkdir()
        source = output / "result.png"
        source.write_bytes(b"result")
        info = copy_to_input(Root("output", "Outputs", "output", output), "result.png", self.root)
        self.assertEqual(info["path"], "result.png")
        self.assertEqual(source.read_bytes(), resolve(self.root, info["path"]).read_bytes())

    def merged_root(self):
        extra = self.base / "extra_models"
        extra.mkdir()
        return Root("model:loras", "Loras", "models", self.folder, additional_paths=(extra,)), extra

    def test_model_locations_merge_before_search_and_pagination(self):
        root, extra = self.merged_root()
        for base, names in [(self.folder, ["shared.bin", "a.bin"]), (extra, ["shared.bin", "b.bin"])]:
            for name in names:
                (base / name).write_bytes(str(base).encode())
        first = list_files(root, limit=2)
        second = list_files(root, offset=first["nextOffset"], limit=2)
        self.assertEqual(first["total"], 3)
        self.assertEqual([v["name"] for v in first["entries"] + second["entries"]], ["a.bin", "b.bin", "shared.bin"])
        self.assertEqual(list_files(root, search="SHARED")["total"], 1)
        self.assertEqual(resolve(root, "shared.bin"), (self.folder / "shared.bin").resolve())
        self.assertEqual(resolve(root, "b.bin"), (extra / "b.bin").resolve())
        self.assertTrue(all(v["root"] == "model:loras" for v in first["entries"] + second["entries"]))

    def test_matching_model_subfolders_merge_but_file_collisions_use_first_location(self):
        root, extra = self.merged_root()
        for base in root.paths:
            (base / "nested").mkdir()
        (self.folder / "nested" / "first.bin").write_bytes(b"first")
        (extra / "nested" / "second.bin").write_bytes(b"second")
        (self.folder / "collision").write_bytes(b"file wins")
        (extra / "collision").mkdir()
        self.assertEqual([v["path"] for v in list_files(root, "nested")["entries"]], ["nested/first.bin", "nested/second.bin"])
        self.assertEqual(list_files(root)["total"], 2)
        self.assertFalse(next(v for v in list_files(root)["entries"] if v["name"] == "collision")["isDirectory"])
        with self.assertRaises(NotADirectoryError):
            list_files(root, "collision")

    def test_model_path_aliases_deduplicate_by_filesystem_identity(self):
        alias = self.base / "alias"
        alias.symlink_to(self.folder, target_is_directory=True)
        root = Root("model:loras", "Loras", "models", self.folder, additional_paths=(self.folder / ".", alias))
        self.assertEqual(root.paths, (self.folder.resolve(),))

    def test_merged_roots_reject_escape_paths_and_outward_symlinks(self):
        root, extra = self.merged_root()
        secret = self.base / "secret.bin"
        secret.write_bytes(b"private")
        (extra / "link.bin").symlink_to(secret)
        (self.folder / "blocked.bin").symlink_to(secret)
        (extra / "blocked.bin").write_bytes(b"later location")
        self.assertEqual(list_files(root)["total"], 0)
        for name in ["link.bin", "blocked.bin", "../secret.bin", "C:\\secret.bin"]:
            with self.subTest(name=name), self.assertRaises(FileAccessError):
                resolve(root, name)

    def test_merged_roots_cannot_be_writable(self):
        with self.assertRaises(ValueError):
            Root("input", "Inputs", "input", self.folder, True, (self.base,))




class PublicationTests(unittest.TestCase):
    def test_fallback_is_atomic_and_does_not_overwrite_existing_destination(self):
        from comfymobile_bridge.filesystem import publish_file
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / ".staged", Path(directory) / "model.bin"
            source.write_bytes(b"complete model")
            with patch("comfymobile_bridge.filesystem.os.link", side_effect=OSError(errno.EOPNOTSUPP, "No hard links")):
                target.write_bytes(b"existing")
                with self.assertRaises(FileExistsError):
                    publish_file(source, target)
                self.assertEqual(target.read_bytes(), b"existing")
                self.assertEqual(source.read_bytes(), b"complete model")
                target.unlink()
                publish_file(source, target)
            self.assertEqual(target.read_bytes(), b"complete model")
            self.assertFalse(source.exists())

    def test_probe_cleans_up_and_reports_unsupported_publication(self):
        from comfymobile_bridge.filesystem import check_publish_support, FileAccessError
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch("comfymobile_bridge.filesystem.os.link", side_effect=OSError(errno.EOPNOTSUPP, "No hard links")):
                check_publish_support(folder)
                self.assertEqual(list(folder.iterdir()), [])
                with patch("comfymobile_bridge.filesystem._rename_exclusive", side_effect=OSError(errno.ENOTSUP, "No exclusive rename")):
                    with self.assertRaisesRegex(FileAccessError, "Choose another location"):
                        check_publish_support(folder)
            self.assertEqual(list(folder.iterdir()), [])

    def test_real_io_failures_are_not_hidden_by_fallback(self):
        from comfymobile_bridge.filesystem import publish_file
        with patch("comfymobile_bridge.filesystem.os.link", side_effect=OSError(errno.ENOSPC, "Disk full")):
            with patch("comfymobile_bridge.filesystem._rename_exclusive") as fallback:
                with self.assertRaises(OSError):
                    publish_file(Path("source"), Path("target"))
                fallback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
