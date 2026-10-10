"""Small recordings for the tests that open one: an Oxysoft export, a CSV, and a TDT block whose tank reader is replaced by a fake (so the
TDT is only readable by an engine that runs in this process — PYAT_ENGINE=inprocess)."""

import datetime
import json
import os
import sys
import types
import zlib
from unittest import mock

import numpy as np
import tdt

TAB, NL = chr(9), chr(10)


def write_oxysoft(path, n=600):
    lines = [f"Datafile sample rate{TAB}10 Hz", "Legend:", f"1{TAB}sample number", f"2{TAB}Rx1 - Tx1 O2Hb (f)", f"3{TAB}Rx1 - Tx1 HHb (f)",
             TAB.join("123"), TAB.join("000")]
    rng = np.random.default_rng(1)
    for i in range(1, n + 1):
        v = np.round(rng.normal(0, 1, 2) + np.sin(i / 20.0), 6)
        lines.append(TAB.join([str(i)] + [str(x) for x in v]))
    with open(path, "w") as f:
        f.write(NL.join(lines) + NL)


def write_csv(path, n=200, fs=10.0):
    rng = np.random.default_rng(2)
    lines = ["time,left,right"]
    for i in range(n):
        lines.append(f"{i / fs:.3f},{np.sin(i / 20.0) + rng.normal(0, 0.1):.5f},{np.cos(i / 20.0) + rng.normal(0, 0.1):.5f}")
    with open(path, "w") as f:
        f.write(NL.join(lines) + NL)


def fake_block(n=20_000, fs=1000.0, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fs
    base = 60 + 30 * np.exp(-t / 8)
    f415 = (0.5 * base + rng.normal(0, 0.1, n)).astype(np.float32)
    f465 = (base * (1 + 0.1 * np.exp(-0.5 * ((t - 9) / 0.5) ** 2)) + rng.normal(0, 0.1, n)).astype(np.float32)
    heads = tdt.StructType()
    heads.stores = {"L1P_": types.SimpleNamespace(type_str="epocs", name="L1P/"), "x465A": types.SimpleNamespace(type_str="streams", name="x465A")}
    data = tdt.StructType()
    data.streams = {"x465A": types.SimpleNamespace(data=f465, fs=fs), "x415A": types.SimpleNamespace(data=f415, fs=fs)}
    data.scalars = tdt.StructType()
    data.epocs = tdt.StructType()
    data.info = types.SimpleNamespace(duration=datetime.timedelta(seconds=n / fs), blockname="Rat7-250101-101010",
                                      start_date=datetime.datetime(2025, 1, 1, 10, 10, 10))

    def read_block(path, headers=None, evtype=None, store=None, verbose=None):
        if isinstance(headers, int) and headers == 1:
            return heads
        if store is not None:
            block = tdt.StructType()
            block.epocs = tdt.StructType()
            block.epocs["L1P_"] = types.SimpleNamespace(name="L1P", onset=np.array([4.0, 9.0, 14.0]), offset=np.array([4.5, 9.5, 14.5]))
            return block
        return data

    return read_block


def patch_tdt_reader():
    """Starts replacing the tank reader with the fake; returns the patcher (stop() it, or addCleanup(patcher.stop))."""
    patcher = mock.patch.object(tdt, "read_block", fake_block())
    patcher.start()
    return patcher


def make_tdt_folder(parent, name):
    path = os.path.join(parent, name)
    os.makedirs(path)
    with open(os.path.join(path, name + ".Tbk"), "wb") as f:
        f.write(b"block " + name.encode())
    return path


# ---------------------------------------------------------------------------------------------
# a text field study, with a stand-in for sentence-transformers (no torch, no download)
# ---------------------------------------------------------------------------------------------

class StubModel:
    """Deterministic bag-of-hashed-words embeddings, L2-normalised."""

    def __init__(self, name):
        self.name = name

    def encode(self, texts, normalize_embeddings=True):
        out = np.zeros((len(texts), 24))
        for i, text in enumerate(texts):
            for word in str(text).lower().split():
                out[i, zlib.crc32(word.encode()) % 24] += 1.0
        if normalize_embeddings:
            out /= np.maximum(np.linalg.norm(out, axis=1, keepdims=True), 1e-9)
        return out


def write_study(folder, n=14, seed=7):
    rng = np.random.default_rng(seed)
    vocab = "apple river stone cloud bright quiet garden window paper engine silver forest morning".split()
    for i in range(n):
        subject = {"participant_id": f"P{i:02d}"}
        core = list(rng.choice(vocab, 4))                         # shared within a subject, so the pairs correlate
        for q in ("q1", "q2", "q3"):
            subject[q] = " ".join(core + list(rng.choice(vocab, rng.integers(3, 9))))
        with open(os.path.join(folder, f"P-{i:02d}.json"), "w", encoding="utf-8") as fh:
            json.dump(subject, fh)


def patch_embedding_model():
    """Starts replacing sentence-transformers with the stub; returns the patcher."""
    patcher = mock.patch.dict(sys.modules, {"sentence_transformers": types.SimpleNamespace(SentenceTransformer=StubModel)})
    patcher.start()
    return patcher
