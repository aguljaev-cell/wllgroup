from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import fitz
import requests

from config import APP_VERSION, AppConfig
from processors import (
    TranslationQualityError,
    _checkpoint_paths,
    _extract_pdf_repair_blocks,
    _extract_schematic_repair_blocks,
    _translate_pdf_text,
    _save_checkpoint,
    translate_pdf,
)
from translator import (
    _post_json,
    _protect_values,
    _reflow_to_source_lines,
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
        self.assertEqual(APP_VERSION, "0.6.3")
        self.assertIn("translategemma-4b-it", config.model_filename)
        self.assertEqual(config.model_size, 2_489_909_760)
        self.assertLessEqual(config.request_timeout, 300)
        self.assertEqual(config.gpu_layer_candidates, (28, 20, 12, 4))


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

    def test_standalone_pdf_bullet_is_protected_and_normalized(self) -> None:
        source = "  ●  \n25 MPa"
        protected = _protect_values(source)
        self.assertEqual(len(protected.values), 2)
        self.assertEqual(_restore_values(protected.text, protected.values), "  •  \n25 MPa")


class TranslationOutputSafetyTests(unittest.TestCase):
    def test_line_reflow_restores_source_geometry(self) -> None:
        source = "First long source line\nSecond source line\nThird line"
        result = _reflow_to_source_lines(
            source,
            "Первая длинная строка, вторая строка и третья строка",
        )
        self.assertEqual(len(result.splitlines()), 3)

    def test_rejected_short_fragment_uses_packaged_fallback(self) -> None:
        with (
            patch("translator._translate_chunk", side_effect=RuntimeError("rejected")),
            patch("translator._translate_with_opus", return_value="Температура масла") as fallback,
        ):
            result = translate_text("Oil temperature", AppConfig())
        self.assertEqual(result, "Температура масла")
        fallback.assert_called_once_with("Oil temperature")

    def test_natural_all_caps_heading_is_translated_but_code_is_not(self) -> None:
        self.assertTrue(should_translate("CATALOGUE ONE (INJECTION)"))
        self.assertTrue(should_translate("DECLARATION"))
        self.assertFalse(should_translate("KS-PET"))
        self.assertFalse(should_translate("PLC"))
        self.assertFalse(should_translate("Температура масла слишком высокая"))
        self.assertTrue(should_translate("Mold height limit bwd"))
        self.assertTrue(should_translate("模具高度检测"))

    def test_repair_extractor_ignores_russian_and_equipment_codes(self) -> None:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Переведённый русский текст")
        page.insert_text((72, 100), "Mold height limit bwd")
        page.insert_text((72, 128), "DI8 XD4 PLC")
        try:
            blocks = _extract_pdf_repair_blocks(page)
        finally:
            doc.close()
        self.assertEqual([block.text for block in blocks], ["Mold height limit bwd"])

    def test_repair_extractor_keeps_paragraph_lines_together(self) -> None:
        doc = fitz.open()
        page = doc.new_page()
        page.insert_textbox(
            fitz.Rect(72, 72, 400, 140),
            "The operator must stop the machine.\nThen inspect the hydraulic circuit.",
            fontsize=10,
        )
        try:
            blocks = _extract_pdf_repair_blocks(page)
        finally:
            doc.close()
        self.assertEqual(len(blocks), 1)
        self.assertIn("\n", blocks[0].text)
        self.assertEqual(blocks[0].kind, "paragraph")

    def test_schematic_bilingual_pair_becomes_one_russian_target(self) -> None:
        data = {
            "blocks": [{
                "type": 0,
                "lines": [
                    {
                        "bbox": (10, 10, 70, 20),
                        "dir": (1, 0),
                        "spans": [{"text": "调模退极限", "size": 8, "color": 0}],
                    },
                    {
                        "bbox": (10, 20, 100, 30),
                        "dir": (1, 0),
                        "spans": [{"text": "Mold height limit bwd", "size": 8, "color": 0}],
                    },
                ],
            }],
        }
        blocks = _extract_schematic_repair_blocks(data)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].text, "Mold height limit bwd")
        self.assertEqual(tuple(blocks[0].rect), (10.0, 10.0, 100.0, 30.0))
        self.assertTrue(blocks[0].prefer_fast)

    def test_schematic_mixed_line_uses_only_english_duplicate(self) -> None:
        data = {
            "blocks": [{
                "type": 0,
                "lines": [{
                    "bbox": (10, 10, 180, 20),
                    "dir": (1, 0),
                    "spans": [{
                        "text": "机械手联锁 Safety Inter Locking",
                        "size": 8,
                        "color": 0,
                    }],
                }],
            }],
        }
        blocks = _extract_schematic_repair_blocks(data)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].text, "Safety Inter Locking")
        self.assertTrue(blocks[0].prefer_fast)

    def test_normal_text_uses_quality_model_before_opus(self) -> None:
        with (
            patch("processors._translate_resilient", return_value="Проверить систему") as quality,
            patch("processors._translate_with_opus") as fast,
        ):
            result = _translate_pdf_text("Check the hydraulic system", AppConfig())
        self.assertEqual(result, "Проверить систему")
        quality.assert_called_once()
        fast.assert_not_called()

    def test_schematic_label_can_use_fast_translator(self) -> None:
        with (
            patch("processors._translate_with_opus", return_value="Ограничение высоты") as fast,
            patch("processors._translate_resilient") as quality,
        ):
            result = _translate_pdf_text(
                "Mold height limit bwd",
                AppConfig(),
                prefer_fast=True,
            )
        self.assertEqual(result, "Ограничение высоты")
        fast.assert_called_once()
        quality.assert_not_called()

    def test_chinese_failure_never_falls_back_to_english_opus(self) -> None:
        with (
            patch("processors._translate_resilient", side_effect=RuntimeError("rejected")),
            patch("processors._translate_with_opus") as fast,
        ):
            with self.assertRaisesRegex(RuntimeError, "rejected"):
                _translate_pdf_text("调模退极限", AppConfig())
        fast.assert_not_called()

    def test_known_catalogue_heading_does_not_call_model(self) -> None:
        with patch("translator._post_json") as mocked_post:
            result = translate_text("CATALOGUE ONE(INJECTION)", AppConfig())
        self.assertEqual(result, "СОДЕРЖАНИЕ. ЧАСТЬ 1 (ВПРЫСК)")
        mocked_post.assert_not_called()

    def test_catalogue_preserves_numbers_leaders_pages_and_line_count(self) -> None:
        source = (
            "1.3 Injection part................................................ 5\n"
            "1.4 Clamping unit.................................................6\n"
            "2.2 Clean........................................................ 11\n"
            "Boot program...................................................... 26"
        )
        with patch("translator._post_json") as mocked_post:
            result = translate_text(source, AppConfig())
        self.assertEqual(
            result,
            "1.3 Узел впрыска................................................ 5\n"
            "1.4 Узел смыкания.................................................6\n"
            "2.2 Очистка........................................................ 11\n"
            "Порядок запуска...................................................... 26",
        )
        self.assertEqual(len(result.splitlines()), len(source.splitlines()))
        mocked_post.assert_not_called()

    def test_unknown_catalogue_title_sends_only_title_to_model(self) -> None:
        source = (
            "1. Unknown first heading............................ 4\n"
            "2. Unknown second heading........................... 5\n"
            "3. Unknown third heading............................ 6\n"
            "4. Unknown fourth heading........................... 7"
        )
        responses = [
            {"choices": [{"message": {"content": "Неизвестный первый заголовок"}}]},
            {"choices": [{"message": {"content": "Неизвестный второй заголовок"}}]},
            {"choices": [{"message": {"content": "Неизвестный третий заголовок"}}]},
            {"choices": [{"message": {"content": "Неизвестный четвёртый заголовок"}}]},
        ]
        with (
            patch("translator._translate_with_opus", side_effect=RuntimeError("force model path")),
            patch("translator._post_json", side_effect=responses) as mocked_post,
        ):
            result = translate_text(source, AppConfig())
        prompts = [
            call.args[1]["messages"][-1]["content"]
            for call in mocked_post.call_args_list
        ]
        self.assertEqual(mocked_post.call_count, 4)
        self.assertTrue(all("...." not in prompt for prompt in prompts))
        self.assertTrue(result.startswith("1. Неизвестный первый заголовок"))
        self.assertTrue(result.endswith("........................... 7"))

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
        with (
            patch("translator._translate_with_opus", side_effect=RuntimeError("force model path")),
            patch("translator._post_json", side_effect=responses) as mocked_post,
        ):
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

        with (
            patch("translator._translate_with_opus", side_effect=RuntimeError("force model path")),
            patch("translator._translate_chunk", side_effect=fake_chunk),
        ):
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

            def fake_translate(text: str, config: AppConfig, **kwargs: object) -> str:
                translated_inputs.append(text)
                return "Translated"

            with patch("processors._translate_pdf_text", side_effect=fake_translate):
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

            def fake_translate(text: str, config: AppConfig, **kwargs: object) -> str:
                translated_inputs.append(text)
                return "Translated"

            with patch("processors._translate_pdf_text", side_effect=fake_translate):
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

    def test_failed_block_is_reported_and_following_pages_continue(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            destination = root / "result.pdf"
            self._make_pdf(source)

            calls = 0

            def translate_or_fail(
                text: str,
                config: AppConfig,
                **kwargs: object,
            ) -> str:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("untranslated English")
                return "Переведено"

            with (
                patch("processors._translate_pdf_text", side_effect=translate_or_fail),
                patch("processors._translation_fits", return_value=True),
                patch("processors._insert_translated_text", return_value=(True, 8.0)),
            ):
                report = translate_pdf(
                    source,
                    destination,
                    AppConfig(),
                    lambda value, message: None,
                    page_start=1,
                    page_end=3,
                )

            self.assertEqual(calls, 3)
            self.assertTrue(destination.exists())
            self.assertTrue(report.exists())
            self.assertIn(
                "обработка документа продолжена",
                report.read_text(encoding="utf-8"),
            )
            with fitz.open(str(destination)) as result:
                self.assertIn("First page", result[0].get_text())

    def test_text_that_does_not_fit_keeps_source_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            destination = root / "result.pdf"
            self._make_pdf(source)

            with (
                patch("processors._translate_pdf_text", return_value="Переведённый текст"),
                patch("processors._translation_fits", return_value=False),
            ):
                report = translate_pdf(
                    source,
                    destination,
                    AppConfig(),
                    lambda value, message: None,
                    page_start=1,
                    page_end=3,
                )

            self.assertTrue(destination.exists())
            self.assertIn(
                "исходный блок сохранён",
                report.read_text(encoding="utf-8"),
            )
            with fitz.open(str(destination)) as result:
                self.assertIn("First page", result[0].get_text())

    def test_unexpected_insert_failure_restores_original_page(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            destination = root / "result.pdf"
            self._make_pdf(source)

            with (
                patch("processors._translate_pdf_text", return_value="Переведённый текст"),
                patch("processors._translation_fits", return_value=True),
                patch("processors._insert_translated_text", return_value=(False, 3.5)),
            ):
                report = translate_pdf(
                    source,
                    destination,
                    AppConfig(),
                    lambda value, message: None,
                    page_start=1,
                    page_end=3,
                )

            self.assertTrue(destination.exists())
            self.assertIn(
                "исходная страница восстановлена",
                report.read_text(encoding="utf-8"),
            )
            with fitz.open(str(destination)) as result:
                self.assertIn("First page", result[0].get_text())
                self.assertIn("Third page", result[2].get_text())

    def test_ten_page_job_does_not_abort_on_page_seven(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            destination = root / "result.pdf"
            doc = fitz.open()
            for index in range(1, 11):
                page = doc.new_page()
                page.insert_text((72, 72), f"Source page {index}")
            doc.save(str(source))
            doc.close()

            translated_pages: list[int] = []

            def translate_with_page_seven_failure(
                text: str,
                config: AppConfig,
                **kwargs: object,
            ) -> str:
                page_number = int(text.rsplit(" ", 1)[-1])
                translated_pages.append(page_number)
                if page_number == 7:
                    raise RuntimeError("simulated rejected fragment")
                return f"Переведена страница {page_number}"

            with (
                patch(
                    "processors._translate_pdf_text",
                    side_effect=translate_with_page_seven_failure,
                ),
                patch("processors._translation_fits", return_value=True),
                patch("processors._insert_translated_text", return_value=(True, 8.0)),
            ):
                report = translate_pdf(
                    source,
                    destination,
                    AppConfig(),
                    lambda value, message: None,
                    page_start=1,
                    page_end=10,
                )

            self.assertEqual(translated_pages, list(range(1, 11)))
            self.assertTrue(destination.exists())
            self.assertIn("страница 7", report.read_text(encoding="utf-8"))

    def test_repair_mode_translates_only_residual_source_lines(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "translated.pdf"
            destination = root / "repaired.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "Русский текст уже готов")
            page.insert_text((72, 100), "Mold height limit bwd")
            page.insert_text((72, 128), "DI8 XD4 PLC")
            doc.save(str(source))
            doc.close()

            inputs: list[str] = []

            def fake_translate(text: str, config: AppConfig, **kwargs: object) -> str:
                inputs.append(text)
                return "Ограничение высоты пресс-формы назад"

            with (
                patch("processors._translate_pdf_text", side_effect=fake_translate),
                patch("processors._translation_fits", return_value=True),
                patch("processors._insert_translated_text", return_value=(True, 7.0)),
            ):
                translate_pdf(
                    source,
                    destination,
                    AppConfig(),
                    lambda value, message: None,
                    repair_mode=True,
                )

            self.assertEqual(inputs, ["Mold height limit bwd"])
            self.assertTrue(destination.exists())


class WorkerReportSignalTests(unittest.TestCase):
    def test_quality_failure_emits_report_path_before_failure(self) -> None:
        try:
            from worker import TranslationWorker
        except ModuleNotFoundError as exc:
            if exc.name == "PySide6":
                self.skipTest("PySide6 is not installed in the local test runtime")
            raise

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.pdf"
            destination = root / "result.pdf"
            report = root / "result_QA_REPORT.txt"
            source.write_bytes(b"test")
            report.write_text("QA", encoding="utf-8")

            quality_error = TranslationQualityError("quality failed", report)
            worker = TranslationWorker(source, destination, AppConfig())
            worker.server.start = Mock()
            worker.server.stop = Mock()
            reports: list[str] = []
            failures: list[str] = []
            worker.report_ready.connect(reports.append)
            worker.failed.connect(failures.append)

            with patch("worker.translate_pdf", side_effect=quality_error):
                worker.run()

            self.assertEqual(reports, [str(report)])
            self.assertEqual(len(failures), 1)


if __name__ == "__main__":
    unittest.main()
