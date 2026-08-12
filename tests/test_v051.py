from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import fitz
import requests

from config import APP_VERSION, AppConfig
from processors import _checkpoint_paths, _save_checkpoint, translate_pdf
from translator import _post_json, _protect_values, _restore_values


class VersionAndConfigTests(unittest.TestCase):
    def test_lightweight_model_is_configured(self) -> None:
        config = AppConfig()
        self.assertEqual(APP_VERSION, "0.5.2")
        self.assertIn("1.5B", config.model_filename)
        self.assertLessEqual(config.request_timeout, 300)
        self.assertEqual(config.gpu_layer_candidates, (20, 12, 4))


class TimeoutTests(unittest.TestCase):
    def test_timeout_is_not_retried(self) -> None:
        mocked_post = Mock(side_effect=requests.Timeout("slow model"))
        with patch("translator.requests.post", mocked_post):
            with self.assertRaisesRegex(RuntimeError, "зациклилась"):
                _post_json("http://127.0.0.1", {}, timeout=1)
        self.assertEqual(mocked_post.call_count, 1)


class ProtectedValueTests(unittest.TestCase):
    def test_ordinary_en_and_un_words_are_not_protected(self) -> None:
        source = "Enterprise environment enough unit................................6"
        protected = _protect_values(source)
        self.assertEqual(protected.text, source)
        self.assertEqual(protected.values, {})

    def test_real_technical_values_are_protected_without_nested_markers(self) -> None:
        source = "ISO 9001, UN 3082, KS-PET and 25 MPa"
        protected = _protect_values(source)
        self.assertEqual(len(protected.values), 4)
        self.assertFalse(any("WLL_" in value for value in protected.values.values()))
        self.assertEqual(_restore_values(protected.text, protected.values), source)


class PdfCheckpointTests(unittest.TestCase):
    @staticmethod
    def _make_pdf(path: Path) -> None:
        doc = fitz.open()
        for text in ("First page", "Second page", "Third page"):
            page = doc.new_page()
            page.insert_text((72, 72), text)
        doc.save(str(path))
        doc.close()

    def test_page_range_and_checkpoint_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            destination = root / "result.pdf"
            self._make_pdf(source)

            translated_inputs: list[str] = []

            def fake_translate(text: str, config: AppConfig) -> str:
                translated_inputs.append(text)
                return "Translated"

            with patch("processors.translate_text", side_effect=fake_translate):
                report = translate_pdf(
                    source,
                    destination,
                    AppConfig(),
                    lambda value, message: None,
                    page_start=1,
                    page_end=2,
                )

            self.assertTrue(destination.exists())
            self.assertTrue(report.exists())
            partial, state = _checkpoint_paths(destination)
            self.assertFalse(partial.exists())
            self.assertFalse(state.exists())

            # The actual translated glyph extraction depends on fonts available
            # on the runner.  Verify range selection through translation calls
            # and confirm that the untouched page remains intact instead.
            self.assertEqual(len(translated_inputs), 2)
            self.assertTrue(any("First page" in item for item in translated_inputs))
            self.assertTrue(any("Second page" in item for item in translated_inputs))

            with fitz.open(str(destination)) as result:
                self.assertIn("Third page", result[2].get_text())

    def test_translation_resumes_after_saved_page(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            destination = root / "result.pdf"
            self._make_pdf(source)
            partial, state = _checkpoint_paths(destination)

            with fitz.open(str(source)) as checkpoint_doc:
                checkpoint_doc[0].insert_text((72, 100), "Checkpointed")
                _save_checkpoint(
                    checkpoint_doc,
                    source,
                    partial,
                    state,
                    start_index=0,
                    end_index=2,
                    next_page_index=1,
                    warnings=[],
                    processed_blocks=1,
                )

            translated_inputs: list[str] = []

            def fake_translate(text: str, config: AppConfig) -> str:
                translated_inputs.append(text)
                return "Translated"

            with patch("processors.translate_text", side_effect=fake_translate):
                translate_pdf(
                    source,
                    destination,
                    AppConfig(),
                    lambda value, message: None,
                    page_start=1,
                    page_end=3,
                )

            self.assertFalse(any("First page" in item for item in translated_inputs))
            with fitz.open(str(destination)) as result:
                self.assertIn("Checkpointed", result[0].get_text())


if __name__ == "__main__":
    unittest.main()
