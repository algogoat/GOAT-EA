import ast
from pathlib import Path
import unittest
from unittest.mock import patch
from studio_subprocess import background_creationflags


class BackgroundProcessTests(unittest.TestCase):
    def test_all_controller_spawns_explicitly_set_creationflags(self):
        failures=[]
        for path in Path(__file__).parent.glob('*.py'):
            if path.name.startswith('test_'): continue
            tree=ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute)
                    and isinstance(node.func.value,ast.Name) and node.func.value.id=='subprocess'
                    and node.func.attr in ('Popen','run','call','check_output','check_call')
                    and not any(key.arg=='creationflags' for key in node.keywords)):
                    failures.append(f'{path.name}:{node.lineno}')
        self.assertEqual(failures,[],'Background subprocess may flash a console')

    def test_windows_no_window_flag(self):
        with patch('studio_subprocess.subprocess.CREATE_NO_WINDOW',0x08000000,create=True):
            self.assertEqual(background_creationflags(),0x08000000)


if __name__=='__main__': unittest.main()
