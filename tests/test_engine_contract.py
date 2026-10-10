"""What the app needs of the analysis engine (backend/contract.py) against what the engine offers (PyATCLI's own contract, which is tested there):
the app refuses an engine that does not fit, says why, and every operation and table the code relies on is one the installed library provides.

The lists in backend/contract.py are kept equal to what the code does: a window that asks for a new operation fails here until it is added."""

import ast
import os
import types
import unittest
from unittest import mock

from PyATCLI import ops, recording
from PyATCLI.analyses import describe_kinds, describe_outputs

from physicsanalysis_qt.analysis import result_window
from physicsanalysis_qt.backend import BackendError, contract, thread_engine

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "physicsanalysis_qt")

# the helpers that send an engine request, and where in their arguments the operation (or analysis) is named
SENDERS = {"run_engine": 1, "request": 0, "call": 0, "request_analysis": 1, "run_click_analysis": 3}
ANALYSIS_SENDERS = ("request_analysis", "run_click_analysis")        # these ask the `run` operation for an analysis by kind


def calls_into_the_engine():
    """[(sender, name, parameter keys, file)] for every call in the app that names its operation or analysis as a literal; the parameter keys
    are those of a dict written out in the call (empty if there is none)."""
    found = []
    for folder, dirs, files in os.walk(PACKAGE):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                sender = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else None
                at = SENDERS.get(sender)
                if at is None or len(node.args) <= at:
                    continue
                named = node.args[at]
                if not (isinstance(named, ast.Constant) and isinstance(named.value, str)):
                    continue                                                    # (the generic helpers pass it on: run_engine's own `method`)
                keys = set()
                if sender != "run_click_analysis" and len(node.args) > at + 1 and isinstance(node.args[at + 1], ast.Dict):
                    keys = {k.value for k in node.args[at + 1].keys if isinstance(k, ast.Constant)}
                found.append((sender, named.value, keys, os.path.relpath(path, ROOT).replace(os.sep, "/")))
    return found


class TestTheCheckOnTheEnginesHello(unittest.TestCase):
    def ready(self, **changes):
        return {"event": "ready", "protocol": contract.SUPPORTED_PROTOCOLS[0], "library": "9.9", "operations": list(contract.OPERATIONS_USED), **changes}

    def test_an_engine_that_fits_is_used(self):
        self.assertIsNone(contract.check_ready(self.ready()))
        self.assertIsNone(contract.check_ready(self.ready(operations=list(contract.OPERATIONS_USED) + ["something.new"])))      # more is fine

    def test_another_protocol_is_refused_and_says_which(self):
        message, hint = contract.check_ready(self.ready(protocol=99))
        self.assertIn("protocol 99", message)
        self.assertIn("9.9", message)
        self.assertIn("pip install", hint)
        self.assertIsNotNone(contract.check_ready({"event": "ready"}))                              # no protocol at all

    def test_an_engine_without_an_operation_the_app_asks_for_is_refused_and_says_which(self):
        message, _ = contract.check_ready(self.ready(operations=[o for o in contract.OPERATIONS_USED if o != "recording.open"]))
        self.assertIn("recording.open", message)


class TestTheClientRefusesAnEngineThatDoesNotFit(unittest.TestCase):
    def engine(self):
        engine = thread_engine()
        self.addCleanup(engine.shutdown)
        return engine

    def test_a_newer_protocol_fails_every_request_with_the_reason(self):
        with mock.patch.object(ops, "PROTOCOL_VERSION", 99):
            engine = self.engine()
            request = engine.request("kinds", {})
            with self.assertRaises(BackendError) as caught:
                request.result(30)
        error = caught.exception
        self.assertEqual(error.code, "incompatible_engine")
        self.assertIn("protocol 99", str(error))
        with self.assertRaises(BackendError) as again:                                              # and it is not started again for the next one
            engine.request("kinds", {})
        self.assertEqual(again.exception.code, "incompatible_engine")
        with self.assertRaises(BackendError) as waiting:
            engine.wait_ready(5)
        self.assertEqual(waiting.exception.code, "incompatible_engine")

    def test_an_engine_missing_an_operation_is_refused_too(self):
        with mock.patch.object(ops, "names", return_value=["info", "kinds"]):
            engine = self.engine()
            with self.assertRaises(BackendError) as caught:
                engine.request("kinds", {}).result(30)
        self.assertEqual(caught.exception.code, "incompatible_engine")
        self.assertIn("recording.open", str(caught.exception))

    def test_an_engine_that_fits_is_used_as_before(self):
        engine = self.engine()
        self.assertEqual(engine.wait_ready(30)["protocol"], contract.SUPPORTED_PROTOCOLS[0])
        self.assertIn("analyses", engine.call("kinds", {}, timeout=30))


