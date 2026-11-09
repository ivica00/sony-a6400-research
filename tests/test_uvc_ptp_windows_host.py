import unittest
from tools.research.uvc_ptp_windows_host import classify


def device(interface=None,service='usbccgp',inf='usb.inf',**changes):
    identity='USB\\VID_054C&PID_0CAA'+('' if interface is None else '&MI_'+interface)+'\\SERIAL'
    record=dict(InstanceId=identity,Service=service,DriverInf=inf,Status='OK',ProblemCode=0)
    record.update(changes)
    return record


class TestCompositeHostClassification(unittest.TestCase):
    def test_both_bound_children(self):
        result=classify([device(),device('00','WUDFRd','wpdmtp.inf'),device('01','usbvideo','usbvideo.inf')])
        self.assertTrue(result['children_ready_simultaneously'])

    def test_parent_is_not_ptp_child(self):
        result=classify([device()])
        self.assertTrue(result['composite_parent_ready'])
        self.assertFalse(result['ptp_ready'])
        self.assertFalse(result['children_ready_simultaneously'])

    def test_unrelated_camera_is_ignored(self):
        result=classify([device('01','usbvideo',InstanceId='USB\\VID_046D&PID_0CAA&MI_01\\X')])
        self.assertEqual(result['uvc_children'],[])

    def test_error_parent_does_not_complete_binding(self):
        result=classify([device(Status='Error',ProblemCode=10),device('00',inf='wpdmtp.inf'),device('01',service='usbvideo')])
        self.assertFalse(result['children_ready_simultaneously'])

    def test_unknown_problem_code_not_ready(self):
        self.assertFalse(classify([device('01',service='usbvideo',ProblemCode=None)])['uvc_ready'])

    def test_driver_not_just_friendly_name(self):
        self.assertFalse(classify([device('01',service='',inf='',FriendlyName='USB Video Device')])['uvc_ready'])

    def test_iad_second_interface_not_another_camera(self):
        result=classify([device('02',service='usbvideo')])
        self.assertEqual(len(result['other_interfaces']),1)
        self.assertFalse(result['uvc_ready'])


if __name__=='__main__':unittest.main()
