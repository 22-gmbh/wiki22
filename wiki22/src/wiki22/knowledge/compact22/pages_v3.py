"""22CK V3 independently verified, bounded-cache table pages."""
from __future__ import annotations
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import struct
import threading
import zlib

MAGIC = b'22CKV003'
HEADER = struct.Struct('<8sQQ32s')
ENTRY = struct.Struct('<QII32s')
U32 = struct.Struct('<I')
PAGE_ROWS = 64
DATA_PAGE = 65536


class TableWriter:
    def __init__(self, directory, name, rows=PAGE_ROWS, compress=False):
        self.path = Path(directory)/name
        self.out = self.path.open('wb')
        self.directory_path = Path(directory)/(name+'.dir')
        self.index = self.directory_path.open('wb')
        self.rows_per_page = rows; self.compress = compress
        self.pending = []; self.count = 0; self.pages = 0

    def add(self, record):
        self.pending.append(bytes(record)); self.count += 1
        if len(self.pending) == self.rows_per_page: self.flush()

    def flush(self):
        if not self.pending: return
        offsets = bytearray(); payload = bytearray()
        for record in self.pending:
            offsets += U32.pack(len(payload)); payload += record
        offsets += U32.pack(len(payload))
        raw = U32.pack(len(self.pending)) + offsets + payload
        stored = b'\0' + raw
        if self.compress:
            zipped = zlib.compress(raw, 6)
            if len(zipped) < len(raw): stored = b'\1' + zipped
        self.index.write(ENTRY.pack(self.out.tell(),len(stored),len(raw),hashlib.sha256(stored).digest()))
        self.out.write(stored); self.pages += 1; self.pending.clear()

    def finish(self):
        self.flush(); self.out.close(); self.index.close()
        return {'path':self.path, 'directory_path':self.directory_path,
                'count':self.count, 'pages':self.pages, 'rows':self.rows_per_page}


def assemble(output, tables, manifest):
    output = Path(output); temporary = output.with_suffix('.building')
    root = {'schema':'22ck.root.v3','manifest':manifest,'tables':{}}
    with temporary.open('wb') as out:
        out.write(bytes(HEADER.size))
        for name, table in tables.items():
            descriptor = {k:table[k] for k in ('count','pages','rows')}
            for kind, pathkey in [('payload','path'),('directory','directory_path')]:
                descriptor[kind+'_offset'] = out.tell()
                descriptor[kind+'_bytes'] = table[pathkey].stat().st_size
                digest = hashlib.sha256()
                with table[pathkey].open('rb') as source:
                    for block in iter(lambda:source.read(1024*1024),b''):
                        out.write(block); digest.update(block)
                if kind == 'directory': descriptor['directory_sha256'] = digest.hexdigest()
            root['tables'][name] = descriptor
        root_offset = out.tell()
        raw = json.dumps(root,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        out.write(raw)
        out.seek(0); out.write(HEADER.pack(MAGIC,root_offset,len(raw),hashlib.sha256(raw).digest()))
        out.flush(); os.fsync(out.fileno())
    digest = hashlib.sha256()
    with temporary.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''): digest.update(block)
    with temporary.open('ab') as out: out.write(digest.digest())
    os.replace(temporary,output)
    return root


