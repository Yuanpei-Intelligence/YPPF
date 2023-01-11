from django.test import TestCase, SimpleTestCase

from utils.context_managers import *

class CheckerTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from utils.context_managers import DEFAULT_EXC_TYPE
        cls.exc_type = DEFAULT_EXC_TYPE
        return super().setUpClass()

    def test_exception_type(self):
        '''Checker的抛出异常类型应只支持AssertionError'''
        self.assertEqual(self.exc_type, AssertionError)
        with self.assertRaises(AssertionError):
            with Checker(AssertionError) as checker:
                0 / 0

    def test_untrapped(self):
        '''不捕获的异常类型直接抛出'''
        with self.assertRaises(ZeroDivisionError):
            with Checker(ZeroDivisionError) as checker:
                0 / 0

    def test_untrapped_exact(self):
        '''不捕获的异常类型必须准确匹配，目的是为只用于实现内部异常'''
        with self.assertRaises(AssertionError):
            with Checker(ZeroDivisionError.__base__) as checker:
                0 / 0

    def test_assert_failure(self):
        '''assert_在测试前线更新提示信息，若未设置则不更新'''
        with self.assertRaisesRegex(AssertionError, '2'):
            with Checker(AssertionError) as checker:
                checker.assert_(True, 'Error 1')
                checker.assert_(False, 'Error 2')
        with self.assertRaisesRegex(AssertionError, '1'):
            with Checker(AssertionError) as checker:
                checker.set_output('Error 1')
                checker.assert_(False)

    def test_assert_success(self):
        '''assert_的语句执行成功后，更新提示信息，若未设置则不更新'''
        with self.assertRaisesRegex(AssertionError, '2'):
            with Checker(AssertionError) as checker:
                checker.assert_(True, 'Error 1', 'Error 2')
                0 / 0
        with self.assertRaisesRegex(AssertionError, '1'):
            with Checker(AssertionError) as checker:
                checker.assert_(True, 'Error 1')
                0 / 0

    def test_assert_except(self):
        '''assert_的语句执行出错时，无法更新提示信息'''
        with self.assertRaisesRegex(AssertionError, '1'):
            with Checker(AssertionError) as checker:
                checker.set_output('Error 1')
                checker.assert_(0 / 0, 'Error 2')
