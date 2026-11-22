#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
极简 .xls（OLE2 / BIFF8）读取器 —— 仅依赖标准库。

为什么需要它：纽约联储的 ACM 期限溢价数据（ACMTermPremium.xls）只有 .xls 一种格式，
不在 FRED 上，而本看板坚持零第三方依赖（不引入 pandas / xlrd）。

只实现读表格单元格所必需的部分：
  OLE2：Header → DIFAT → FAT → Directory → 找到 "Workbook" 流（含 mini stream 兜底）
  BIFF8：BOUNDSHEET（定位工作表）、SST+CONTINUE（共享字符串）、
         LABELSST / NUMBER / RK / MULRK / FORMULA（单元格）
不支持：写、加密、格式、公式计算（FORMULA 只取 Excel 缓存的结果值）。

用法：
  from xls_lite import read_sheet
  rows = read_sheet(path, "ACM Daily")   # -> [[cell, cell, ...], ...]，cell 为 str / float / None
"""
import struct

# ---------------------------------------------------------------------------
# 一、OLE2 复合文档
# ---------------------------------------------------------------------------
_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FREESECT = 0xFFFFFFFF
_ENDOFCHAIN = 0xFFFFFFFE


class _Ole2:
    def __init__(self, blob):
        if blob[:8] != _MAGIC:
            raise ValueError("不是 OLE2 复合文档")
        self.blob = blob
        self.ssz = 1 << struct.unpack_from("<H", blob, 30)[0]      # 扇区大小
        self.mssz = 1 << struct.unpack_from("<H", blob, 32)[0]     # 迷你扇区大小
        self.n_fat = struct.unpack_from("<I", blob, 44)[0]
        self.dir_start = struct.unpack_from("<I", blob, 48)[0]
        self.cutoff = struct.unpack_from("<I", blob, 56)[0]
        self.minifat_start = struct.unpack_from("<I", blob, 60)[0]
        self.n_minifat = struct.unpack_from("<I", blob, 64)[0]
        self.difat_start = struct.unpack_from("<I", blob, 68)[0]
        self.n_difat = struct.unpack_from("<I", blob, 72)[0]
        self.difat = list(struct.unpack_from("<109I", blob, 76))
        self._load_difat()
        self._load_fat()
        self.entries = self._load_dir()
        self._mini_stream = None
        self._minifat = None

    # -- 扇区读写 --
    def _sector(self, sid):
        off = 512 + sid * self.ssz
        return self.blob[off:off + self.ssz]

    def _load_difat(self):
        """DIFAT：FAT 所在扇区的清单。前 109 项在头里，超出部分串成链。"""
        if not self.n_difat:
            return
        sid = self.difat_start
        per = self.ssz // 4 - 1
        for _ in range(self.n_difat):
            if sid >= _ENDOFCHAIN:
                break
            vals = struct.unpack_from("<%dI" % (per + 1), self._sector(sid))
            self.difat.extend(v for v in vals[:per] if v < _ENDOFCHAIN)
            sid = vals[per]
        self.difat = self.difat[:self.n_fat] if self.n_fat else self.difat

    def _load_fat(self):
        fat = []
        for sid in self.difat:
            if sid >= _ENDOFCHAIN:
                continue
            fat.extend(struct.unpack_from("<%dI" % (self.ssz // 4), self._sector(sid)))
        self.fat = fat

    def _chain(self, start, fat):
        out, sid, guard = [], start, 0
        while sid < _ENDOFCHAIN and guard < 1_000_000:
            out.append(sid)
            sid = fat[sid] if sid < len(fat) else _ENDOFCHAIN
            guard += 1
        return out

    def _read_regular(self, start, size):
        chunks = [self._sector(s) for s in self._chain(start, self.fat)]
        return b"".join(chunks)[:size]

    def _load_dir(self):
        raw = b"".join(self._sector(s) for s in self._chain(self.dir_start, self.fat))
        out = []
        for i in range(len(raw) // 128):
            e = raw[i * 128:(i + 1) * 128]
            nlen = struct.unpack_from("<H", e, 64)[0]
            name = e[:max(0, nlen - 2)].decode("utf-16-le", "ignore")
            out.append({
                "name": name,
                "type": e[66],
                "start": struct.unpack_from("<I", e, 116)[0],
                "size": struct.unpack_from("<Q", e, 120)[0],
            })
        return out

    def _load_mini(self):
        root = next((e for e in self.entries if e["type"] == 5), None)
        if not root:
            return
        self._mini_stream = self._read_regular(root["start"], root["size"])
        if self.n_minifat:
            raw = b"".join(self._sector(s) for s in self._chain(self.minifat_start, self.fat))
            self._minifat = list(struct.unpack_from("<%dI" % (len(raw) // 4), raw))

    def stream(self, name):
        e = next((x for x in self.entries if x["type"] == 2 and x["name"] == name), None)
        if e is None:
            raise KeyError(f"找不到流 {name}")
        if e["size"] < self.cutoff:
            if self._mini_stream is None:
                self._load_mini()
            out, sid, guard = [], e["start"], 0
            while sid < _ENDOFCHAIN and guard < 1_000_000:
                off = sid * self.mssz
                out.append(self._mini_stream[off:off + self.mssz])
                sid = self._minifat[sid]
                guard += 1
            return b"".join(out)[:e["size"]]
        return self._read_regular(e["start"], e["size"])


# ---------------------------------------------------------------------------
# 二、BIFF8 记录解析
# ---------------------------------------------------------------------------
_R_BOF = 0x0809
_R_EOF = 0x000A
_R_BOUNDSHEET = 0x0085
_R_SST = 0x00FC
_R_CONTINUE = 0x003C
_R_LABELSST = 0x00FD
_R_LABEL = 0x0204
_R_NUMBER = 0x0203
_R_RK = 0x027E
_R_MULRK = 0x00BD
_R_FORMULA = 0x0006
_R_BOOLERR = 0x0205


def _records(buf, start=0, stop=None):
    """按偏移依次产出 (偏移, 类型, 数据)。"""
    pos = start
    end = len(buf) if stop is None else stop
    while pos + 4 <= end:
        rtype, rlen = struct.unpack_from("<HH", buf, pos)
        data = buf[pos + 4:pos + 4 + rlen]
        yield pos, rtype, data
        pos += 4 + rlen


class _ChunkReader:
    """把 SST 主记录与后续 CONTINUE 记录当成一条连续字节流读，
    但记住每段边界——字符串可能被切在段中间，续段开头会多一个"字符宽度标志"字节。"""

    def __init__(self, chunks):
        self.chunks = chunks
        self.i = 0
        self.p = 0

    def _advance(self):
        """跳过已读完的段（结构字段用，不消费续段标志字节）。"""
        while self.i < len(self.chunks) and self.p >= len(self.chunks[self.i]):
            self.i += 1
            self.p = 0

    def eof(self):
        self._advance()
        return self.i >= len(self.chunks)

    def u8(self):
        self._advance()
        v = self.chunks[self.i][self.p]
        self.p += 1
        return v

    def u16(self):
        return struct.unpack("<H", self.raw(2))[0]

    def u32(self):
        return struct.unpack("<I", self.raw(4))[0]

    def raw(self, n):
        out = b""
        while n > 0:
            self._advance()
            if self.i >= len(self.chunks):
                break
            c = self.chunks[self.i]
            take = min(n, len(c) - self.p)
            out += c[self.p:self.p + take]
            self.p += take
            n -= take
        return out

    def chars(self, cch, high):
        """读 cch 个字符（可能跨段）。跨段时续段首字节为新的宽度标志。"""
        out = []
        left = cch
        while left > 0 and self.i < len(self.chunks):
            c = self.chunks[self.i]
            if self.p >= len(c):
                # 字符数据被切段：下一段首字节是宽度标志
                self.i += 1
                if self.i >= len(self.chunks):
                    break
                high = bool(self.chunks[self.i][0] & 0x01)
                self.p = 1
                continue
            width = 2 if high else 1
            avail = (len(c) - self.p) // width
            if avail <= 0:      # 段尾只剩半字符
                self.i += 1
                self.p = 0
                continue
            take = min(left, avail)
            out.append(c[self.p:self.p + take * width].decode(
                "utf-16-le" if high else "latin-1", "ignore"))
            self.p += take * width
            left -= take
        return "".join(out)


def _parse_sst(chunks):
    """解析共享字符串表，chunks[0] 为 SST 数据，后续为 CONTINUE 数据。"""
    cr = _ChunkReader(chunks)
    cr.raw(8)                       # 跳过 total / unique 计数
    unique = struct.unpack_from("<I", chunks[0], 4)[0]
    strings = []
    for _ in range(unique):
        if cr.eof():
            break
        cch = cr.u16()
        flags = cr.u8()
        high = bool(flags & 0x01)
        ext = bool(flags & 0x04)
        rich = bool(flags & 0x08)
        runs = cr.u16() if rich else 0
        cb_ext = cr.u32() if ext else 0
        strings.append(cr.chars(cch, high))
        if runs:
            cr.raw(4 * runs)
        if cb_ext:
            cr.raw(cb_ext)
    return strings


def _rk_to_float(rk):
    """RK 值：末两位是标志位（bit0 除 100、bit1 整数），其余 30 位是尾数。"""
    if rk & 0x02:
        v = float(rk >> 2) if not rk & 0x80000000 else float((rk >> 2) - 0x40000000)
    else:
        v = struct.unpack("<d", struct.pack("<Q", (rk & 0xFFFFFFFC) << 32))[0]
    return v / 100 if rk & 0x01 else v


def read_sheet(path, sheet_name):
    with open(path, "rb") as f:
        blob = f.read()
    ole = _Ole2(blob)
    wb = ole.stream("Workbook") if any(e["name"] == "Workbook" for e in ole.entries) else ole.stream("Book")

    # 1. 全局区：BOUNDSHEET 定位 + SST 共享字符串
    sheets, sst = [], []
    for pos, rtype, data in _records(wb):
        if rtype == _R_BOUNDSHEET:
            lb = struct.unpack_from("<I", data, 0)[0]
            nlen = data[6]
            high = data[7] & 0x01
            name = data[8:8 + nlen * (2 if high else 1)].decode(
                "utf-16-le" if high else "latin-1", "ignore")
            sheets.append({"name": name, "offset": lb})
        elif rtype == _R_SST:
            chunks = [data]
            # 紧跟在后面的 CONTINUE 记录属于同一张表
            for p2, t2, d2 in _records(wb, pos + 4 + len(data)):
                if t2 != _R_CONTINUE:
                    break
                chunks.append(d2)
            sst = _parse_sst(chunks)
            break

    target = next((s for s in sheets if s["name"].strip() == sheet_name.strip()), None)
    if target is None:
        raise KeyError(f"工作表 {sheet_name} 不存在，可选：{[s['name'] for s in sheets]}")

    # 2. 目标工作表区间：从它的 BOF 到下一个工作表 BOF（或文件末尾）
    starts = sorted(s["offset"] for s in sheets)
    nxt = next((o for o in starts if o > target["offset"]), None)

    # 3. 读单元格
    rows = {}
    for pos, rtype, data in _records(wb, target["offset"], nxt):
        if rtype == _R_EOF:
            break
        if rtype == _R_LABELSST:
            r, c, _xf, isst = struct.unpack_from("<HHHI", data, 0)
            v = sst[isst] if isst < len(sst) else None
        elif rtype == _R_LABEL:
            r, c = struct.unpack_from("<HH", data, 0)
            cch = struct.unpack_from("<H", data, 6)[0]
            flags = data[8]
            off = 9
            if flags & 0x08:
                off += 2
            if flags & 0x04:
                off += 4
            v = data[off:off + cch * (2 if flags & 0x01 else 1)].decode(
                "utf-16-le" if flags & 0x01 else "latin-1", "ignore")
        elif rtype == _R_NUMBER:
            r, c, _xf = struct.unpack_from("<HHH", data, 0)
            v = struct.unpack_from("<d", data, 6)[0]
        elif rtype == _R_RK:
            r, c, _xf, rk = struct.unpack_from("<HHHI", data, 0)
            v = _rk_to_float(rk)
        elif rtype == _R_MULRK:
            r, c0 = struct.unpack_from("<HH", data, 0)
            n = (len(data) - 6) // 6
            for k in range(n):
                _xf, rk = struct.unpack_from("<HI", data, 4 + k * 6)
                rows.setdefault(r, {})[c0 + k] = _rk_to_float(rk)
            continue
        elif rtype == _R_FORMULA:
            r, c, _xf = struct.unpack_from("<HHH", data, 0)
            res = data[6:14]
            if res[6:8] == b"\xff\xff":
                # 字符串/布尔/错误：布尔与错误可读，字符串结果取不到（本数据源用不到）
                if res[0] == 0x01:
                    v = float(res[2])
                else:
                    continue
            else:
                v = struct.unpack("<d", res)[0]
        elif rtype == _R_BOOLERR:
            r, c, _xf, val, iserr = struct.unpack_from("<HHHBB", data, 0)
            v = None if iserr else float(val)
        else:
            continue
        rows.setdefault(r, {})[c] = v

    if not rows:
        return []
    max_r, max_c = max(rows), max(max(d) for d in rows.values())
    out = []
    for r in range(max_r + 1):
        row = rows.get(r, {})
        out.append([row.get(c) for c in range(max_c + 1)])
    return out


if __name__ == "__main__":
    import sys
    path = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "ACM Daily"
    data = read_sheet(path, name)
    print(f"行数 {len(data)}，列数 {len(data[0]) if data else 0}")
    for row in data[:4]:
        print(row)
    print("...")
    for row in data[-2:]:
        print(row)
