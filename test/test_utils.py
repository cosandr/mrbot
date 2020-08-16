import json
import random

import pytest

from ext import utils

with open('wordlist.json', 'r') as fr:
    WORDS = json.load(fr)


def wrap_str(content: str, wrap="```"):
    return f"{wrap}{content}{wrap}"


def generate_words(max_length=3000, with_newline=True, no_whitespace=False):
    ret_str = ""
    while True:
        add = random.choice(WORDS)
        num = random.randint(0, 10)
        if not no_whitespace:
            if num < 1 and with_newline:
                ret_str += "\n"
            elif num < 3:
                ret_str += random.choice((", ", ". "))
            else:
                ret_str += " "
        if len(ret_str) + len(add) > max_length:
            break
        ret_str += add
    return ret_str


def test_paginate():
    max_len = 100
    expected = [
        # --- No whitespace ---
        {
            "comment": "1 page",
            "input": "1" * max_len,
            "output": [
                "1" * max_len,
            ],
        },
        {
            "comment": "2 pages",
            "input": "1" * max_len + "2" * max_len,
            "output": [
                "1" * max_len,
                "2" * max_len,
            ],
        },
        {
            "comment": "2.5 pages",
            "input": "1" * max_len + "2" * max_len + "3" * int(max_len/2),
            "output": [
                "1" * max_len,
                "2" * max_len,
                "3" * int(max_len/2),
            ],
        },
        {
            "comment": "3 pages",
            "input": "1" * max_len + "2" * max_len + "3" * max_len,
            "output": [
                "1" * max_len, "2" * max_len,
                "3" * max_len,
            ],
        },
        # --- With spaces ---
        {
            "comment": "1 page, with spaces",
            "input": "1" * (max_len-10) + " " + "1" * 9,
            "output": [
                "1" * (max_len-10) + " " + "1" * 9,
            ],
        },
        {
            "comment": "2 pages (90 1's, single space, 91 2's)",
            "input": "1" * (max_len-10) + " " + "2" * (max_len-9),
            "output": [
                "1" * (max_len-10),
                "2" * (max_len-9),
            ],
        },
        {
            "comment": "2 pages, space too late (100 1's, 10 2's, space, 89 2's)",
            "input": "1" * max_len + "2" * 10 + " " + "2" * (max_len-11),
            "output": [
                "1" * max_len,
                "2" * 10 + " " + "2" * (max_len-11),
            ],
        },
        {
            "comment": "2 pages, space too early (60 1's, space, 100 2's)",
            "input": "1" * 60 + " " + "1" * 39 + "2" * max_len,
            "output": [
                "1" * 60 + " " + "1" * 39,
                "2" * max_len,
            ],
        },
        {
            "comment": "2 pages, two spaces early enough (80 1's, space, 9 1's, space, 100 2's)",
            "input": "1" * (max_len-20) + " " + "1" * 9 + " " + "2" * max_len,
            "output": [
                "1" * (max_len-20) + " " + "1" * 9,
                "2" * max_len,
            ],
        },
        # --- With spaces and newlines ---
        {
            "comment": "1 page, with spaces and newlines",
            "input": "1" * (max_len-10) + "\n" + "1" * 9,
            "output": [
                "1" * (max_len-10) + "\n" + "1" * 9,
            ],
        },
        {
            "comment": "2 pages (90 1's, newline, 100 2's)",
            "input": "1" * (max_len-10) + "\n" + "2" * max_len,
            "output": [
                "1" * (max_len-10),
                "2" * max_len,
            ],
        },
        {
            "comment": "2 pages, space and newline (90 1's, space, 3 1's, newline, 100 2's)",
            "input": "1" * (max_len-10) + " 111\n" + "2" * max_len,
            "output": [
                "1" * (max_len-10) + " 111",
                "2" * max_len,
            ],
        },
        {
            "comment": "2 pages, newline and space (80 1's, newline, 9 1's, space, 100 2's)",
            "input": "1" * (max_len - 20) + "\n" + "2" * 9 + " " + "2" * (max_len - 10),
            "output": [
                "1" * (max_len - 20),
                "2" * 9 + " " + "2" * (max_len - 10),
            ],
        },
        {
            "comment": "2 pages, newline too early and space (10 1's, newline, 79 1's, space, 100 2's)",
            "input": "1" * 10 + "\n" + "1" * (max_len-21) + " " + "2" * max_len,
            "output": [
                "1" * 10 + "\n" + "1" * (max_len-21),
                "2" * max_len,
            ],
        },
    ]
    for e in expected:
        actual = utils.paginate(e['input'], max_len=max_len, wrap=False, lookback_max=30)
        assert e['output'] == actual, e['comment']


