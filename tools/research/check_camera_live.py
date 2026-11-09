import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from tools.camera_debugger import connect

def main():
    with connect() as d:
        r = d.request(3, b'cat /proc/149/task/368/stack')
        print("TID 368 stack:")
        print(r['payload'].decode(errors='replace'))

if __name__ == '__main__':
    main()
