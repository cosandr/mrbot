import math
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO
from typing import Sequence, Optional, List, Tuple, MappingView, Set, Union, Any
from zoneinfo import ZoneInfo

import asyncpg
import discord
from aiohttp import ClientSession
from jellyfish import jaro_winkler_similarity

re_url = re.compile(r'https?://\S+', re.IGNORECASE)
re_img_url = re.compile(r'https?://\S+(\.png|\.jpg|\.jpeg)', re.IGNORECASE)
re_id = re.compile(r'\d{18}')


def str_or_none(val: Optional[Any]) -> Optional[str]:
    """Cast val to string, keeping None."""
    if val is None:
        return None
    return str(val)


def format_dt(dt: datetime, fmt: str, tz: Optional[str] = None) -> str:
    """Format a datetime object (non-aware assumes UTC), if tz is not provided system-time is used"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if not tz:
        return dt.astimezone().strftime(fmt)
    return dt.astimezone(ZoneInfo(tz)).strftime(fmt)


@asynccontextmanager
async def pg_connection(dsn: str):
    """Async context manager for PSQL database connection"""
    con = await asyncpg.connect(dsn=dsn)
    try:
        yield con
    finally:
        await con.close()


def cleanup_http_params(params: dict, remove_none=True) -> dict:
    """Converts all dict values to string, optionally remove None values"""
    for k in list(params.keys()):
        if remove_none and params[k] is None:
            params.pop(k)
            continue
        params[k] = str(params[k])
    return params


def transparent_embed(**kwargs) -> discord.Embed:
    """Returns a transparent embed, keywords arguments are passed to Embed constructor"""
    return discord.Embed(colour=0x36393E, **kwargs)


def paginate(content: str, max_len=2000, wrap="```", header='', lookback_max=20) -> List[str]:
    # TODO: Replace existing stuff with this function, search regex: if .*\s+(<|>|=)+\s+\d{4}
    """Splits text line by line

    Get character at position max_len (and its multiples) and split the string at that point
    Look behind for the first newline, fallback to whitespace and finally just split if neither are possible

    :param content: Text to split
    :param max_len: Maximum length of each page, default 2000
    :param wrap: Characters to use for wrapping, default ``` (code blocks)
    :param header: Header to add to each page
    :param lookback_max: How many characters to look back in search of a better split alternative
    :return: List of pages, if the input is already less than max_len, it returns immediately
    """
    if wrap:
        max_len -= 2 * len(wrap)
    if header:
        max_len -= len(header) + 1
    if len(content) <= max_len:
        if header:
            content = f'{header}\n{content}'
        if wrap:
            return [f"{wrap}{content}{wrap}"]
        return [content]
    # Find latest preferable split point, within lookback_max chars of max_len blocks
    split_idx: List[int] = [0]
    end = max_len
    start = end - lookback_max
    running = True
    while running:
        split_at: int = 0
        for i in range(end-1, start, -1):
            # Stop at latest newline
            if content[i] == "\n":
                split_at = i
                break
            # Prefer spaces over characters
            if content[i] == " " and content[split_at] != " ":
                split_at = i

        # Any character if we didn't find a space earlier
        if not split_at:
            split_at = end - 1
        split_idx.append(split_at+1)
        end = split_at + 1 + max_len
        if end >= len(content):
            running = False
            end = len(content)
        start = end - lookback_max
    split_idx.append(len(content))
    pages = []
    for i in range(len(split_idx)-1):
        split_from = split_idx[i]
        split_to = split_idx[i+1]
        # Remove whitespace if it was included
        add_str = content[split_from:split_to].strip()
        if header:
            add_str = f'{header}\n{add_str}'
        if wrap:
            add_str = f"{wrap}{add_str}{wrap}"
        pages.append(add_str)
    return pages


def fmt_plural_str(num: int, what: str) -> str:
    """Adds s to 'what' if needed

    (0, 'video') -> 0 videos
    (1, 'video') -> 1 video
    (10, 'video') -> 10 videos
    """
    if num == 1:
        return f"{num} {what}"
    return f"{num} {what}s"


def to_columns_vert(in_list: Sequence[str], num_cols: int = 4, sort: bool = False) -> str:
    if sort:
        in_list = sorted(in_list, key=str.casefold)
    # Determine how many rows we will have, rounding down
    num_rows = math.ceil(len(in_list) / num_cols)
    # Create row 2 dim list
    cols = []
    tmp = []
    for el in in_list:
        tmp.append(el)
        if len(tmp) == num_rows:
            cols.append(tmp)
            tmp = []
    if tmp:
        cols.append(tmp)
    # Determine padding per row
    padding = [max(len(el) for el in r)+2 for r in cols]
    ret_str = ""
    for i in range(num_rows):
        for j in range(num_cols):
            if j >= len(cols) or i >= len(cols[j]):
                continue
            ret_str += f'{cols[j][i]:{padding[j]}s}'
        ret_str += "\n"

    return ret_str


def to_columns_horiz(in_list: Sequence[str], cols: int = 4, sort: bool = False) -> str:
    """Returns a string formatted in columns"""
    if sort:
        in_list = sorted(in_list, key=str.casefold)
    longest_name = 0
    for el in in_list:
        if len(el) > longest_name:
            longest_name = len(el)
    ret_str = ""
    for i in range(len(in_list)):
        if i % cols == 0:
            ret_str += '\n'
        ret_str += f"{in_list[i]:{longest_name}s}\t"
    return ret_str


def get_url(check: str, img_only: bool = False, one: bool = True) -> Union[str, List[str]]:
    """Returns the URL(s) in the check string, empty list if not found"""
    ret = []
    if img_only:
        match = re_img_url.search(check)
    else:
        match = re_url.search(check)
    if match:
        if one:
            return match.group()
        ret.append(match.group())
    return ret


def find_closest_match(name: str, names: Sequence[str], _recurse_call: bool = False) -> Optional[Tuple[str, float]]:
    """Returns the closest match and its similarity

    Similarity is 1.0 if they are an exact match"""
    # Check exact matches
    for el in names:
        if el == name:
            return name, 1.0
    # Convert to lower if not recursive call
    if _recurse_call:
        names_lower = names
    else:
        name = name.lower()
        names_lower = [el.lower() for el in names]
    # Case insensitive exact matches
    for i in range(len(names)):
        if names_lower[i] == name:
            return names[i], 1.0
    # Loose matches
    meant = {}
    for i in range(len(names)):
        for word_name in name.split():
            targets = names_lower[i].split()
            # Remove 5% for each word
            # Searching for "example" in "this is an example"
            # will return a similarity of 0.8
            penalty = 0.05 * len(targets)
            sim_list = []
            for word_target in targets:
                # Exact match for a word
                if word_name == word_target:
                    sim_list.append(1.0 - penalty)
                    break
                else:
                    sim_list.append(jaro_winkler_similarity(word_name, word_target) - penalty)
            best = max(sim_list)
            if best > 0.5 and best > meant.get(names[i], 0):
                meant[names[i]] = best
    # Similar strings
    for i in range(len(names)):
        sim = jaro_winkler_similarity(name, names_lower[i])
        if sim > meant.get(names[i], 0):
            meant[names[i]] = sim
    # If we have no matches still, try removing spaces
    if not meant and not _recurse_call:
        name = ''.join(name.strip())
        names = [''.join(el.strip()) for el in names_lower]
        meant = find_closest_match(name, names, _recurse_call=True)
    if not meant or meant == ('', 0):
        return '', 0
    for k, v in reversed(sorted(meant.items(), key=lambda item: item[1])):
        # Reject if it is too dissimilar
        if v < 0.5:
            return '', 0
        return k, v


def find_similar_str(name: str, names: Union[Sequence[str], MappingView[str]], _recurse_call: bool = False) -> Optional[List[str]]:
    """Finds items similar to `name` in `names`"""
    meant: Set[str] = set()
    # Check exact matches
    for el in names:
        if el == name:
            meant.add(el)
            break
    name = name.lower()
    names_lower = [el.lower() for el in names]
    # Case insensitive exact matches
    for i in range(len(names)):
        if names_lower[i] == name:
            meant.add(names[i])
    # Loose matches
    for i in range(len(names)):
        # Similar strings
        if jaro_winkler_similarity(name, names_lower[i]) > 0.8:
            meant.add(names[i])
        # Input in output or vice versa
        if name in names_lower[i] or names_lower[i] in name:
            meant.add(names[i])
    # If we have no matches still, try removing spaces
    if len(meant) == 0 and not _recurse_call:
        name = ''.join(name.strip())
        names = [''.join(el.strip()) for el in names_lower]
        return find_similar_str(name, names, _recurse_call=True)
    return list(meant)


def human_timedelta(dt: datetime, max_vals: int = 3) -> str:
    times = {
        'year': int(3.154e7),
        'month': int(2.628e6),
        'week': 604800,
        'day': 86400,
        'hour': 3600,
        'minute': 60,
        'second': 1
    }
    ret_str = ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    past = seconds > 0
    seconds = abs(seconds)
    if seconds < 1:
        return "just now" if past else "about now"
    tmp = 0
    for name, val in times.items():
        if tmp >= max_vals:
            break
        unit, rem = divmod(seconds, val)
        if unit == 0:
            continue
        if unit == 1:
            ret_str += f"{int(unit)} {name}, "
        else:
            ret_str += f"{int(unit)} {name}s, "
        seconds = rem
        tmp += 1
    return f"{ret_str[:-2]} ago" if past else f"in {ret_str[:-2]}"


def fmt_timedelta(td: timedelta, with_seconds: bool = False) -> str:
    """Return timedelta formatted with H and M. """
    h, rem = divmod(td.seconds, 3600)
    m, s = divmod(rem, 60)
    if with_seconds and s > 0:
        return f"{h}h {m}m {s}s"
    return f"{h}h {m}m"


def human_timedelta_short(dt: datetime, max_vals: int = 3) -> str:
    times = {
        'y': int(3.154e7),
        'mo': int(2.628e6),
        'w': 604800,
        'd': 86400,
        'h': 3600,
        'm': 60,
        's': 1
    }
    ret_str = ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    past = seconds > 0
    seconds = abs(seconds)
    if seconds < 1:
        return "just now" if past else "about now"
    tmp = 0
    for name, val in times.items():
        if tmp >= max_vals:
            break
        unit, rem = divmod(seconds, val)
        if unit == 0:
            continue
        ret_str += f"{int(unit)}{name}, "
        seconds = rem
        tmp += 1
    return f"{ret_str[:-2]} ago" if past else f"in {ret_str[:-2]}"


def human_large_num(num, with_zeroes: bool = False, e_notation: bool = False) -> str:
    scale = {
        'septillion': 1e24,
        'sextillion': 1e21,
        'quintillion': 1e18,
        'quadrillion': 1e15,
        'trillion': 1e12,
        'billion': 1e9,
        'million': 1e6
    }
    ret_str = None
    for name, val in scale.items():
        if isinstance(num, Decimal):
            val = Decimal(val)
        unit = num / val
        if unit < 1:
            continue
        if val > 1e15:
            e_notation = True
        ret_str = f"{unit:,.2f} {name}"
        if e_notation:
            power = int(math.log10(num))
            digit = num / (10**power)
            ret_str += f" ({digit:.2f}e{power})"
        elif with_zeroes:
            ret_str += f" ({math.floor(math.log10(num))} zeroes)"
        break
    if not ret_str:
        return f"{num:,.0f}"
    return ret_str


def human_seconds(seconds: float, num_units=2, precision=0, sep='') -> str:
    """Convert seconds to whatever unit is closest

    :param seconds: Seconds to parse
    :param num_units: How many units to include
    :param precision: How many significant figures the last unit has
    :param sep: What separates the units in the output string
    :return: Human readable string for the input seconds
    """
    times = {
        'y': 3.154e7,
        'mo': 2.628e6,
        'w': 604800,
        'd': 86400,
        'h': 3600,
        'm': 60,
        's': 1,
        'ms': 1e-3,
        'us': 1e-6,
        'ns': 1e-9,
    }
    key_list = list(times.keys())
    ret = []
    for i, k in enumerate(key_list):
        q, r = divmod(seconds, times[k])
        if q == 0:
            continue
        # Last item
        if len(ret) == num_units - 1:
            ret.append(f'{r+q:.{precision}f}{k}')
            break
        ret.append(f'{q:.0f}{k}')
        seconds = r
    return sep.join(ret)


def get_channel_name(message: discord.Message) -> str:
    """Returns channel name if in guild, otherwise returns `DM`."""
    if isinstance(message.channel, (discord.DMChannel, discord.GroupChannel)):
        return "DM"
    return message.channel.name


def find_url_type(url: str) -> str:
    """
    Helper function for finding URL types,
    recognizes image links, Twitch and YouTube.
    All other links simply return `link`.
    Parameters
    ----------
    url: `str`
        URL to identify.
    Returns
    --------
    `str`
        URL domain, if recognized.
    """
    if url.lower().endswith(('.jpg', '.png', '.jpeg')):
        return 'image'
    if 'twitch' in url:
        return 'twitch'
    if 'youtu' in url:
        return 'youtube'
    return 'link'


async def bytes_from_url(url: str, sess: ClientSession) -> BytesIO:
    """
    Save `url` content into a `BytesIO` buffer and return it.
    Parameters
    ----------
    url: `str`
        URL to download.
    sess: `ClientSession`
        Asyncio session to use
    Returns
    --------
    `BytesIO`
        Buffer with downloaded content.
    """
    async with sess.get(url) as resp:
        return BytesIO(await resp.read())


async def file_from_url(filepath: str, url: str, sess: ClientSession):
    """
    Save `url` content into the fie at `filepath`, argument includes file extension.
    Parameters
    ----------
    filepath: `str`
        Path to file
    url: `str`
        URL to download.
    sess: `ClientSession`
        Asyncio session to use
    """
    async with sess.get(url) as resp:
        with open(filepath, 'wb') as fw:
            fw.write(await resp.read())


class QueueItem:
    """Work around PriorityQueue not working with coroutines"""
    def __init__(self, priority: int, coro):
        self.priority = priority
        self.coro = coro

    def __gt__(self, other):
        return self.priority > other.priority
