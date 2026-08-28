import unittest
from unittest.mock import Mock

import cv2

from module.shop.assets import MEDAL_SHOP_SCROLL_AREA_250814
from module.shop.shop_medal import MEDAL_SHOP_SCROLL_250814


class TestMedalShopScroll(unittest.TestCase):
    def test_track_is_not_treated_as_full_scroll_thumb(self):
        image = cv2.imread('assets/cn/shop/MEDAL_SHOP_SCROLL_AREA_250814.png')
        main = Mock()
        main.image_crop.side_effect = lambda area, copy=False: image[area[1]:area[3], area[0]:area[2]]

        mask = MEDAL_SHOP_SCROLL_250814.match_color(main)

        self.assertEqual(mask.size, MEDAL_SHOP_SCROLL_AREA_250814.area[3] - MEDAL_SHOP_SCROLL_AREA_250814.area[1])
        self.assertEqual(MEDAL_SHOP_SCROLL_250814.length, MEDAL_SHOP_SCROLL_250814.total)
        self.assertEqual(MEDAL_SHOP_SCROLL_250814.cal_position(main), 1.0)
        self.assertTrue(MEDAL_SHOP_SCROLL_250814.at_bottom(main))
        self.assertEqual(MEDAL_SHOP_SCROLL_250814.set_top(main), 0)


if __name__ == '__main__':
    unittest.main()