class PageStore:
    def __init__(self,path,cache_bytes=16*1024*1024):
        self.path = Path(path); self.file = self.path.open('rb'); self.read_lock = threading.RLock()
        self.length = self.path.stat().st_size
        raw = self.file.read(HEADER.size)
        if len(raw)!=HEADER.size: raise ValueError('truncated 22CK header')
        magic,offset,length,digest = HEADER.unpack(raw)
        if magic!=MAGIC or length>4*1024*1024 or offset<HEADER.size or offset+length+32!=self.length:
            raise ValueError('invalid 22CK V3 root bounds')
        raw = self.read(offset,length)
        if hashlib.sha256(raw).digest()!=digest: raise ValueError('22CK root integrity failure')
        self.root = json.loads(raw)
        self.tables = self.root['tables']; self.cache = OrderedDict(); self.cache_size = 0
        self.cache_limit = cache_bytes; self.directories = {}; self.bytes_read = HEADER.size+length
        for t in self.tables.values():
            for kind in ('payload','directory'):
                if t[kind+'_offset']<HEADER.size or t[kind+'_offset']+t[kind+'_bytes']>offset:
                    raise ValueError('22CK table bounds')
            if t['directory_bytes']!=t['pages']*ENTRY.size or t['pages']!=(t['count']+t['rows']-1)//t['rows']:
                raise ValueError('22CK table shape')

    def read(self,offset,length):
        if callable(getattr(os, 'pread', None)):
            data = os.pread(self.file.fileno(),length,offset)
        else:  # Windows has no pread; serialize seek/read on the shared file.
            with self.read_lock:
                self.file.seek(offset)
                data = self.file.read(length)
        if len(data)!=length: raise ValueError('truncated 22CK page')
        if hasattr(self,'bytes_read'): self.bytes_read += length
        return data

    def page(self,name,number):
        key = (name,number)
        if key in self.cache:
            self.cache.move_to_end(key); return self.cache[key]
        t = self.tables[name]
        if not 0<=number<t['pages']: raise IndexError(number)
        if name not in self.directories:
            raw = self.read(t['directory_offset'],t['directory_bytes'])
            if hashlib.sha256(raw).hexdigest()!=t['directory_sha256']: raise ValueError('22CK directory integrity failure')
            self.directories[name] = raw
        offset,length,decoded_length,digest = ENTRY.unpack_from(self.directories[name],number*ENTRY.size)
        if offset+length>t['payload_bytes'] or decoded_length>64*1024*1024:
            raise ValueError('22CK page bounds')
        stored = self.read(t['payload_offset']+offset,length)
        if hashlib.sha256(stored).digest()!=digest: raise ValueError('22CK page integrity failure')
        if stored[0]==0: raw=stored[1:]
        elif stored[0]==1:
            d=zlib.decompressobj();raw=d.decompress(stored[1:],decoded_length+1)
            if not d.eof or d.unused_data or d.unconsumed_tail: raise ValueError('invalid 22CK compressed page')
        else: raise ValueError('unknown 22CK page codec')
        if len(raw)!=decoded_length: raise ValueError('22CK decoded page length')
        while self.cache and self.cache_size+len(raw)>self.cache_limit:
            _,previous=self.cache.popitem(last=False);self.cache_size-=len(previous)
        if len(raw)<=self.cache_limit:
            self.cache[key]=raw;self.cache_size+=len(raw)
        return raw

    def record(self,name,ordinal):
        t=self.tables[name]
        if not 0<=ordinal<t['count']: raise IndexError(ordinal)
        page=self.page(name,ordinal//t['rows']);local=ordinal%t['rows']
        count=U32.unpack_from(page)[0]
        if count>t['rows'] or local>=count: raise ValueError('22CK record count')
        base=4+4*(count+1)
        start=U32.unpack_from(page,4+4*local)[0];end=U32.unpack_from(page,8+4*local)[0]
        if start>end or base+end>len(page): raise ValueError('22CK record bounds')
        return page[base+start:base+end]

    def data(self,offset,length):
        result=bytearray()
        while length:
            page=self.record('data',offset//DATA_PAGE);start=offset%DATA_PAGE
            take=min(length,len(page)-start)
            if take<=0: raise ValueError('22CK evidence data bounds')
            result+=page[start:start+take];offset+=take;length-=take
        return bytes(result)

    def verify_integrity(self):
        digest=hashlib.sha256();remaining=self.length-32;offset=0
        while remaining:
            block=self.read(offset,min(1024*1024,remaining));digest.update(block);offset+=len(block);remaining-=len(block)
        if digest.digest()!=self.read(self.length-32,32): raise ValueError('22CK container integrity failure')
        for name,t in self.tables.items():
            for page in range(t['pages']): self.page(name,page)
        return True

    def close(self):
        self.file.close();self.cache.clear();self.directories.clear();self.cache_size=0
