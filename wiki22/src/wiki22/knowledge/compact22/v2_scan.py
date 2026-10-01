"""Read canonical V2 sections incrementally for lossless V3 migration."""
import io
import json
import mmap
from pathlib import Path
from .format import HEADER


def json_rows(path,offset):
    decoder=json.JSONDecoder()
    with Path(path).open('rb') as raw:
        h=HEADER.unpack(raw.read(HEADER.size));remaining=h[6]+h[7]-offset
        raw.seek(offset)
        class Limited(io.RawIOBase):
            def readable(self):return True
            def readinto(self,b):
                nonlocal remaining
                data=raw.read(min(len(b),remaining));b[:len(data)]=data;remaining-=len(data);return len(data)
        stream=io.TextIOWrapper(io.BufferedReader(Limited()),encoding='utf-8');buf='';pos=0
        while True:
            if len(buf)-pos<65536:buf=buf[pos:]+stream.read(65536);pos=0
            while pos<len(buf) and buf[pos] in ' \r\n\t,':pos+=1
            if pos<len(buf) and buf[pos]==']':return
            try:value,end=decoder.raw_decode(buf,pos)
            except json.JSONDecodeError:
                more=stream.read(65536)
                if not more:raise
                buf=buf[pos:]+more;pos=0;continue
            yield value;pos=end


def layout(path):
    with Path(path).open('rb') as f:
        h=HEADER.unpack(f.read(HEADER.size))
        if h[:2]!=(b'22CKV001',1):raise ValueError('expected canonical V2 staging container')
        with mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) as m:
            def find(pattern,start):
                for pos in range(start,h[6]+h[7],1024*1024):
                    found=m.find(pattern,pos,min(pos+1024*1024+len(pattern),h[6]+h[7]))
                    m.madvise(mmap.MADV_DONTNEED) if hasattr(m, 'madvise') else None
                    if found>=0:return found
                raise ValueError('missing V2 metadata section')
            evidence=find(b'],"evidence":[',h[6])+len(b'],"evidence":[')
            end=find(b'],"format_version":',evidence)
            start=find(b'"manifest":',end)+len(b'"manifest":')
            manifest,_=json.JSONDecoder().raw_decode(m[start:min(start+65536,h[6]+h[7])].decode('utf-8',errors='ignore'))
        return h,h[6]+len(b'{"articles":['),evidence,manifest
