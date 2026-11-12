import io
import threading
import unittest
from unittest.mock import patch

from PIL import Image

from d200 import Button


class MiraboxTests(unittest.TestCase):
    def make_deck(self):
        from mirabox import Mirabox
        deck = Mirabox.__new__(Mirabox)
        deck._lock = threading.Lock()
        deck._images = {}
        deck.on_event = None
        return deck

    def test_image_is_jpeg_with_size_and_physical_key_in_header(self):
        deck = self.make_deck()
        with patch.object(deck, '_write') as write:
            deck.set_buttons({0: Button(image=self.png('red'))})
        packets = write.call_args.args[0]
        self.assertEqual(packets[0][:8], b'CRT\0\0BAT')
        size = int.from_bytes(packets[0][8:12], 'big')
        self.assertEqual(packets[0][12], 13)
        jpeg = b''.join(packets[1:-1])[:size]
        self.assertEqual(Image.open(io.BytesIO(jpeg)).size, (100, 100))
        self.assertLessEqual(size, 10240)
        self.assertEqual(packets[-1][:8], b'CRT\0\0STP')
        self.assertTrue(all(len(p) == 1024 for p in packets))

    def test_unchanged_keys_are_not_sent_again(self):
        deck = self.make_deck()
        buttons = {0: Button(image=self.png('blue'))}
        with patch.object(deck, '_write') as write:
            deck.set_buttons(buttons)
            deck.set_buttons(buttons)
        self.assertEqual(write.call_count, 1)

    def test_wide_panel_is_split_over_last_two_keys(self):
        deck = self.make_deck()
        with patch.object(deck, '_write') as write:
            deck.set_buttons({}, small_png=self.png('green', (458, 196)))
        packets = write.call_args.args[0]
        headers = [p for p in packets if p.startswith(b'CRT\0\0BAT')]
        self.assertEqual([p[12] for p in headers], [6, 3])

    def test_press_release_map_to_dashboard_indices(self):
        deck = self.make_deck()
        events = []
        deck.on_event = events.append
        for key, state in ((13, 1), (13, 0), (9, 1), (255, 1)):
            deck._parse(b'ACK\0\0BT\0\0' + bytes((key, state)))
        self.assertEqual([(e.index, e.action) for e in events],
                         [(0, 'press'), (0, 'release'), (12, 'press')])
        deck._parse(b'bad')

    def test_failed_write_does_not_cache_image(self):
        deck = self.make_deck()
        with patch.object(deck, '_write', side_effect=OSError('unplugged')):
            with self.assertRaises(OSError):
                deck.set_buttons({0: Button(image=self.png('red'))})
        self.assertEqual(deck._images, {})

    @staticmethod
    def png(color, size=(196, 196)):
        buffer = io.BytesIO()
        Image.new('RGB', size, color).save(buffer, 'PNG')
        return buffer.getvalue()


if __name__ == '__main__':
    unittest.main()
