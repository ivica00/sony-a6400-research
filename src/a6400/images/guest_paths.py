"""Guest namespace path operations; never consult the host filesystem."""
import posixpath


def canonical(path):
    return posixpath.normpath('/' + path.lstrip('/'))


def resolve_guest(nodes, path, max_links=40, visit=None):
    """Resolve guest symlink components without touching the host filesystem."""
    # Keep '..' until after symlink expansion: link/.. need not mean its parent.
    path = '/' + path.lstrip('/')
    must_be_directory = path.endswith('/') or path.endswith('/.')
    chain, seen = [], set()
    for _ in range(max_links + 1):
        components = [part for part in path.split('/') if part and part != '.']
        if visit:
            visit('/', nodes.get('/'), bool(components))
        path = '/' + '/'.join(components)
        if path in seen:
            raise ValueError(f'Guest symlink cycle: {path}')
        seen.add(path)
        traversed = []
        for index, component in enumerate(components):
            if component == '..':
                if traversed:
                    traversed.pop()
                continue
            traversed.append(component)
            prefix = '/' + '/'.join(traversed)
            node = nodes.get(prefix)
            if visit:
                visit(prefix, node, index < len(components) - 1)
            if node is None:
                return {'path': path, 'chain': chain, 'status': 'missing', 'missing': prefix}
            if node['kind'] == 'symlink':
                target = node['target']
                if index == len(components) - 1 and (target.endswith('/') or target.endswith('/.')):
                    must_be_directory = True
                destination = target if target.startswith('/') else posixpath.join(posixpath.dirname(prefix), target)
                chain.append({'path': prefix, 'target': target})
                path = posixpath.join(destination, *components[index + 1:])
                break
            if index < len(components) - 1 and node['kind'] != 'directory':
                return {'path': path, 'chain': chain, 'status': 'not_directory', 'missing': prefix}
        else:
            path = '/' + '/'.join(traversed)
            if must_be_directory and path in nodes and nodes[path]['kind'] != 'directory':
                return {'path': path, 'chain': chain, 'status': 'not_directory', 'missing': path}
            return {'path': path, 'chain': chain, 'status': 'resolved' if path in nodes else 'missing'}
    raise ValueError('Guest symlink expansion limit exceeded')

