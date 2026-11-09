from tools.camera_debugger import connect

def main():
    with connect() as d:
        maps_data, _ = d.read_all('/proc/149/maps')
        lines = maps_data.decode(errors='replace').splitlines()
        so_files = set()
        for line in lines:
            if '.so' in line or '/bin/' in line:
                parts = line.split()
                if len(parts) >= 6:
                    so_files.add(parts[5])
        for s in sorted(so_files):
            print(s)

if __name__ == '__main__':
    main()
