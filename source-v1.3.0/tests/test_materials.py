import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Resources/payload'))
import material_rules
import scan_materials
from publisher import Ledger

COPY = '发布标题\n测试标题\n\n详情内容\n正文 #Inside\n第二行\n\nYouTube Studio Tags\none, two words，三\nfour\n\nHashtags\n#Fallback\n#Second'


class ParsingTests(unittest.TestCase):
    def test_description_keeps_all_lines_without_appending_hashtags(self):
        p = scan_materials.parse_copy(COPY)
        self.assertEqual(p['title'], '测试标题')
        self.assertEqual(p['description'], '正文 #Inside\n第二行')
        self.assertEqual(p['description_source'], '详情内容')

    def test_empty_description_uses_all_hashtag_lines(self):
        p = scan_materials.parse_copy(COPY.replace('正文 #Inside\n第二行', ' \n\t'))
        self.assertEqual(p['description'], '#Fallback\n#Second')
        self.assertEqual(p['description_source'], 'Hashtags')

    def test_tags_are_separate_and_support_commas_and_lines(self):
        self.assertEqual(scan_materials.parse_copy(COPY)['tags'], ['one', 'two words', '三', 'four'])

    def test_empty_optional_tags(self):
        self.assertEqual(scan_materials.parse_copy(COPY.replace('one, two words，三\nfour', ''))['tags'], [])

    def test_both_description_sources_empty(self):
        p = scan_materials.parse_copy('发布标题\ntitle\n详情内容\nYouTube Studio Tags\na,b\nHashtags\n')
        self.assertEqual(p['description'], '')
        self.assertEqual(p['tags'], ['a', 'b'])

    def test_bom_crlf_and_heading_variants(self):
        p = scan_materials.parse_copy('\ufeff' + COPY.replace('\n', '\r\n').replace('YouTube Studio Tags', ' youtube studio｜tags： '))
        self.assertEqual(p['description'], '正文 #Inside\n第二行')
        self.assertEqual(p['tags'][0], 'one')

    def test_text_heading_also_ends_empty_description(self):
        p = scan_materials.parse_copy('发布标题\ntitle\n详情内容\nYouTube Studio text\n\nHashtags\n#only')
        self.assertEqual(p['description'], '#only')

    def test_hashtag_like_words_inside_body_are_preserved(self):
        p = scan_materials.parse_copy(COPY.replace('第二行', '这句提到 Hashtags 但不是标题'))
        self.assertIn('这句提到 Hashtags 但不是标题', p['description'])

    def test_duplicate_headings_fail_explicitly(self):
        with self.assertRaisesRegex(ValueError, '段落重复'):
            scan_materials.parse_copy(COPY + '\nHashtags\n#again')

    def test_missing_title_is_not_taken_from_other_sections(self):
        self.assertEqual(scan_materials.parse_copy('详情内容\nbody\nHashtags\n#x')['title'], '')


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'materials'
        self.folder.mkdir()
        (self.folder / 'video.mp4').write_bytes(b'video-one')
        (self.folder / 'video_发布文案.txt').write_text(COPY)
        (self.folder / 'video_封面.jpg').write_bytes(b'image')
        self.patchers = [patch.object(scan_materials, 'ROOT', self.root),
                         patch.object(material_rules, 'PATH', self.root / 'rules.json')]
        for p in self.patchers:
            p.start()
            self.addCleanup(p.stop)

    def test_default_rules_recognize_reference_naming(self):
        rows = scan_materials.discover(self.folder)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'ready')
        self.assertEqual(rows[0]['missing_reasons'], [])

    def test_hidden_sidecars_and_hidden_directories_are_excluded(self):
        (self.folder / '._video.mp4').write_bytes(b'sidecar')
        (self.folder / '._video_发布文案.txt').write_bytes(b'sidecar')
        (self.folder / '._video_封面.jpg').write_bytes(b'sidecar')
        hidden = self.folder / '.hidden'; hidden.mkdir()
        (hidden / 'another.mp4').write_bytes(b'hidden')
        self.assertEqual(len(scan_materials.discover(self.folder)), 1)
        self.assertEqual(scan_materials.discover(self.folder)[0]['status'], 'ready')

    def test_multiple_matches_list_candidates_instead_of_selecting_one(self):
        (self.folder / '另一个发布文案.txt').write_text(COPY)
        row = scan_materials.discover(self.folder)[0]
        self.assertIsNone(row['copy_file'])
        self.assertTrue(any('文案匹配多个' in x and '另一个发布文案.txt' in x for x in row['missing_reasons']))

    def test_missing_cover_has_specific_reason(self):
        (self.folder / 'video_封面.jpg').unlink()
        self.assertIn('封面未匹配', scan_materials.discover(self.folder)[0]['missing_reasons'][0])

    def test_custom_keywords_persist_and_match_case_insensitively(self):
        (self.folder / 'video_发布文案.txt').rename(self.folder / 'release_CAPTION.TXT')
        (self.folder / 'video_封面.jpg').rename(self.folder / 'ARTWORK.PNG')
        value = {'copy_keywords': ['caption'], 'cover_keywords': ['artwork'], 'fallback_description': ''}
        material_rules.save(value)
        self.assertEqual(material_rules.read(), value)
        self.assertEqual(scan_materials.discover(self.folder)[0]['status'], 'ready')

    def test_invalid_utf8_reports_reason(self):
        (self.folder / 'video_发布文案.txt').write_bytes(b'\xff\xff')
        self.assertIn('文案读取或解析失败', scan_materials.discover(self.folder)[0]['missing_reasons'][0])

    def test_ledger_uses_description_fallback_and_withdraws_stale_unassigned_assets(self):
        ledger = Ledger(self.root / 'ledger.sqlite3')
        self.addCleanup(ledger.db.close)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.scan(scan_materials.discover(self.folder))
            (self.folder / 'video.mp4').write_bytes(b'video-two')
            ledger.scan(scan_materials.discover(self.folder))
        self.assertEqual(ledger.db.execute('select count(*) from assets where complete=1').fetchone()[0], 1)
        self.assertEqual(ledger.db.execute('select count(*) from assets').fetchone()[0], 2)

    def test_history_is_retained_when_scanning_empty_folder(self):
        ledger = Ledger(self.root / 'ledger.sqlite3'); self.addCleanup(ledger.db.close)
        ledger.channel('UC-test', 'GM001', 'test', enabled=True, verified=True)
        with contextlib.redirect_stdout(io.StringIO()):
            ledger.scan(scan_materials.discover(self.folder)); ledger.plan('2026-10-15'); ledger.scan([])
        self.assertEqual(ledger.db.execute('select count(*) from tasks').fetchone()[0], 1)
        self.assertEqual(ledger.db.execute('select count(*) from assets').fetchone()[0], 1)


class SettingsTests(unittest.TestCase):
    def test_trims_and_deduplicates(self):
        result = material_rules.validate({'copy_keywords': [' caption ', 'CAPTION'], 'cover_keywords': ['封面']})
        self.assertEqual(result['copy_keywords'], ['caption'])

    def test_rejects_empty_or_invalid_configuration(self):
        for words in ([], [''], ['a/b'], ['x\ny'], '文案', [7], ['x' * 65]):
            with self.subTest(words=words), self.assertRaises(ValueError):
                material_rules.validate({'copy_keywords': words, 'cover_keywords': ['封面']})


if __name__ == '__main__':
    unittest.main()
