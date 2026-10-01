"""Lazy SHA-256 record proofs for READ001; no whole-index scan on a question.

A catalog-pinned Merkle root authenticates each SQLite row, including article,
revision, raw source digest and display instructions. SQLite remains a lookup
accelerator; neither its contents nor a cached answer authorizes a claim.
"""
import hashlib
from pathlib import Path
import struct

MAGIC=b'22READM1'
HEADER=struct.Struct('<8sQQ')
MAX_ROWS=1000000

def stamp(path):
    s=path.stat();return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns

def leaf(canonical_sha256,aid,revision,raw_sha,body):
    if type(aid) is not int or type(revision) is not int or aid<=0 or revision<=0 or len(raw_sha)!=32 or len(body)>65536:
        raise ValueError('Invalid authenticated reading row')
    return hashlib.sha256(b'READ001-LEAF\0'+bytes.fromhex(canonical_sha256)+struct.pack('<QQI',aid,revision,len(body))+raw_sha+body).digest()

def branch(left,right):return hashlib.sha256(b'READ001-NODE\0'+left+right).digest()

def empty(canonical_sha256):return hashlib.sha256(b'READ001-EMPTY\0'+bytes.fromhex(canonical_sha256)).digest()

class RecordProof:
    def __init__(self,path,*,root,rows,capacity,canonical_sha256):
        self.path=Path(path).resolve();self.initial_stamp=stamp(self.path);self.stream=None
        if type(rows) is not int or not 1<=rows<=MAX_ROWS or type(capacity) is not int or capacity&(capacity-1) or not rows<=capacity<2*max(2,rows):
            raise ValueError('Invalid proof bounds')
        self.root=bytes.fromhex(root)
        if len(self.root)!=32:raise ValueError('Invalid proof root')
        self.rows=rows;self.capacity=capacity;self.canonical_sha256=canonical_sha256
        if self.path.stat().st_size!=HEADER.size+capacity*64:raise ValueError('Invalid proof file length')
        try:
            self.stream=self.path.open('rb')
            if HEADER.unpack(self.stream.read(HEADER.size))!=(MAGIC,capacity,rows):raise ValueError('Proof header mismatch')
            if self.node(1)!=self.root:raise ValueError('Proof root mismatch')
            self.unchanged()
        except BaseException:self.close();raise

    def unchanged(self):
        if stamp(self.path)!=self.initial_stamp:raise ValueError('Reading proof changed: reopen library')

    def node(self,index):
        if not 1<=index<2*self.capacity:raise ValueError('Proof node outside tree')
        self.stream.seek(HEADER.size+index*32);value=self.stream.read(32)
        if len(value)!=32:raise ValueError('Truncated reading proof')
        return value

    def verify(self,position,aid,revision,raw_sha,body):
        self.unchanged()
        if type(position) is not int or not 0<=position<self.rows:raise ValueError('Reading position outside authenticated set')
        index=self.capacity+position;value=leaf(self.canonical_sha256,aid,revision,raw_sha,body)
        while index>1:
            sibling=self.node(index^1)
            value=branch(sibling,value) if index&1 else branch(value,sibling)
            index//=2
        if value!=self.root:raise ValueError('Reading source proof failed')
        self.unchanged();return True

    def close(self):
        if self.stream is not None:self.stream.close();self.stream=None
