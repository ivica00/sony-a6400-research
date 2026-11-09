"""Policy-only mocks: these tests do not claim camera input/refresh compatibility."""
import ctypes as C
import shutil
import struct
import unittest
from tools.research.menu_touch_policy_host import Policy,Context,Event,Refresh

@unittest.skipUnless(shutil.which('gcc') or shutil.which('cc'),'Host C compiler required')
class MenuTouchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];self.hits={2};self.position_ok=1;self.hit_error=False;self.select_ok=1
        def position(_user,mouse,x,y):self.calls.append(('position',mouse));x[0]=320;y[0]=200;return self.position_ok
        def hit(_user,row,x,y):return -1 if self.hit_error else int(row in self.hits)
        def select(_user,row):self.calls.append(('select',row));return self.select_ok
        def refresh(_user):self.calls.append(('refresh',))
        self.p=Policy(position,hit,select,refresh)
        self.c=Context(1,0x1000,0x2000,1,149,149,6,1,0)
    def event(self,kind,mouse=0,button=0):return self.p.process(self.c,Event(kind,mouse,button))
    def actions(self):return [x for x in self.calls if x[0]!='position']
    def press(self):self.assertEqual(self.event(5),1)
    def test_one_selection_on_release(self):
        self.press();self.assertEqual(self.event(6),2);self.assertEqual(self.actions(),[('select',2),('refresh',)]);self.assertEqual(self.p.state.armed,0)
    def test_duplicate_release_does_not_repeat(self):
        self.press();self.event(6);self.assertEqual(self.event(6),0);self.assertEqual(len(self.actions()),2)
    def test_same_row_no_model_write(self):
        self.c.current_row=2;self.press();self.assertEqual(self.event(6),3);self.assertEqual(self.actions(),[])
    def test_release_without_press(self):self.assertEqual(self.event(6),0);self.assertEqual(self.calls,[])
    def test_press_outside_rows(self):self.hits=set();self.assertEqual(self.event(5),4);self.assertEqual(self.actions(),[])
    def test_release_in_another_row(self):self.press();self.hits={3};self.assertEqual(self.event(6),4);self.assertEqual(self.actions(),[])
    def test_move_outside_cancels_returning_touch(self):
        self.press();self.hits=set();self.assertEqual(self.event(2),4);self.hits={2};self.assertEqual(self.event(6),0);self.assertEqual(self.actions(),[])
    def test_move_inside_keeps_press_ignores_button_parameter(self):
        self.press();self.assertEqual(self.event(2,button=255),1);self.assertEqual(self.event(6),2)
    def test_menu_generation_change_cancels(self):
        self.press();self.c.generation+=1;n=len(self.calls);self.assertEqual(self.event(6),4);self.assertEqual(len(self.calls),n)
    def test_page_change_cancels(self):self.press();self.c.page+=4;self.assertEqual(self.event(6),4);self.assertEqual(self.actions(),[])
    def test_menu_change_cancels(self):self.press();self.c.menu+=4;self.assertEqual(self.event(6),4);self.assertEqual(self.actions(),[])
    def test_closed_menu_cancels(self):self.press();self.c.active=0;self.assertEqual(self.event(6),4);self.assertEqual(self.actions(),[])
    def test_unknown_lifetime_denied(self):self.c.generation=0;self.assertEqual(self.event(5),4);self.assertEqual(self.calls,[])
    def test_wrong_thread_denied(self):self.c.current_tid=302;self.assertEqual(self.event(5),-2);self.assertEqual(self.calls,[])
    def test_unproven_thread_denied(self):self.c.expected_tid=0;self.assertEqual(self.event(5),-2);self.assertEqual(self.calls,[])
    def test_other_mouse_cancels(self):self.press();self.assertEqual(self.event(6,mouse=1),4);self.assertEqual(self.actions(),[])
    def test_other_button_cancels(self):self.press();self.assertEqual(self.event(6,button=1),4);self.assertEqual(self.actions(),[])
    def test_no_button_is_not_a_press(self):self.assertEqual(self.event(5,button=5),4);self.assertEqual(self.calls,[])
    def test_ambiguous_hit_rejected(self):self.hits={1,2};self.assertEqual(self.event(5),-4);self.assertEqual(self.actions(),[])
    def test_hit_failure_rejected(self):self.hit_error=True;self.assertEqual(self.event(5),-3);self.assertEqual(self.actions(),[])
    def test_position_failure_rejected(self):self.position_ok=0;self.assertEqual(self.event(5),-3);self.assertEqual(self.actions(),[])
    def test_invalid_row_count_rejected(self):self.c.rows=7;self.assertEqual(self.event(5),-1);self.assertEqual(self.calls,[])
    def test_missing_refresh_denied_before_selection(self):self.p.ops.refresh=Refresh();self.assertEqual(self.event(5),-1);self.assertEqual(self.calls,[])
    def test_selection_failure_does_not_refresh(self):self.press();self.select_ok=0;self.assertEqual(self.event(6),-3);self.assertEqual(self.actions(),[('select',2)])
    def test_gesture_cancels(self):self.press();self.assertEqual(self.event(7),4);self.assertEqual(self.event(6),0);self.assertEqual(self.actions(),[])
    def test_transport_tag_not_confused_with_ui_press(self):self.assertEqual(self.event(1),0);self.assertEqual(self.calls,[])
    def test_decoder_ignores_event_parameters_for_coordinates(self):
        raw=struct.pack('<BBhhhIIQ',3,4,-123,456,-7,6,0,123456)
        buf=(C.c_uint8*len(raw)).from_buffer_copy(raw);out=Event()
        self.assertEqual(self.p.lib.mt_decode(buf,len(raw),C.byref(out)),0);self.assertEqual((out.type,out.mouse,out.button),(6,3,4))
    def test_decoder_rejects_short_record(self):
        raw=(C.c_uint8*8)();out=Event();self.assertEqual(self.p.lib.mt_decode(raw,8,C.byref(out)),-1)
