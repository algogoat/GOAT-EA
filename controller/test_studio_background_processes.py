import ast
from pathlib import Path
import unittest
from unittest.mock import patch
from studio_subprocess import background_creationflags


def no_window(node,tree,depth=0):
    if depth>4:return False
    if isinstance(node,ast.Call):
        if isinstance(node.func,ast.Name) and node.func.id=='background_creationflags':return True
        return (isinstance(node.func,ast.Name) and node.func.id=='getattr' and len(node.args)>=2
                and isinstance(node.args[0],ast.Name) and node.args[0].id=='subprocess'
                and isinstance(node.args[1],ast.Constant) and node.args[1].value=='CREATE_NO_WINDOW')
    if isinstance(node,ast.Attribute):
        return isinstance(node.value,ast.Name) and node.value.id=='subprocess' and node.attr=='CREATE_NO_WINDOW'
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.BitOr):
        return no_window(node.left,tree,depth+1) or no_window(node.right,tree,depth+1)
    if isinstance(node,ast.Name):
        assignments=[row.value for row in ast.walk(tree) if isinstance(row,ast.Assign)
                     and any(isinstance(target,ast.Name) and target.id==node.id for target in row.targets)]
        return bool(assignments) and all(no_window(value,tree,depth+1) for value in assignments)
    return False


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
                    and not any(key.arg=='creationflags' and no_window(key.value,tree) for key in node.keywords)):
                    failures.append(f'{path.name}:{node.lineno}')
        self.assertEqual(failures,[],'Background subprocess may flash a console')

    def test_zero_or_unverified_flags_do_not_pass_the_guard(self):
        for expression in ('0','subprocess.CREATE_NEW_PROCESS_GROUP','unknown_flags'):
            tree=ast.parse(expression,mode='eval')
            self.assertFalse(no_window(tree.body,tree))
        tree=ast.parse('subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW',mode='eval')
        self.assertTrue(no_window(tree.body,tree))

    def test_windows_no_window_flag(self):
        with patch('studio_subprocess.subprocess.CREATE_NO_WINDOW',0x08000000,create=True):
            self.assertEqual(background_creationflags(),0x08000000)


if __name__=='__main__': unittest.main()