def test_paginate_wrap():
    max_len = 100
    wrap = "```"
    max_len_wrap = max_len - (2 * len(wrap))
    expected = [
        # --- No whitespace ---
        {
            "comment": "1 page",
            "input": "1" * max_len_wrap,
            "output": [
                wrap_str("1" * max_len_wrap, wrap),
            ],
        },
        {
            "comment": "2 pages",
            "input": "1" * max_len_wrap + "2" * max_len_wrap,
            "output": [
                wrap_str("1" * max_len_wrap, wrap),
                wrap_str("2" * max_len_wrap, wrap),
            ],
        },
        {
            "comment": "2.5 pages",
            "input": "1" * max_len_wrap + "2" * max_len_wrap + "3" * int(max_len_wrap/2),
            "output": [
                wrap_str("1" * max_len_wrap, wrap),
                wrap_str("2" * max_len_wrap, wrap),
                wrap_str("3" * int(max_len_wrap/2), wrap),
            ],
        },
        {
            "comment": "3 pages",
            "input": "1" * max_len_wrap + "2" * max_len_wrap + "3" * max_len_wrap,
            "output": [
                wrap_str("1" * max_len_wrap, wrap),
                wrap_str("2" * max_len_wrap, wrap),
                wrap_str("3" * max_len_wrap, wrap),
            ],
        },
        # --- With spaces ---
        {
            "comment": "1 page, with spaces",
            "input": "1" * (max_len_wrap-10) + " " + "1" * 9,
            "output": [
                wrap_str("1" * (max_len_wrap-10) + " " + "1" * 9, wrap),
            ],
        },
        {
            "comment": "2 pages (90 1's, single space, 91 2's)",
            "input": "1" * (max_len_wrap-10) + " " + "2" * (max_len_wrap-9),
            "output": [
                wrap_str("1" * (max_len_wrap-10), wrap),
                wrap_str("2" * (max_len_wrap-9), wrap),
            ],
        },
        {
            "comment": "2 pages, space too late (100 1's, 10 2's, space, 89 2's)",
            "input": "1" * max_len_wrap + "2" * 10 + " " + "2" * (max_len_wrap-11),
            "output": [
                wrap_str("1" * max_len_wrap, wrap),
                wrap_str("2" * 10 + " " + "2" * (max_len_wrap-11), wrap),
            ],
        },
        {
            "comment": "2 pages, two spaces early enough (80 1's, space, 9 1's, space, 100 2's)",
            "input": "1" * (max_len_wrap-20) + " " + "1" * 9 + " " + "2" * max_len_wrap,
            "output": [
                wrap_str("1" * (max_len_wrap-20) + " " + "1" * 9, wrap),
                wrap_str("2" * max_len_wrap, wrap),
            ],
        },
        # --- With spaces and newlines ---
        {
            "comment": "1 page, with spaces and newlines",
            "input": "1" * (max_len_wrap-10) + "\n" + "1" * 7 + " 1",
            "output": [
                wrap_str("1" * (max_len_wrap-10) + "\n" + "1" * 7 + " 1", wrap),
            ],
        },
        {
            "comment": "2 pages (90 1's, newline, 100 2's)",
            "input": "1" * (max_len_wrap-10) + "\n" + "2" * max_len_wrap,
            "output": [
                wrap_str("1" * (max_len_wrap-10), wrap),
                wrap_str("2" * max_len_wrap, wrap),
            ],
        },
        {
            "comment": "2 pages, space and newline (90 1's, space, 3 1's, newline, 100 2's)",
            "input": "1" * (max_len_wrap-10) + " 111\n" + "2" * max_len_wrap,
            "output": [
                wrap_str("1" * (max_len_wrap-10) + " 111", wrap),
                wrap_str("2" * max_len_wrap, wrap),
            ],
        },
        {
            "comment": "2 pages, newline and space (80 1's, newline, 9 1's, space, 100 2's)",
            "input": "1" * (max_len_wrap-20) + "\n" + "2" * 9 + " " + "2" * (max_len_wrap-10),
            "output": [
                wrap_str("1" * (max_len_wrap-20), wrap),
                wrap_str("2" * 9 + " " + "2" * (max_len_wrap-10), wrap),
            ],
        },
        {
            "comment": "2 pages, newline too early and space (10 1's, newline, 79 1's, space, 100 2's)",
            "input": "1" * 10 + "\n" + "1" * (max_len_wrap-21) + " " + "2" * max_len_wrap,
            "output": [
                wrap_str("1" * 10 + "\n" + "1" * (max_len_wrap-21), wrap),
                wrap_str("2" * max_len_wrap, wrap),
            ],
        },
    ]
    for e in expected:
        actual = utils.paginate(e['input'], max_len=max_len, wrap=wrap, lookback_max=30)
        assert e['output'] == actual, e['comment']


