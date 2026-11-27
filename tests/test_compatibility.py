"""Check LiveOSCQuery against the language-independent golden vectors from pxs-core."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from OSCQueryRemote import live_model, osc
from OSCQueryRemote.tree import Tree, describe


class Compatibility(unittest.TestCase):
    vectors_path = Path(__file__).resolve().parents[2] / "pxs-core/test/golden/vectors.tsv"

    def test_action_packets_and_advertisement(self):
        if not self.vectors_path.is_file():
            self.skipTest("pxs-core golden vectors are unavailable")
        with self.vectors_path.open(encoding="utf-8") as source:
            vectors = [line.rstrip("\r\n").split("\t") for line in source
                       if line.strip() and not line.startswith("#")]

        tree = Tree()
        calls = []
        node = live_model.trigger(tree.root, "N", lambda: calls.append(True))
        advertisements = [json.loads(row[2]) for row in vectors
                          if row[0] == "oscquery-action" and row[1] == "1"]
        self.assertIn(describe(node), advertisements)

        expected = {("/a", ""): [], ("/N", "N"): [None], ("/I", "I"): [True]}
        seen = set()
        for row in vectors:
            if row[0] != "osc" or tuple(row[1:3]) not in expected:
                continue
            _, address, tag, _, wire = row
            with self.subTest(tag=tag):
                [(received, args)] = osc.decode(bytes.fromhex(wire))
                self.assertEqual(received, address)
                self.assertEqual(args, expected[address, tag])
                self.assertTrue(node.write(args))
                seen.add((address, tag))
        self.assertEqual(seen, set(expected))
        self.assertEqual(calls, [True, True, True])


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python3 -I tests/test_compatibility.py PATH_TO_VECTORS_TSV")
    Compatibility.vectors_path = Path(sys.argv.pop())
    if not Compatibility.vectors_path.is_file():
        raise SystemExit("Golden vectors file not found: %s" % Compatibility.vectors_path)
    unittest.main()
