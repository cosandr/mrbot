import os
from typing import Optional, List, Dict, NamedTuple, Tuple

from PIL import Image, ImageDraw, ImageFont

from ext import utils
from .errors import MemeTemplateError, MemeEntryError, MemeFontNotFound


class TextBox(NamedTuple):
    """Holds a meme's text box properties"""
    start: Tuple[int, int]
    size: Tuple[int, int]
    text_align: Tuple[int, int]
    angle: float
    fill: str
    font: str
    font_size: int
    stroke_width: int
    stroke_fill: str


class MemeTemplate:
    """Holds meme template info and methods for creating them"""

    """
    # TODO: Write bottom to top
    # TODO: Adjust text_start if it will overflow, start at 0 in that case?
    --- JSON file structure ---
{
    "name": <Display name>,
    "file": <Relative path to image file>,
    # Define text boxes
    "boxes": [
        # NOTE: X and/or Y positions can be set to -1 to indicate auto-centering
        # NOTE: If width or height (size) are -1 then it will use the entire image for that dimension
        # NOTE: Text alignment is defined using -1, 0 and 1 where -1 is left/bottom, 0 is center and 1 is right/top
        #       The first number in the array is width and the second height, i.e. [0, 1] means top center
        {
            "start": [204, 228],    # Box starting at (204, 228) pixels
            "size": [218, 90],      # 218 pixels long and 90 pixels tall
            "text-align": [-1, 1],  # Align to the top left corner
            "angle": 5.76,          # Rotate text 5.76 degrees
            "fill": "black",        # Text color is black
            "font": "consola",      # Font is Consolas
            "font-size": 36,        # Size 36
            "stroke-width": 1,      # Stroke (outline) width of 1 pixel
            "stroke-fill": "black"  # Stroke is black
        }
    ]
}
    --- JSON file structure ---
    """
    _font_dir = os.path.join(os.path.dirname(__file__), 'fonts')
    meme_dir = os.path.join(os.path.dirname(__file__), 'meme-templates')

    def __init__(self, in_dict: Dict, debug: int = 0):
        self.name: str = ""
        self.file: str = ""
        self._debug: int = debug
        self._text_boxes: List[TextBox] = []
        self._parse_info(in_dict)
        self._draw = None
        self._stroke_width = 0
        self._line_spacing = 2

    def __str__(self):
        ret = f'### {self.name} ###\n'
        for t in self._text_boxes:
            ret += f'{t}\n'
        return ret

    def __getitem__(self, item: int):
        if not isinstance(item, int):
            raise IndexError('Index must be int')
        return self._text_boxes[item]

    def __len__(self):
        return len(self._text_boxes)

    def make(self, lines: List[str]) -> Image.Image:
        return self._text_on_image(lines)

    def _get_font(self, name: str, size: int) -> Optional[ImageFont.FreeTypeFont]:
        meant = utils.find_similar_str(name, os.listdir(self._font_dir))
        if not meant:
            raise MemeFontNotFound(f'Font {name} not found')
        font_path = os.path.join(self._font_dir, meant[0])
        return ImageFont.truetype(font=font_path, size=size)

    def _text_on_image(self, entries: List[str]) -> Image.Image:
        """Writes entries onto this meme, raises BadMemeEntries"""
        if len(entries) != len(self._text_boxes):
            raise MemeEntryError(f'Expected {len(self._text_boxes)} text boxes, got {len(entries)}')
        img = Image.open(self.file)
        img_size = (img.width, img.height)
        for i in range(len(entries)):
            box_def = self._text_boxes[i]
            box_size = self._check_box_size(box_def.size, img_size)
            self._stroke_width = box_def.stroke_width
            box = Image.new('RGBA', box_size, color=0)
            self._draw = ImageDraw.Draw(box)
            text, font = self._fit_text(entries[i], box_def.font, box_def.font_size, box_size)
            # Calculate position using smaller box to avoid clipping
            smaller_box = (box.size[0], box.size[1]-(font.font.height * 0.17))
            text_start = self._calc_start_location(self._tsize(text, font), smaller_box, box_def.text_align)
            self._draw.multiline_text(text_start, text=text, fill=box_def.fill, font=font, spacing=self._line_spacing,
                                      stroke_fill=box_def.stroke_fill, stroke_width=self._stroke_width)
            # Rotate around center and resample so it doesn't look awful
            if box_def.angle > 0:
                if self._debug > 1:
                    print(f'Rotating {box_size} box {box_def.angle:.1f} degrees')
                # box = box.rotate(box_def.angle, center=(0, 0), expand=1, resample=Image.BICUBIC)
                box = box.rotate(box_def.angle, expand=1, resample=Image.BICUBIC)
            box_start = self._check_coords(box_def.start, box_size, img_size)
            if self._debug > 0:
                print(f'Pasting {box_size} size box starting at {box_start} on {img_size} image')
            img.paste(box, box_start, box)
        return img

    def _tsize(self, text: str, font):
        return self._draw.multiline_textsize(text, font=font, spacing=self._line_spacing, stroke_width=self._stroke_width)

    def _fit_text(self, text: str, font_name: str, font_size: int, box_size: Tuple[int, int]) -> Tuple[str, ImageFont.FreeTypeFont]:
        font = self._get_font(font_name, font_size)
        # Actual x and y
        xa, ya = self._tsize(text, font)
        # Box x and y
        xb, yb = box_size
        if self._debug > 0:
            print(f'--- Box ({xb}, {yb}), text: ({xa}, {ya}) ---')
        # Do nothing if it fits
        if xa < xb and ya < yb:
            return text, font
        return self._fix_text_both(text, font, xb, yb)

    def _fix_text_both(self, text, font, xb, yb, recurse=False) -> Tuple[str, ImageFont.FreeTypeFont]:
        # Remove whitespace
        text = ' '.join(text.split())
        xa, ya = self._tsize(text, font)
        # Too wide, split
        if xa > xb:
            text = self._fit_text_wide(text, font, xb)
            xa, ya = self._tsize(text, font)
            if self._debug > 1:
                print(f' - Width correction ({xa}, {ya})\n -- Corrected text --\n{text}')
        # Too tall, shrink font size
        if ya > yb:
            font = self._fit_text_tall(text, font, yb)
            xa, ya = self._tsize(text, font)
            if self._debug > 1:
                print(f' - Height correction ({xa}, {ya}) size {font.size}')
            # Run again if still too large
            if xa > xb or ya > yb and not recurse:
                return self._fix_text_both(text, font, xb, yb, True)
        return text, font

    def _fit_text_tall(self, text: str, font: ImageFont.FreeTypeFont, yb: int) -> Optional[ImageFont.FreeTypeFont]:
        # Decrease by 1 until it fits
        for i in range(font.size, 8, -1):
            xa, ya = self._tsize(text, font)
            if ya > yb:
                # Reduce stroke width
                if self._stroke_width > 1:
                    self._stroke_width -= 1
                font = font.font_variant(size=i)
                continue
            break
        return font

    def _fit_text_wide(self, text: str, font: ImageFont.FreeTypeFont, xb: int) -> str:
        lines: List[str] = []
        tmp = ''
        # Split on space
        for word in text.split():
            xa, _ = self._tsize(f'{tmp} {word}', font)
            if xa > xb:
                lines.append(tmp)
                tmp = ''
            tmp = f'{tmp} {word}'
        lines.append(tmp)
        return '\n'.join(lines)

    @staticmethod
    def _calc_start_location(text_size: Tuple[int, int], box_size: Tuple[int, int], position: Tuple[int, int]) -> Tuple[int, int]:
        """Return starting location such that the text is in given position"""
        xb, yb = box_size
        xt, yt = text_size
        xp, yp = position
        ret_x = {
            -1: 0,
             0: (xb / 2) - (xt / 2),
             1: xb - xt,
        }.get(xp, None)
        if ret_x is None:
            raise RuntimeError(f'Unknown X alignment: {xp}')
        ret_y = {
            -1: yb - yt,
             0: (yb/2) - (yt/2),
             1: 0,
        }.get(yp, None)
        if ret_y is None:
            raise RuntimeError(f'Unknown Y alignment: {xp}')
        return int(ret_x), int(ret_y)

    def _check_coords(self, coords: Tuple[int, int], box_size: Tuple[int, int], target_size: Tuple[int, int]) -> Tuple[int, int]:
        """Centers coordinates that are set to -1"""
        x, y = coords
        if x >= 0 and y >= 0:
            return x, y
        center = self._center_box(box_size, target_size)
        if x == -1:
            x = center[0]
        if y == -1:
            y = center[1]
        if self._debug > 1:
            print(f' --- CHECK COORDS ---\nCoords: {coords}, Box size: {box_size}, Target size: {target_size}\nOUTPUT ({x}, {y}), CENTER: {center}')
        return x, y

    def _check_box_size(self, box_size: Tuple[int, int], img_size: Tuple[int, int]) -> Tuple[int, int]:
        """Return box size, expanding to img size if x/y set to -1"""
        x, y = box_size
        if x == -1:
            x = img_size[0]
        if y == -1:
            y = img_size[1]
        if self._debug > 1:
            print(f' --- CHECK BOX SIZE ---\nBox size: {box_size}, Img size: {img_size}\nOUTPUT ({x}, {y})')
        return x, y

    @staticmethod
    def _center_box(box_size: Tuple[int, int], target_size: Tuple[int, int]) -> Tuple[int, int]:
        """Returns the starting X and Y positions in order to center the given box"""
        return int(abs(target_size[0] - box_size[0]) / 2), int(abs(target_size[1] - box_size[1]) / 2)

    def _parse_info(self, in_dict: Dict) -> None:
        """Parse input dict into class attributes"""
        try:
            self.name = in_dict['name']
            self.file = os.path.join(self.meme_dir, in_dict['file'])
            for t in in_dict['boxes']:
                self._text_boxes.append(
                    TextBox(
                        start=tuple(t.get('start', (-1, -1))),
                        size=tuple(t.get('size', (-1, -1))),
                        text_align=tuple(t.get('text-align', (0, 0))),
                        fill=t.get('fill', 'white'),
                        angle=t.get('angle', 0),
                        stroke_width=t.get('stroke-width', 2),
                        stroke_fill=t.get('stroke-fill', 'black'),
                        font=t.get('font', 'choco'),
                        font_size=t.get('font-size', 16),
                    )
                )
        except Exception as e:
            raise MemeTemplateError(str(e))