class TestWhatTheAppAsksIsWhatTheEngineOffers(unittest.TestCase):
    def test_the_list_of_operations_is_what_the_code_asks_for(self):
        asked = {name for sender, name, _, _ in calls_into_the_engine() if sender not in ANALYSIS_SENDERS}
        asked.add("run")                                                                              # (every analysis window asks for it by kind)
        self.assertEqual(sorted(asked), sorted(contract.OPERATIONS_USED),
                         "backend/contract.py OPERATIONS_USED is out of step with the operations the app asks for")

    def test_every_operation_the_app_asks_for_exists_and_takes_the_parameters_it_is_given(self):
        offered = ops.describe()
        for sender, name, keys, path in calls_into_the_engine():
            if sender in ANALYSIS_SENDERS:
                continue
            with self.subTest(op=name, file=path):
                self.assertIn(name, offered)
                self.assertLessEqual(keys, {p["name"] for p in offered[name]["parameters"]}, f"{path} sends {name} a parameter it does not take")

    def test_every_analysis_the_app_asks_for_exists_and_takes_the_parameters_it_is_given(self):
        kinds = describe_kinds()
        window = set(result_window.window_parameters(types.SimpleNamespace(plot_signal="normalized"), 1.0, 2.0, 3.0))
        for sender, kind, keys, path in calls_into_the_engine():
            if sender not in ANALYSIS_SENDERS:
                continue
            with self.subTest(kind=kind, file=path):
                self.assertIn(kind, kinds)
                accepted = {p["name"] for p in kinds[kind]["parameters"]}
                self.assertLessEqual(keys | (window if sender == "run_click_analysis" else set()), accepted)

    def test_the_tables_and_columns_the_windows_read_are_ones_the_analysis_says_are_always_there(self):
        kinds = describe_kinds()
        for kind, tables in contract.TABLES_READ.items():
            for table, columns in tables.items():
                with self.subTest(kind=kind, table=table):
                    self.assertIn(table, kinds[kind]["tables"])
                    self.assertLessEqual(set(columns), set(kinds[kind]["tables"][table]), f"{kind}.{table}: the app reads a column the library does not promise")

    def test_the_output_tables_and_columns_the_app_relies_on_are_ones_the_library_declares(self):
        declared = describe_outputs()
        for name, tables in contract.OUTPUTS_READ.items():
            for table, columns in tables.items():
                with self.subTest(output=name, table=table):
                    self.assertIn(name, declared)
                    self.assertIn(table, declared[name]["tables"])
                    self.assertLessEqual(set(columns), set(declared[name]["tables"][table]), f"{name}.{table}: the app relies on a column the library does not promise")

    def test_the_keys_of_an_answer_that_the_app_reads_are_ones_the_operation_promises(self):
        offered = ops.describe()
        for op, keys in contract.RESULTS_READ.items():
            with self.subTest(op=op):
                self.assertIn(op, offered)
                self.assertLessEqual(set(keys), set(offered[op]["result"]), f"{op}: the app reads a key of the answer that the operation does not promise")

    def test_the_keys_of_a_loaded_recording_that_the_app_reads_are_ones_the_library_promises(self):
        promised = recording.CACHE_KEYS
        self.assertLessEqual(set(contract.CACHE_KEYS_READ["always"]), set(promised["always"]))
        for source, keys in contract.CACHE_KEYS_READ.items():
            if source != "always":
                with self.subTest(source=source):
                    self.assertLessEqual(set(keys), set(promised[source]))

    def test_every_key_of_the_recording_the_code_reads_by_name_is_declared(self):
        read = set()
        for folder, dirs, files in os.walk(PACKAGE):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if not name.endswith(".py"):
                    continue
                with open(os.path.join(folder, name), encoding="utf-8") as f:
                    tree = ast.parse(f.read())
                for node in ast.walk(tree):
                    key = receiver = None
                    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                        key, receiver = node.slice.value, node.value
                    elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args
                          and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                        key, receiver = node.args[0].value, node.func.value
                    holder = receiver.attr if isinstance(receiver, ast.Attribute) else receiver.id if isinstance(receiver, ast.Name) else None
                    if key is not None and holder in ("cache", "original_cache", "recorded"):
                        read.add(key)
        declared = set(contract.CACHE_KEYS_READ["always"]) | set(contract.CACHE_KEYS_READ["TDT"]) | set(contract.APP_CACHE_KEYS)
        self.assertTrue(read, "no keys found: the scan needs updating")
        self.assertLessEqual(read, declared, "the app reads a key of the loaded recording that backend/contract.py does not list")

    def test_the_tables_a_window_reads_are_the_ones_declared_for_it(self):
        windows = {"auc.py": "auc_window", "fft.py": "fft_window", "peth.py": "zscore_window", "curve_fit.py": "curve_fit", "intervals.py": "event_intervals"}
        for name, kind in windows.items():
            with open(os.path.join(PACKAGE, "analysis", name), encoding="utf-8") as f:
                tree = ast.parse(f.read())
            read = {node.slice.value for node in ast.walk(tree)
                    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute) and node.value.attr == "tables"
                    and isinstance(node.slice, ast.Constant)}
            with self.subTest(window=name):
                self.assertTrue(read, "no tables found: the scan needs updating")
                self.assertLessEqual(read, set(contract.TABLES_READ[kind]), f"{name} reads a table that TABLES_READ[{kind!r}] does not list")


if __name__ == "__main__":
    unittest.main()
