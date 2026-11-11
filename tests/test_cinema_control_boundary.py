"""Physical camera controls must never succeed by changing host display state."""
import copy
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import threading
import unittest
from concurrent.futures import Future

from tools.research import ptp_liveview_client as cinema
from tools.research.sony_ptp_controls import SonySettings
from tests.test_sony_ptp_controls import Driver


class CinemaControlBoundaryTests(unittest.TestCase):
    def test_owner_thread_confirms_real_backend_readback(self):
        before = copy.deepcopy(cinema.camera_state)
        driver = Driver()
        settings = SonySettings(driver)
        future = Future()
        try:
            cinema.control_requests.put_nowait(('iso', 800, future))
            cinema.service_controls(settings)
            self.assertTrue(future.result()['applied'])
            self.assertEqual(cinema.camera_state['iso'], '800')
            self.assertEqual(len(driver.writes), 1)
        finally:
            cinema.camera_state.clear()
            cinema.camera_state.update(before)

    def test_cancelled_queued_request_never_writes(self):
        driver = Driver()
        future = Future()
        future.cancel()
        cinema.control_requests.put_nowait(('iso', 800, future))
        cinema.service_controls(SonySettings(driver))
        self.assertEqual(driver.writes, [])

    def test_cross_origin_camera_command_is_rejected(self):
        conn = HTTPConnection(*self.server.server_address, timeout=3)
        try:
            conn.request('POST', '/api/control', json.dumps({'param': 'iso', 'value': 800}),
                         {'Content-Type': 'application/json', 'Origin': 'http://example.com'})
            response = conn.getresponse()
            self.assertEqual(response.status, 403)
            response.read()
        finally:
            conn.close()

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), cinema.MJPEGHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_camera_commands_are_rejected_without_mutating_state(self):
        for param, value in [('iso', '1600'), ('recording', True),
                             ('controls_available', True)]:
            with self.subTest(param=param):
                before = copy.deepcopy(cinema.camera_state)
                conn = HTTPConnection(*self.server.server_address, timeout=3)
                try:
                    conn.request('POST', '/api/control',
                                 json.dumps({'param': param, 'value': value}),
                                 {'Content-Type': 'application/json'})
                    response = conn.getresponse()
                    payload = json.loads(response.read())
                    self.assertEqual(response.status, 501)
                    self.assertIs(payload['applied'], False)
                    self.assertEqual(cinema.camera_state, before)
                finally:
                    conn.close()


if __name__ == '__main__':
    unittest.main()
