import asyncio
import os

import numpy as np

from .error import SnakeDiedError


class _Getch:
    """
    Gets a single character from standard input.\n
    Does not echo to the screen.
    """
    def __init__(self):
        try:
            self.impl = _GetchWindows()
        except ImportError:
            self.impl = _GetchUnix()

    def __call__(self):
        return self.impl()


class _GetchUnix:
    def __init__(self):
        pass

    def __call__(self):
        import sys, tty, termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return ch.encode('utf-8')


class _GetchWindows:
    def __init__(self):
        pass

    def __call__(self):
        import msvcrt
        return msvcrt.getch()


class Playfield:

    props = {"empty":     {"val": 0, "ascii": "  ", "emoji": "💦"},
             "snakehead": {"val": 1, "ascii": "@ ", "emoji": "🍆"},
             "snakeseg":  {"val": 2, "ascii": ". ", "emoji": "💩"},
             "apple":     {"val": 3, "ascii": "A ", "emoji": "🍎"}}

    def __init__(self, dim_x: int, dim_y: int):
        self._field = np.zeros((dim_x, dim_y))
        self._xsize = dim_x
        self._ysize = dim_y
    
    @property
    def field(self):
        return self._field
    
    @property
    def xsize(self):
        return self._xsize
    
    @property
    def ysize(self):
        return self._ysize
    
    def new_food(self, snake):
        """Generates new food on field"""
        while True:
            x = np.random.randint(0, self.xsize-1)
            y = np.random.randint(0, self.ysize-1)
            # Don't place food inside snake or on top of more food
            if (x, y) in snake or self.get((x, y)) == self.prop_val('apple'):
                continue
            self.set((x, y), 'apple')
            return

    def __repr__(self):
        """Returns ASCII representation of field"""
        top_bot_border = '-' * 4 + '--' * self.ysize + "\n"
        ret_str = top_bot_border
        for i in range(self.xsize):
            ret_str += "| "
            for j in range(self.ysize):
                for prop in self.props.values():
                    if prop['val'] == self.field[i][j]:
                        ret_str += prop['ascii']
                        break
            ret_str += " |\n"
        return ret_str + top_bot_border
    
    def discord(self):
        """Return string for display on Discord"""
        ret_str = f"```\n"
        for i in range(self.xsize):
            for j in range(self.ysize):
                for prop in self.props.values():
                    if prop['val'] == self.field[i][j]:
                        ret_str += prop['emoji']
                        break
            ret_str += "\n"
        return f"{ret_str}```"

    def prop_val(self, prop: str):
        """Returns value of prop"""
        return self.props[prop]['val']

    def set(self, coords: tuple, prop: str):
        """Set index (x, y) to `prop`'s value"""
        if coords is not None:
            self.field[coords[0]][coords[1]] = self.props[prop]['val']
    
    def get(self, coords: tuple):
        """Get index (x, y)"""
        return self.field[coords[0]][coords[1]]


class Segment:
    """Base snake segment class"""
    _curr = None
    _prev = None
    next_seg = None
    prev_seg = None

    def __init__(self, prev_seg):
        self.prev_seg = prev_seg
        self.curr = prev_seg.prev

    def __repr__(self):
        return f"({self.curr[0]}, {self.curr[1]})"

    @property
    def prev(self):
        return self._prev
    
    @property
    def curr(self):
        return self._curr
    
    @curr.setter
    def curr(self, curr: tuple):
        self._prev = self.curr
        self._curr = curr
    
    def move(self):
        """Update segment position recursively"""
        if self.prev_seg is not None:
            self.curr = self.prev_seg.prev
        if self.next_seg is not None:
            if self.curr == self.next_seg.curr:
                raise SnakeDiedError("You cannot turn into yourself.")
            self.next_seg.move()
    
    def upd_field(self, field: Playfield):
        """Set previous position as empty, current as segment"""
        # Don't empty field if the head is there
        if self.prev is not None and field.get(self.prev) != field.prop_val('snakehead'):
            field.set(self.prev, 'empty')
        field.set(self.curr, 'snakeseg')
        if self.next_seg is not None:
            self.next_seg.upd_field(field)

    def print_all(self, ret_str: str = '', depth: int = 0):
        """Returns string with info about all segment positions"""
        ret_str += f"- {depth} Curr: {self.curr}, Prev: {self.prev}\n"
        depth += 1
        if self.next_seg is None:
            return ret_str
        else:
            return self.next_seg.print_all(ret_str, depth)

    def add_seg(self):
        """Adds segment at the end of the chain"""
        if self.next_seg is None:
            self.next_seg = Segment(prev_seg=self)
        else:
            self.next_seg.add_seg()
        
    def _calc_len(self, tmp: int = 0):
        """Internal method for calculating number of segments"""
        tmp += 1
        if self.next_seg is None:
            return tmp
        else:
            return self.next_seg._calc_len(tmp)

    def __contains__(self, item):
        """Returns True if segment is currently at position given by `item` tuple"""
        if isinstance(item, tuple):
            if self.curr == item:
                return True
            elif self.next_seg is not None:
                return item in self.next_seg
            else:
                return False
        
    def __eq__(self, item):
        if isinstance(item, tuple):
            return self.curr == item
    
    def __len__(self):
        """Returns number of segments"""
        return self._calc_len()