def test_paginate_random_short():
    max_len = 100
    content = generate_words(3*max_len, with_newline=True)
    pages = utils.paginate(content, max_len=max_len, wrap=None)
    print(f'Input length {len(content)}')
    print(f'Got {len(pages)} pages, lengths {[len(p) for p in pages]}')
    # print(f'--- INPUT ---\n{content}\n--- OUTPUT ---\n')
    for p in pages:
        # print(f'- PAGE BEGIN [{len(p)}] -\n{p}\n- PAGE END -')
        assert len(p) <= max_len


def test_paginate_random():
    max_len = 2000
    gen_len = int(max_len + max_len/2)
    # --- With newlines ---
    content = generate_words(gen_len, with_newline=True)
    print(f'No wrap, newlines: input length {len(content)}')
    # No wrapping
    pages = utils.paginate(content, max_len=max_len, wrap=None)
    print(f'Got {len(pages)} pages, lengths {[len(p) for p in pages]}')
    for p in pages:
        assert len(p) <= max_len
    # --- Without newlines ---
    content = generate_words(gen_len, with_newline=False)
    print(f'No wrap, no newlines: input length {len(content)}')
    # No wrapping
    pages = utils.paginate(content, max_len=max_len, wrap=None)
    print(f'Got {len(pages)} pages, lengths {[len(p) for p in pages]}')
    for p in pages:
        assert len(p) <= max_len
    # --- Without whitespace ---
    content = generate_words(gen_len, no_whitespace=True)
    print(f'No wrap, no whitespace: input length {len(content)}')
    # No wrapping
    pages = utils.paginate(content, max_len=max_len, wrap=None)
    print(f'Got {len(pages)} pages, lengths {[len(p) for p in pages]}')
    for p in pages:
        assert len(p) <= max_len


def test_paginate_header():
    max_len = 100
    wrap = "```"
    header = "- Test header"
    add_header = lambda s: f'{header}\n{s}'
    # remove two wrap lengths, header length and one more for the inserted newline
    max_len_real = max_len - (2 * len(wrap)) - len(header) - 1
    expected = [
        # --- No whitespace ---
        {
            "comment": "1 page",
            "input": "1" * max_len_real,
            "output": [
                wrap_str(add_header("1" * max_len_real), wrap),
            ],
        },
        {
            "comment": "2 pages",
            "input": "1" * max_len_real + "2" * max_len_real,
            "output": [
                wrap_str(add_header("1" * max_len_real), wrap),
                wrap_str(add_header("2" * max_len_real), wrap),
            ],
        },
        {
            "comment": "2.5 pages",
            "input": "1" * max_len_real + "2" * max_len_real + "3" * int(max_len_real/2),
            "output": [
                wrap_str(add_header("1" * max_len_real), wrap),
                wrap_str(add_header("2" * max_len_real), wrap),
                wrap_str(add_header("3" * int(max_len_real/2)), wrap),
            ],
        },
    ]
    for e in expected:
        actual = utils.paginate(e['input'], max_len=max_len, wrap=wrap, lookback_max=30, header=header)
        assert e['output'] == actual, e['comment']


def test_human_seconds():
    expected = [
        dict(
            args=dict(
                seconds=10,
                num_units=1,
                precision=0,
            ),
            output='10s',
        ),
        dict(
            args=dict(
                seconds=10.5,
                num_units=1,
                precision=0,
            ),
            output='10s',
        ),
        dict(
            args=dict(
                seconds=10.5,
                num_units=1,
                precision=1,
            ),
            output='10.5s',
        ),
        dict(
            args=dict(
                seconds=69.42,
                num_units=2,
                precision=0,
            ),
            output='1m9s',
        ),
        dict(
            args=dict(
                seconds=69.42,
                num_units=2,
                precision=1,
            ),
            output='1m9.4s',
        ),
        dict(
            args=dict(
                seconds=69.42,
                num_units=2,
                precision=2,
            ),
            output='1m9.42s',
        ),
        dict(
            args=dict(
                seconds=354.9876 / 1000,
                num_units=2,
                precision=0,
            ),
            output='354ms987us',
        ),
    ]
    fmt_args = "human_seconds(seconds={seconds}, num_units={num_units}, precision={precision})"
    for e in expected:
        actual = utils.human_seconds(**e['args'])
        assert actual == e['output'], fmt_args.format(**e['args'])


# Setup some data for benchmarks
BENCH_WORDS = generate_words(max_length=20000, with_newline=True, no_whitespace=False)


@pytest.mark.skip
def test_benchmark_paginate(benchmark):
    benchmark(utils.paginate, content=BENCH_WORDS, max_len=2000)


@pytest.mark.skip
def test_benchmark_old_split_spaces(benchmark):
    def old_split_spaces(in_str):
        pages = []
        ret_str = "```py\n"
        for word in in_str.split(" "):
            tmp = word + " "
            if len(ret_str) + len(tmp) > 1950:
                pages.append(ret_str + "\n```")
                ret_str = "```py\n"
            ret_str += tmp
        pages.append(f'{ret_str}\n```')
        return pages
    benchmark(old_split_spaces, in_str=BENCH_WORDS)
