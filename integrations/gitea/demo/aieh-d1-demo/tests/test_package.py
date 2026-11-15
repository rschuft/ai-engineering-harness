import unittest

import aieh_d1_demo


class PackageTest(unittest.TestCase):
    def test_the_package_has_a_version(self):
        self.assertRegex(aieh_d1_demo.__version__, r'^[0-9]+\.[0-9]+\.[0-9]+$')


if __name__ == '__main__':
    unittest.main()