class Snake(Segment):
    """Snake entity class"""
    def __init__(self, field: Playfield):
        self._field = field
        self._init_field()

    def _init_field(self):
        """Adds snake and one piece of food randomly on the field"""
        # Random snake starting position
        start_x = np.random.randint(0, self.field.xsize-1)
        start_y = np.random.randint(0, self.field.ysize-1)
        self.curr = (start_x, start_y)
        self.upd_field()
        # Generate new food
        self.field.new_food(self)

    @property
    def field(self):
        return self._field
    
    def upd_field(self):
        """Set previous position as empty, current as head"""
        self.field.set(self.prev, 'empty')
        self.field.set(self.curr, 'snakehead')
        if self.next_seg is not None:
            self.next_seg.upd_field(self.field)

    def _logic_calc(self):
        """Determines what should happen next, add food, end game etc."""
        self.move()
        # Check if we hit ourselves
        if self.next_seg is not None and self.curr in self.next_seg:
            raise SnakeDiedError("You've hit yourself.")
        # Check if we ate food
        if self.field.get(self.curr) == self.field.prop_val('apple'):
            self.add_seg()
            self.field.new_food(self)
        self.upd_field()

    def up(self):
        """Moves snake up"""
        max_x = self.field.xsize - 1
        # Going too far down, reset to first column
        if self.curr[0] - 1 < 0:
            self.curr = (max_x, self.curr[1])
        else:
            self.curr = (self.curr[0]-1, self.curr[1])
        self._logic_calc()

    def down(self):
        """Moves snake down"""
        max_y = self.field.ysize - 1
        # Going too far down, reset to first column
        if self.curr[0] + 1 > max_y:
            self.curr = (0, self.curr[1])
        else:
            self.curr = (self.curr[0]+1, self.curr[1])
        self._logic_calc()

    def right(self):
        """Moves snake right"""
        max_x = self.field.xsize - 1
        # Going too far right, reset to first row
        if self.curr[1] + 1 > max_x:
            self.curr = (self.curr[0], 0)
        else:
            self.curr = (self.curr[0], self.curr[1]+1)
        self._logic_calc()

    def left(self):
        """Moves snake left"""
        max_y = self.field.ysize - 1
        if self.curr[1] - 1 < 0:
            self.curr = (self.curr[0], max_y)
        else:
            self.curr = (self.curr[0], self.curr[1]-1)
        self._logic_calc()


def clear():
    if os.name == 'nt':
        os.system('cls')
    else:
        os.system('clear')


pf = Playfield(10, 10)
snake = Snake(pf)
moves = {'up': snake.up,
         'down': snake.down,
         'left': snake.left,
         'right': snake.right}
move_dir = 'right'
    

async def board_update():
    """Updates the entire board"""
    global snake, move_dir, moves
    while True:
        try:
            moves[move_dir]()
            clear()
            print(snake.field)
            print(f"Segments: {len(snake)}")
            await asyncio.sleep(0.1)
        except Exception as e:
            if isinstance(e, asyncio.CancelledError):
                print("Board update task cancelled.")
            elif isinstance(e, SnakeDiedError):
                print(f"You died: {e}")
            else:
                print(f"Exception: {e}")
            break


async def read_keyboard(loop):
    """Continuously read keyboard input"""
    global snake, move_dir
    getch = _Getch()
    while True:
        try:
            key = await loop.run_in_executor(None, lambda: getch())
            if key == b'\x03':
                raise KeyboardInterrupt
            key = key.decode('utf-8')
            if key == 'w':
                # snake.up()
                move_dir = 'up'
            elif key == 's':
                # snake.down()
                move_dir = 'down'
            elif key == 'a':
                # snake.left()
                move_dir = 'left'
            elif key == 'd':
                # snake.right()
                move_dir = 'right'
        except asyncio.CancelledError:
            print("Snake mover task cancelled.")
            break


async def main(loop):
    board_task = loop.create_task(board_update())
    snake_task = loop.create_task(read_keyboard(loop))
    try:
        await snake_task
    except KeyboardInterrupt:
        board_task.cancel()
        snake_task.cancel()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    try:
        try:
            loop.run_until_complete(main(loop))
        except Exception as e:
            print(f"Game over: {e}")
    except KeyboardInterrupt:
        pass
