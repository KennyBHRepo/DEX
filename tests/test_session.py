import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from session import Session, Lesson

class SessionTests(unittest.TestCase):
    def test_off_disables_recognition(self):
        s=Session();s.set_mode('control');self.assertTrue(s.recognizing)
        s.set_mode('off');self.assertFalse(s.recognizing)
    def test_practice_launcher_can_never_control(self):
        s=Session(practice_only=True);s.set_mode('control');self.assertEqual(s.mode,'practice')
    def test_settings_prevent_activation_and_do_not_resume(self):
        s=Session();s.set_mode('control');s.suspend(True);s.set_mode('control')
        self.assertEqual(s.mode,'off');s.suspend(False);self.assertEqual(s.mode,'off')
    def test_lesson_movement_is_measured_from_first_sample(self):
        lesson=Lesson();lesson.reset(2)
        self.assertFalse(lesson.observe({'pointer':(.3,.3)}))
        self.assertFalse(lesson.observe({'pointer':(.31,.3)}))
        self.assertTrue(lesson.observe({'pointer':(.5,.3)}))
    def test_seen_hand_must_be_continuous(self):
        lesson=Lesson();lesson.reset(1)
        lesson.observe({'pointer':(.3,.3),'time':1})
        lesson.observe({'pointer':None,'time':1.4})
        self.assertFalse(lesson.observe({'pointer':(.3,.3),'time':1.6}))
        self.assertTrue(lesson.observe({'pointer':(.3,.3),'time':2.2}))
    def test_click_scroll_and_off_have_real_completion_signals(self):
        lesson=Lesson()
        for step,signal in [(3,'did_click'),(4,'did_scroll')]:
            lesson.reset(step);self.assertFalse(lesson.observe({}));self.assertTrue(lesson.observe({signal:True}))
        lesson.reset(5);self.assertFalse(lesson.observe({'mode':'practice'}));self.assertTrue(lesson.observe({'mode':'off'}))

if __name__=='__main__':unittest.main()
