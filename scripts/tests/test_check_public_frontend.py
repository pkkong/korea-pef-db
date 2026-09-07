import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import check_public_frontend as check


class PublicSourceTermTests(unittest.TestCase):
    def test_article_prose_does_not_trigger_operator_wording_gate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            data = [{"articles": [{"title": "Investor confidence improves", "summaryText": "Restoring confidence"}]}]
            (root / "index.html").write_text('<script>window.KPEF_DAILY_ARCHIVE = ' + json.dumps(data) + ';</script>')
            with patch.object(check, "PUBLIC_DIR", root):
                check.check_public_source_terms(["index.html"])

    def test_internal_payload_field_and_ui_label_are_still_rejected(self):
        for html in [
            '<script>window.KPEF_DAILY_ARCHIVE = [{"articles":[{"title":"Normal", "confidence":0.9}]}];</script>',
            '<div>confidence</div><script>window.KPEF_DAILY_ARCHIVE = [];</script>',
        ]:
            with TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "index.html").write_text(html)
                with patch.object(check, "PUBLIC_DIR", root), self.assertRaises(check.CheckFailure):
                    check.check_public_source_terms(["index.html"])

    def test_missing_icon_warns_but_redirect_links_still_fail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'assets').mkdir()
            (root / 'assets' / 'service.js').write_text('article.gpProfileLinks; appendLinkChip(item.name, item.url, "gp-chip"); appendLinkChip(item.name, item.url, "lp-chip");')
            article = {"title": "Sample", "url": "https://example.com/a", "tagVersion": "news-taxonomy-v1", "sourceIconUrl": ""}
            (root / 'archive.json').write_text(json.dumps([{"articles": [article]}]))
            with patch.object(check, "PUBLIC_DIR", root):
                self.assertIn('newsletter_icon_warnings=1', check.check_newsletter_frontend_contract())
                article['url'] = 'https://news.google.com/a'
                (root / 'archive.json').write_text(json.dumps([{"articles": [article]}]))
                with self.assertRaises(check.CheckFailure):
                    check.check_newsletter_frontend_contract()
