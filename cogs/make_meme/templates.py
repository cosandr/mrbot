import json
import os
from typing import Dict

from ext import utils
from .errors import MemeTemplateError
from .meme import MemeTemplate


class AllMemeTemplates:
    """Holds all meme templates"""

    def __init__(self):
        self._memes: Dict[str, MemeTemplate] = {}
        self._meme_dir = MemeTemplate.meme_dir
        self._read_all()

    def __getitem__(self, key: str):
        """Returns the closest match to `key`"""
        if not isinstance(key, str):
            raise KeyError
        if key in self._memes:
            return self._memes[key]
        meant = utils.find_similar_str(key, list(self._memes))
        if not meant:
            raise KeyError
        return self._memes[meant[0]]

    def __len__(self):
        return len(self._memes)

    def to_list(self):
        return list(self._memes)

    def _read_all(self) -> None:
        """Open and read all json files, raises BadTemplateInfo"""
        for file in os.listdir(self._meme_dir):
            if file.endswith('.json'):
                try:
                    with open(os.path.join(self._meme_dir, file), 'r', encoding='utf-8') as fr:
                        meme = MemeTemplate(json.load(fr))
                        self._memes[meme.name] = meme
                except Exception as e:
                    raise MemeTemplateError(str(e))
