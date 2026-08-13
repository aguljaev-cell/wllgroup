from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import fitz
import requests

from config import APP_VERSION, AppConfig
from processors import _checkpoint_paths, _save_checkpoint, translate_pdf
from translator import (
    _post_json,
    _protect_values,
    _restore_values,
    _translate_chunk,
    qa_text,
    should_translate,
    split_long_text,
    translate_text,
)


class VersionAndConfigTests(unittest.TestCase):
    def test_lightweight_model_is_configured(self) -> None:
        config = AppConfig()
        self.assertEqual(APP_VERSION, "0.5.6")
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


class TranslationOutputSafetyTests(unittest.TestCase):
    def test_natural_all_caps_heading_is_translated_but_code_is_not(self) -> None:
        self.assertTrue(should_translate("CATALOGUE ONE (INJECTION)"))
        self.assertTrue(should_translate("DECLARATION"))
        self.assertFalse(should_translate("KS-PET"))
        self.assertFalse(should_translate("PLC"))

    def test_long_text_is_split_on_lines_and_round_trips_exactly(self) -> None:
        source = "".join(f"{index}. A table of contents row..................{index}\n" for index in range(80))
        chunks = list(split_long_text(source))
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 1100 for chunk in chunks))
        self.assertEqual("".join(chunks), source)

    def test_prompt_leak_is_retried_and_never_returned(self) -> None:
        leaked = (
            "Термины, обязательные для этого фрагмента:\n"
            "maintenance = техническое обслуживание\n"
            "ИСХОДНЫЙ ТЕКСТ:\nMaintenance schedule"
        )
        clean = "График технического обслуживания"
        responses = [
            {"choices": [{"message": {"content": leaked}}]},
            {"choices": [{"message": {"content": clean}}]},
        ]
        with patch("translator._post_json", side_effect=responses) as mocked_post:
            result = _translate_chunk("Maintenance schedule", AppConfig())
        self.assertEqual(result, clean)
        self.assertEqual(mocked_post.call_count, 2)

    def test_prompt_leak_is_reported_by_qa(self) -> None:
        result = qa_text("ИСХОДНЫЙ ТЕКСТ:\nMaintenance", "test")
        self.assertEqual(result.metrics["prompt_leak_markers"], 1)
        self.assertTrue(any("служебный текст" in warning for warning in result.warnings))

    def test_cjk_output_is_retried(self) -> None:
        responses = [
            {"choices": [{"message": {"content": "Система впрыска 机器"}}]},
            {"choices": [{"message": {"content": "Система впрыска"}}]},
        ]
        with patch("translator._post_json", side_effect=responses) as mocked_post:
            result = _translate_chunk("Injection system", AppConfig())
        self.assertEqual(result, "Система впрыска")
        self.assertEqual(mocked_post.call_count, 2)

    def test_untranslated_english_paragraph_is_retried(self) -> None:
        source = (
            "Melt plastic into melt status and inject the melted material into the mold "
            "while the machine prepares raw materials for the next injection cycle."
        )
        clean = (
            "Расплавьте пластик и впрысните расплавленный материал в пресс-форму, "
            "пока машина подготавливает сырьё для следующего цикла впрыска."
        )
        responses = [
            {"choices": [{"message": {"content": source}}]},
            {"choices": [{"message": {"content": clean}}]},
        ]
        with patch("translator._post_json", side_effect=responses) as mocked_post:
            result = _translate_chunk(source, AppConfig())
        self.assertEqual(result, clean)
        self.assertEqual(mocked_post.call_count, 2)

    def test_short_untranslated_english_line_is_rejected(self) -> None:
        source = "Oil temperature is too high"
        responses = [
            {"choices": [{"message": {"content": source}}]},
            {"choices": [{"message": {"content": "Температура масла слишком высокая"}}]},
        ]
        with patch("translator._post_json", side_effect=responses) as mocked_post:
            result = _translate_chunk(source, AppConfig())
        self.assertEqual(result, "Температура масла слишком высокая")
        self.assertEqual(mocked_post.call_count, 2)

    def test_failed_paragraph_is_split_and_translated_in_smaller_parts(self) -> None:
        source = (
            "Oil temperature is too high and the cooling system must be checked. "
            "The operator must stop the machine before inspecting the hydraulic circuit."
        )
        first = "Температура масла слишком высокая, необходимо проверить систему охлаждения. "
        second = (
            "Перед проверкой гидравлической системы оператор должен остановить машину."
        )
        responses = [
            {"choices": [{"message": {"content": source}}]},
            {"choices": [{"message": {"content": source}}]},
            {"choices": [{"message": {"content": first}}]},
            {"choices": [{"message": {"content": second}}]},
        ]
        with patch("translator._post_json", side_effect=responses) as mocked_post:
            result = translate_text(source, AppConfig())
        self.assertIn("Температура масла", result)
        self.assertIn("оператор должен остановить машину", result)
        self.assertEqual(mocked_post.call_count, 4)

    def test_recursive_fallback_preserves_manual_line_structure(self) -> None:
        source = "First line\nSecond line\nThird line\nFourth line"
        translations = {
            "First line": "Первая строка",
            "Second line": "Вторая строка",
            "Third line": "Третья строка",
            "Fourth line": "Четвёртая строка",
        }

        def fake_chunk(text: str, config: AppConfig) -> str:
            if "\n" in text:
                raise RuntimeError("block rejected")
            return translations[text]

        with patch("translator._translate_chunk", side_effect=fake_chunk):
            result = translate_text(source, AppConfig())
        self.assertEqual(
            result,
            "Первая строка\nВторая строка\nТретья строка\nЧетвёртая строка",
        )

    def test_known_bad_manual_phrases_are_rejected(self) -> None:
        result = qa_text(
            "Семиатомный режим: замесить пластики и впихнуть материал",
            "manual",
        )
        self.assertGreaterEqual(result.metrics["bad_terms"], 3)

    def test_collapsed_lines_are_retried(self) -> None:
        source = "First line\nSecond line\nThird line\nFourth line"
        collapsed = "Первая строка, вторая строка, третья строка и четвёртая строка"
        clean = "Первая строка\nВторая строка\nТретья строка\nЧетвёртая строка"
        responses = [
            {"choices": [{"message": {"content": collapsed}}]},
            {"choices": [{"message": {"content": clean}}]},
        ]
        with patch("translator._post_json", side_effect=responses) as mocked_post:
            result = _translate_chunk(source, AppConfig())
        self.assertEqual(result, clean)
        self.assertEqual(mocked_post.call_count, 2)


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

            checkpoint_doc = fitz.open(str(source))
            try:
                checkpoint_doc[0].insert_text((72, 100), "Checkpointed")
                reopened = _save_checkpoint(
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
                reopened.close()
            finally:
                checkpoint_doc.close()

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

    def test_failed_block_stops_pdf_instead_of_saving_english_source(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            destination = root / "result.pdf"
            self._make_pdf(source)

            with patch(
                "processors.translate_text",
                side_effect=RuntimeError("untranslated English"),
            ):
                with self.assertRaisesRegex(RuntimeError, "Перевод остановлен"):
                    translate_pdf(
                        source,
                        destination,
                        AppConfig(),
                        lambda value, message: None,
                        page_start=1,
                        page_end=1,
                    )

            self.assertFalse(destination.exists())
            self.assertTrue(destination.with_name("result_QA_REPORT.txt").exists())

    def test_text_that_does_not_fit_stops_page_before_final_save(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            destination = root / "result.pdf"
            self._make_pdf(source)

            with (
                patch("processors.translate_text", return_value="Переведённый текст"),
                patch("processors._insert_translated_text", return_value=(False, 4.5)),
            ):
                with self.assertRaisesRegex(RuntimeError, "не поместился"):
                    translate_pdf(
                        source,
                        destination,
                        AppConfig(),
                        lambda value, message: None,
                        page_start=1,
                        page_end=1,
                    )

            self.assertFalse(destination.exists())
            self.assertTrue(destination.with_name("result_QA_REPORT.txt").exists())


if __name__ == "__main__":
    unittest.main()
