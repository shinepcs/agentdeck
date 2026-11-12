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
        self.assertEqual(Image.open(io.BytesIO(jpeg)).size, (96, 96))
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

    def test_side_strip_sends_three_native_tiles_to_strip_outputs(self):
        deck = self.make_deck()
        image = Image.new('RGB', (96, 288))
        for row, color in enumerate(('red', 'green', 'blue')):
            image.paste(color, (0, row * 96, 96, (row + 1) * 96))
        buffer = io.BytesIO()
        image.save(buffer, 'PNG')
        with patch.object(deck, '_write') as write:
            deck.set_side_strip(buffer.getvalue())
        packets = write.call_args.args[0]
        headers = [i for i, packet in enumerate(packets) if packet.startswith(b'CRT\0\0BAT')]
        self.assertEqual([packets[i][12] for i in headers], [0x10, 0x11, 0x12])
        for row, offset in enumerate(headers):
            size = int.from_bytes(packets[offset][8:12], 'big')
            self.assertLessEqual(size, 10240)
            jpeg = b''.join(packets[offset + 1:])[:size]
            tile = Image.open(io.BytesIO(jpeg))
            self.assertEqual(tile.size, (96, 96))
            self.assertGreater(tile.getpixel((40, 40))[row], 100)
        self.assertEqual(packets[-1][:8], b'CRT\0\0STP')
        self.assertTrue(all(len(packet) == 1024 for packet in packets))

    def test_side_strip_rotates_each_tile_like_the_existing_keys(self):
        deck = self.make_deck()
        image = Image.new('RGB', (96, 288), 'black')
        image.paste('red', (0, 0, 40, 40))
        buffer = io.BytesIO()
        image.save(buffer, 'PNG')
        with patch.object(deck, '_write') as write:
            deck.set_side_strip(buffer.getvalue())
        packets = write.call_args.args[0]
        size = int.from_bytes(packets[0][8:12], 'big')
        tile = Image.open(io.BytesIO(b''.join(packets[1:])[:size]))
        self.assertGreater(tile.getpixel((20, 76))[0], 200)
        self.assertLess(tile.getpixel((20, 20))[0], 20)

    def test_side_strip_only_sends_changed_tiles_and_keeps_key_cache(self):
        deck = self.make_deck()
        image = Image.new('RGB', (96, 288), 'black')
        with patch.object(deck, '_write') as write:
            deck.set_buttons({0: Button(image=self.png('blue'))})
            deck.set_side_strip(self.png('black', (96, 288)))
            deck.set_side_strip(self.png('black', (96, 288)))
            self.assertEqual(write.call_count, 2)
            image.paste('red', (0, 0, 96, 96))
            buffer = io.BytesIO()
            image.save(buffer, 'PNG')
            deck.set_side_strip(buffer.getvalue())
            packets = write.call_args.args[0]
            headers = [packet for packet in packets if packet.startswith(b'CRT\0\0BAT')]
            self.assertEqual([packet[12] for packet in headers], [0x10])
            deck.set_buttons({0: Button(image=self.png('blue'))})
            self.assertEqual(write.call_count, 3)

    def test_side_strip_rejects_wrong_size_without_writing(self):
        deck = self.make_deck()
        with patch.object(deck, '_write') as write:
            with self.assertRaises(ValueError):
                deck.set_side_strip(self.png('red', (100, 300)))
        write.assert_not_called()
        self.assertEqual(deck._images, {})

    def test_failed_side_strip_write_does_not_cache_tiles(self):
        deck = self.make_deck()
        with patch.object(deck, '_write', side_effect=OSError('unplugged')):
            with self.assertRaises(OSError):
                deck.set_side_strip(self.png('red', (96, 288)))
        self.assertEqual(deck._images, {})

    def test_clear_display_uses_standard_clear_all_then_refresh(self):
        from mirabox import command
        deck = self.make_deck()
        deck._images = {13: b'key', 16: b'strip'}
        with patch.object(deck, '_write') as write:
            deck.clear_display()
        write.assert_called_once_with([command(b'CLE\0\0\0\xff'), command(b'STP')])
        self.assertEqual(deck._images, {})

    def test_failed_clear_display_keeps_image_cache(self):
        deck = self.make_deck()
        deck._images = {13: b'key', 16: b'strip'}
        with patch.object(deck, '_write', side_effect=OSError('unplugged')):
            with self.assertRaises(OSError):
                deck.clear_display()
        self.assertEqual(deck._images, {13: b'key', 16: b'strip'})

    def test_start_clears_previous_display_before_starting_threads(self):
        from mirabox import command
        deck = self.make_deck()
        with patch.object(deck, '_write') as write, patch('d200.D200.start') as start:
            deck.start()
        self.assertEqual([call.args[0] for call in write.call_args_list],
                         [[command(b'DIS'), command(b'CONNECT')],
                          [command(b'CLE\0\0\0\xff'), command(b'STP')]])
        start.assert_called_once_with()

    @staticmethod
    def png(color, size=(196, 196)):
        buffer = io.BytesIO()
        Image.new('RGB', size, color).save(buffer, 'PNG')
        return buffer.getvalue()


if __name__ == '__main__':
    unittest.main()
