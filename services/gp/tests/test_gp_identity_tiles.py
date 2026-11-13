"""GP list/profile tiles: a wide wordmark is not squeezed into the 40px tile."""
from __future__ import annotations

import unittest

from services.gp.src import gp_service_pages as pages


class GpIdentityTiles(unittest.TestCase):
    def test_wide_wordmark_becomes_a_lettered_tile(self) -> None:
        # stic_logo.png is registered at 31x16px: a wordmark.
        markup = pages._avatar_markup("https://www.stic.co.kr", pages._avatar_label("스틱인베스트먼트"), "스틱인베스트먼트", "스틱인베스트먼트")
        self.assertNotIn("<img", markup)
        self.assertIn('data-label-length="2"', markup)
        self.assertIn("<span>스틱</span>", markup)

    def test_favicon_symbol_is_kept(self) -> None:
        markup = pages._avatar_markup("https://www.hcompany.com", "한앤", "한앤컴퍼니", "한앤컴퍼니")
        self.assertIn('class="gp-avatar has-logo"', markup)
        self.assertIn("favicon.png", markup)

    def test_labels_are_acronyms_where_the_name_spells_one(self) -> None:
        self.assertEqual(pages._avatar_label("엠비케이파트너스"), "MBK")
        self.assertEqual(pages._avatar_label(""), "GP")

    def test_shared_tile_css_is_in_the_page_styles(self) -> None:
        styles = pages._base_styles()
        self.assertIn('.gp-avatar:not(.has-logo)[data-tone="1"]', styles)
        self.assertIn(".gp-profile-preview .gp-profile-preview-logo{", styles)


if __name__ == "__main__":
    unittest.main()
