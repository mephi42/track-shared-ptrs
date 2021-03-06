#!/usr/bin/env python
import json
import os
import unittest


the_file = os.path.abspath(__file__)


class Test(unittest.TestCase):
    REPORT = "tracked-shared-ptrs"

    def setUp(self):
        self.testDir = os.path.dirname(the_file)
        os.chdir(self.testDir)
        self.rootDir = os.path.dirname(self.testDir)
        self.launcher = os.path.join(self.rootDir, "track-shared-ptrs")
        self.assertEqual(0, os.system("make all"))
        if os.path.exists(Test.REPORT):
            os.unlink(Test.REPORT)

    def tearDown(self):
        if os.path.exists(Test.REPORT):
            os.unlink(Test.REPORT)
        self.assertEqual(0, os.system("make clean"))

    def test_0(self):
        self.assertEqual(0, os.system(self.launcher + " --log=DEBUG ./test_0"))
        with open(Test.REPORT, "r") as f:
            report = json.load(f)
        self.assertFalse(report["success"])
        self.assertEqual(3, report["instances-created"])
        self.assertEqual(2, len(report["instances"]))

    def test_flake8(self):
        sources = ["track-shared-ptrs",
                   "track-shared-ptrs.py",
                   "test/test.py"]
        abs_sources = lambda p: os.path.join(self.rootDir, p)
        command = ["flake8"] + map(abs_sources, sources)
        self.assertEqual(0, os.system(" ".join(command)))


if __name__ == '__main__':
    unittest.main()
