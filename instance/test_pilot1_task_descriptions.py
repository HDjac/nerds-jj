import unittest
from pilot1_task_descriptions import pilot1_task_description, PROGRAM_OVERVIEWS

class Pilot1TaskDescriptionTests(unittest.TestCase):
    def test_anonymous_position_both_orders(self):
        for code in PROGRAM_OVERVIEWS:
            for position in (1, 2):
                with self.subTest(code=code, position=position):
                    html = pilot1_task_description(code, position)
                    self.assertIn(f"Task {position} — Fuzzing Investigation", html)
                    self.assertNotIn(code, html)
                    self.assertNotIn('Dense', html)
                    self.assertNotIn('Low-Yield', html)
                    for expected in ('fuzz_a', 'fuzz_b', 'fuzz_c', 'corpus', 'harness_a.c', 'harness_b.c', 'harness_c.c', 'Makefile', 'include/', 'src/'):
                        self.assertIn(expected, html)

    def test_invalid_metadata_rejected(self):
        for code, position in [('unknown',1),('dense_v2',3),('lowyield_v1',0),('dense_v2',True)]:
            with self.subTest(code=code, position=position):
                with self.assertRaises(ValueError):
                    pilot1_task_description(code, position)

    def test_program_overviews_are_distinct_and_neutral(self):
        a = pilot1_task_description('dense_v2',1)
        b = pilot1_task_description('lowyield_v1',1)
        self.assertNotEqual(a,b)
        self.assertIn('framed messages', a)
        self.assertIn('binary protocol', b)
        for html in (a,b):
            for phrase in ('vulnerability location', 'easy task', 'difficult task', 'better harness', 'correct harness'):
                self.assertNotIn(phrase, html.lower())

if __name__ == '__main__':
    unittest.main()
