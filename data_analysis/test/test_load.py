from io import StringIO
from django.core.management import call_command
from django.test import TestCase

from data_analysis.management import register_load

class LoadCommandTest(TestCase):
    def test_register_command(self):
        '''测试注册指令'''
        cmd_label = '_test'
        filepath = 'test.csv'
        def _load_func(filepath, output_func=None, base_dir=''):
            output = f'filepath is {filepath}'
            if filepath is None:
                return output_func
            output_func(output)
            return
        register_load(cmd_label, _load_func, filepath)
        out = StringIO()
        call_command('load', cmd_label, stdout=out)
        self.assertIn(f'filepath is {filepath}', out.getvalue())
