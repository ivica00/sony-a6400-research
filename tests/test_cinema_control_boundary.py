"""Physical camera controls must never succeed by changing host display state."""
import copy
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
import threading
import unittest

from tools.research import ptp_liveview_client as cinema


class CinemaControlBoundaryTests(unittest.TestCase):
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
