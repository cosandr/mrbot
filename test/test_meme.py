import json
import os
import time
from typing import Tuple

from PIL import Image, ImageDraw

from cogs.make_meme.errors import MemeTemplateError
from cogs.make_meme.templates import MemeTemplate, AllMemeTemplates


# noinspection PyProtectedMember
class TestMeme:

    def test_make_all(self):
        start_all = time.perf_counter()
        all_templ = AllMemeTemplates()
        templ_dict = {
            'Change My Mind': ['Testing entry 1, longer edition my dude'],
            'Distracted Boyfriend': ['Testing entry 1', 'Testing entry 2'],
            'Is This A Pigeon': ['Testing entry 1', 'Testing entry 2'],
            'Jerry': ['Testing entry 1'],
            'Tom Newspaper': ['Testing entry 1'],
            'Two Buttons': ['Testing entry 1', 'Testing entry 2'],
            'Woman Yelling At Cat': ['Testing entry 1', 'Testing entry 2'],
        }
        for name, entries in templ_dict.items():
            start = time.perf_counter()
            img = all_templ[name].make(entries)
            print(f"Made {name} in {((time.perf_counter() - start) * 1000):.3f}ms.")
            img.save(f'text/{name}.png')
        print(f"Made all templates in {((time.perf_counter() - start_all) * 1000):,.3f}ms.")

    def test_template(self):
        start = time.perf_counter()
        templ = self.load_template('Change-My-Mind.json')
        img = templ.make(["this is a reaaaallly long thing my dude yeeeaaah"])
        # img = templ.make(["wtf make me", "don't make me"])
        print(f"Made template in {((time.perf_counter() - start) * 1000):.3f}ms.")
        # img.save('test-meme.jpg')
        img.show()

    def run_template_test(self):
        text = "This is a test"
        img = Image.open(f'{self.meme_dir}/Change-My-Mind.jpg')
        img_size = (img.width, img.height)
        templ = self.load_template('Change-My-Mind.json', debug=0)
        self.test_calc_start_location(text, img_size, templ)
        # self.test_fit_text(templ)

    def test_fit_text(self, templ):
        box_def = templ[0]
        self._get_font = templ._get_font
        self._debug = templ._debug
        text_dict = {
            'short': 'Memes',
            'medium': 'This is a test',
            'long': 'What the fuck did you say about me you little bitch, I\'ll have you know I...',
            'multiline': "Shouldn't have a big effect or make a difference to you though.\nNormal people who are concerned about me would probably tell you to stay a bit away from me then, but the hell am I gonna tell you/do that.\nDon't know why I always only like people"
        }
        box_size_dict = {
            'small': (100, 50),
            'medium': (150, 100),
            'large': (300, 400),
            'narrow': (50, 400),
            'wide': (400, 50)
        }
        for box_name, box_size in box_size_dict.items():
            for name, text in text_dict.items():
                # if box_name != 'medium' or name != 'long':
                #     continue
                templ._stroke_width = box_def.stroke_width
                box = Image.new('RGBA', box_size, color=(255, 255, 255, 255))
                templ._draw = ImageDraw.Draw(box)
                text, font = templ._fit_text(text, box_def.font, box_def.font_size, box_size)
                text_start = templ._calc_start_location(templ._tsize(text, font), box_size, 'bottom-center')
                templ._draw.multiline_text(text_start, text=text, fill=box_def.fill, font=font, spacing=templ._line_spacing,
                                           stroke_fill=box_def.stroke_fill, stroke_width=templ._stroke_width)
                box.save(f'text/{box_name}_{name}.png')

    def test_calc_start_location(self, text, img_size, templ):
        box_def = templ[0]
        box_size = templ._check_box_size(box_def.size, img_size)
        font = templ._get_font(box_def.font, 16)
        pos_dict = {
            'left-top': [-1, 1], 'center-top': [0, 1], 'right-top': [1, 1],
            'left-center': [-1, 0], 'center': [0, 0], 'right-center': [1, 0],
            'left-bottom': [-1, -1], 'center-bottom': [0, -1], 'right-bottom': [1, -1],
        }
        text_size = font.getsize(text)
        print(f'Text size: {text_size}, box size: {box_size}')
        for name, position in pos_dict.items():
            ret = templ._calc_start_location(text_size, box_size, position)
            print(f'Position {position}: {ret}')
            box = Image.new('RGBA', box_size, color=(255, 255, 255, 255))
            draw = ImageDraw.Draw(box)
            draw.text(ret, text=text, fill=box_def.fill, font=font,
                      stroke_fill=box_def.stroke_fill, stroke_width=box_def.stroke_width)
            box.save(f'text/{name}.png')

    def _aprox_text_size(self, text: str, width: int, height: int) -> Tuple[int, int]:
        """Approximate text size using the letter X"""
        x, y = 0, 0
        lines = text.split('\n')
        for line in lines:
            if len(line) > x:
                x = len(line)*width
            y += height
        return x, y

    def load_template(self, file: str, debug=0) -> MemeTemplate:
        try:
            with open(os.path.join(self.meme_dir, file), 'r', encoding='utf-8') as fr:
                return MemeTemplate(json.load(fr), debug=debug)
        except Exception as e:
            raise MemeTemplateError(str(e))


if __name__ == '__main__':
    if not os.path.exists('output'):
        os.mkdir('output', 0o755)
    t = TestMeme()
    t.test_template()
