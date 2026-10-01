from pathlib import Path
from .format import TwentyTwoCKReader as TwentyTwoCKReaderV2, build_22ck
from .runtime_v3 import TwentyTwoCKReaderV3, build_22ck_streaming_v3


class TwentyTwoCKReader:
    """Version-dispatched reader; existing V1/V2 artifacts remain compatible."""
    def __new__(cls, path):
        with Path(path).open('rb') as stream:
            magic = stream.read(8)
        if magic == b'22CKV003':
            return TwentyTwoCKReaderV3(path)
        return TwentyTwoCKReaderV2(path)

__all__ = ["TwentyTwoCKReader", "TwentyTwoCKReaderV3", "build_22ck", "build_22ck_streaming_v2", "build_22ck_streaming_v3"]
from wiki22.knowledge.compact22.streaming_v2 import build_22ck_streaming_v2
