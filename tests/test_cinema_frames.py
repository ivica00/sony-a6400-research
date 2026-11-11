import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from tools.research.cinema_frames import FrameHub
from tools.research import ptp_liveview_client as cinema


class FrameHubTests(unittest.TestCase):
    def test_slow_viewer_gets_newest_and_never_a_queue(self):
        hub=FrameHub()
        for i in range(20):hub.publish(bytes([i]))
        self.assertEqual(hub.after(0,0).jpeg,bytes([19]))
        self.assertIsNone(hub.after(20,0))

    def test_waiter_wakes_for_new_frame(self):
        hub=FrameHub();hub.publish(b'old')
        timer=threading.Timer(.02,lambda:hub.publish(b'new'));timer.start()
        self.assertEqual(hub.after(1,1).jpeg,b'new');timer.join()

    def test_http_connection_is_reused_and_sequences_are_fresh(self):
        previous=cinema.frame_hub;cinema.frame_hub=FrameHub()
        server=ThreadingHTTPServer(('127.0.0.1',0),cinema.MJPEGHandler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        conn=HTTPConnection(*server.server_address,timeout=3)
        try:
            cinema.frame_hub.publish(b'first',12.5)
            conn.request('GET','/frame.jpg?after=0')
            response=conn.getresponse();self.assertEqual(response.read(),b'first')
            self.assertEqual(response.getheader('X-Cinema-Sequence'),'1')
            self.assertEqual(response.getheader('X-Cinema-Fetch-Ms'),'12.500')
            sock=conn.sock
            cinema.frame_hub.publish(b'second')
            conn.request('GET','/frame.jpg?after=1')
            response=conn.getresponse();self.assertEqual(response.read(),b'second')
            self.assertIs(conn.sock,sock)
        finally:
            conn.close();server.shutdown();server.server_close();worker.join();cinema.frame_hub=previous


if __name__=='__main__':unittest.main()
