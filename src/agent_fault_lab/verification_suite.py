"""External observer for the controlled unittest fixture; no lab dependencies.

Invoked with isolated Python, outside the mutable workspace. This is evidence
collection for cooperative code, not a hostile-Python sandbox.
"""

import contextlib
import json
import sys
import unittest
from collections.abc import Iterator


def cases(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        elif isinstance(item, unittest.TestCase):
            yield item


class ObservedResult(unittest.TextTestResult):
    def startTest(self, test: unittest.TestCase) -> None:  # noqa: N802
        self.executed.append(test.id())
        super().startTest(test)

    def addSuccess(self, test: unittest.TestCase) -> None:  # noqa: N802
        self.succeeded.append(test.id())
        super().addSuccess(test)

    executed: list[str]
    succeeded: list[str]


def main() -> int:
    # Match `python3 -m unittest -v` discovery, but retain machine-readable facts.
    sys.path.insert(0, ".")
    with contextlib.redirect_stdout(sys.stderr):
        suite = unittest.defaultTestLoader.discover(".")
        discovered = sorted(test.id() for test in cases(suite))
        runner = unittest.TextTestRunner(verbosity=2)
        result = ObservedResult(runner.stream, True, 2)
        result.executed = []
        result.succeeded = []
        result.startTestRun()
        try:
            suite(result)
        finally:
            result.stopTestRun()
        result.printErrors()
    print(
        json.dumps(
            {
                "discovered": discovered,
                "executed": sorted(result.executed),
                "succeeded": sorted(result.succeeded),
                "skipped": sorted(test.id() for test, _ in result.skipped),
                "expected_failures": sorted(
                    test.id() for test, _ in result.expectedFailures
                ),
            }
        )
    )
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
