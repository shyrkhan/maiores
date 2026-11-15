"""What the builders pack: a module left out makes the installed program crash at start."""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def local_imports(module):
    """Names of this program's own modules that `module` imports, at any depth in the file."""
    tree = ast.parse((ROOT / f"{module}.py").read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return {name for name in names if (ROOT / f"{name}.py").is_file()}


class AndroidStageTests(unittest.TestCase):
    def test_every_module_the_program_imports_is_staged(self):
        from android_stage import MODULES
        needed, waiting = set(), ["app"]
        while waiting:
            module = waiting.pop()
            if module not in needed:
                needed.add(module)
                waiting += local_imports(module)
        self.assertEqual(sorted(needed - set(MODULES)), [])


class RobotStubTests(unittest.TestCase):
    def test_every_window_the_program_asks_through_is_stubbed_for_the_robot_and_the_sweep(self):
        """An ask_ method left real opens a window that waits for a click: the run hangs."""
        import re
        asks = set(re.findall(r"^    def (ask_\w+)\(", (ROOT / "app.py").read_text(encoding="utf-8"), re.M))
        for tool in ("explorer.py", "sweep.py"):
            stubbed = set(re.findall(r"\.(ask_\w+) = ", (ROOT / "devtools" / tool).read_text(encoding="utf-8")))
            self.assertEqual(sorted(asks - stubbed), [], tool)


if __name__ == "__main__":
    unittest.main()


class WorkflowFileTests(unittest.TestCase):
    def test_no_key_appears_twice_in_one_block(self):
        """GitHub rejects a whole workflow over one repeated key (a second retention-days
        once stopped every build, the 1.3.0 release included)."""
        import re
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            blocks = []  # (indent, keys seen) for each open mapping.
            literal_indent = None
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                indent = len(line) - len(line.lstrip())
                if literal_indent is not None:
                    if indent > literal_indent:
                        continue  # Inside a "|" block of text.
                    literal_indent = None
                text = line.strip()
                item = text.startswith("- ")
                if item:
                    indent += 2
                    text = text[2:]
                while blocks and (blocks[-1][0] > indent or (item and blocks[-1][0] == indent)):
                    blocks.pop()
                match = re.match(r"([A-Za-z0-9_.-]+|\"[^\"]+\"):(\s|$)", text)
                if not match:
                    continue
                if not blocks or blocks[-1][0] < indent:
                    blocks.append((indent, set()))
                key = match[1]
                self.assertNotIn(key, blocks[-1][1], f"{path.name}:{number} repeats {key}")
                blocks[-1][1].add(key)
                if text.rstrip().endswith(("|", ">")):
                    literal_indent = indent
