"""Household model store, beside twin/library, never under static.

Original uploads are retained. glTF remains glTF (no exporter is vendored).
Only local, self-contained resources are accepted, including zip bundles.
"""
import base64
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import uuid
import zipfile

from services import storage, twin_store, twin_objects

DEFAULT_LIMIT_MB = 50
MAX_TRIANGLES = 300000
META = '.asset.json'


def limit_mb():
    value = storage.get_settings().get('twin_import_limit_mb', DEFAULT_LIMIT_MB)
    return value if type(value) is int and 1 <= value <= 200 else DEFAULT_LIMIT_MB


def root():
    return Path(twin_store.DATA_DIR) / 'imports'


def path_name(name):
    from urllib.parse import unquote
    name = unquote(name)
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or name.startswith('/')
            or any(p in ('..', '.', '') or p.startswith('.') for p in path.parts)
            or str(path) != name or len(name) > 240):
        raise ValueError('Use relative model resource filenames.')
    return name


def get(asset_id):
    import re
    if not isinstance(asset_id, str) or not re.fullmatch(r'import-[a-f0-9]{32}', asset_id):
        return None
    try:
        return json.loads((root() / asset_id / META).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None


def catalog():
    if not root().is_dir():
        return []
    return [entry for folder in sorted(root().iterdir()) if (entry := get(folder.name))]


def _document(name, data):
    if name.lower().endswith('.gltf'):
        return json.loads(data)
    if len(data) < 20 or data[:4] != b'glTF' or struct.unpack_from('<II', data, 4) != (2, len(data)):
        raise ValueError('Invalid GLB header.')
    length, kind = struct.unpack_from('<II', data, 12)
    if kind != 0x4E4F534A or length > len(data) - 20:
        raise ValueError('Invalid GLB JSON chunk.')
    return json.loads(data[20:20 + length])


def _inspect(name, files):
    from urllib.parse import urlsplit, unquote
    import posixpath
    doc = _document(name, files[name])
    if not isinstance(doc, dict) or doc.get('asset', {}).get('version') != '2.0':
        raise ValueError('Use a glTF 2.0 model.')
    for row in doc.get('buffers', []) + doc.get('images', []):
        uri = row.get('uri')
        if not uri or uri.startswith('data:'):
            continue
        parts = urlsplit(uri)
        if parts.scheme or parts.netloc or parts.query or parts.fragment:
            raise ValueError('Models must include their buffers and textures; remote URLs are not allowed.')
        resource = path_name(posixpath.normpath(posixpath.join(str(PurePosixPath(name).parent), unquote(uri))))
        if resource not in files:
            raise ValueError(f'Include the model resource: {resource}')
    if any(e in doc.get('extensionsRequired', []) for e in ('KHR_draco_mesh_compression', 'EXT_meshopt_compression', 'KHR_texture_basisu')):
        raise ValueError('Export an uncompressed glTF/GLB for this build.')
    counts = []
    for mesh in doc.get('meshes', []):
        triangles = 0
        for primitive in mesh.get('primitives', []):
            accessor = primitive.get('indices', primitive.get('attributes', {}).get('POSITION'))
            count = doc['accessors'][accessor]['count'] if accessor is not None else 0
            if type(count) is not int or not 0 <= count <= MAX_TRIANGLES * 3:
                raise ValueError('Invalid model vertex count.')
            mode = primitive.get('mode', 4)
            triangles += count // 3 if mode == 4 else max(0, count - 2) if mode in (5, 6) else count
        counts.append(triangles)
    # Count every node instance, not just each unique mesh.
    triangles = sum(counts[node['mesh']] for node in doc.get('nodes', []) if 'mesh' in node)
    if triangles > MAX_TRIANGLES:
        raise ValueError('This model exceeds 300,000 triangles. Simplify it before importing.')
    return triangles


def _thumbnail(thumbnail):
    thumbnail_bytes = None
    if thumbnail:
        from PIL import Image
        try:
            raw = base64.b64decode(thumbnail.split(',', 1)[-1], validate=True)
            if len(raw) > 200000:
                raise ValueError('Thumbnail is too large.')
            with Image.open(io.BytesIO(raw)) as image:
                if image.width > 512 or image.height > 512:
                    raise ValueError('Thumbnail is too large.')
                out = io.BytesIO()
                image.convert('RGBA').save(out, format='PNG')
                thumbnail_bytes = out.getvalue()
        except Exception as exc:
            raise ValueError('Use a small PNG model thumbnail.') from exc
    return thumbnail_bytes


def create(files, name, kind, thumbnail=None):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError('Give the model a name of at most 100 characters.')
    if not isinstance(kind, str) or kind not in twin_objects.SCHEMA['kinds']:
        raise ValueError('Choose a model kind.')
    cap = limit_mb() * 1024 * 1024
    if not files or sum(len(data) for data in files.values()) > cap:
        raise ValueError(f'Models may be at most {limit_mb()} MB.')
    files = {path_name(n): d for n, d in files.items()}
    original = dict(files)
    for filename, data in original.items():
        if filename.lower().endswith(('.dae', '.kmz')):
            raise ValueError('Collada and KMZ are not available in this build; use glTF or GLB.')
        if filename.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                if len(archive.infolist()) > 512 or sum(i.file_size for i in archive.infolist()) + sum(len(d) for n, d in files.items() if not n.lower().endswith('.zip')) > cap:
                    raise ValueError('The expanded model exceeds the import size limit.')
                for entry in archive.infolist():
                    if entry.is_dir():
                        continue
                    resource = path_name(entry.filename)
                    if resource in files:
                        raise ValueError('Duplicate model resource name.')
                    try:
                        files[resource] = archive.read(entry)
                    except RuntimeError as exc:
                        raise ValueError('Use a zip without encrypted resources.') from exc
    models = [n for n in files if n.lower().endswith(('.glb', '.gltf'))]
    if len(models) != 1:
        raise ValueError('Include exactly one .glb or .gltf model, with its buffers and textures.')
    try:
        triangles = _inspect(models[0], files)
    except (KeyError, IndexError, TypeError, AttributeError, UnicodeError, json.JSONDecodeError, struct.error) as exc:
        raise ValueError('The glTF model is invalid or incomplete.') from exc
    thumbnail_bytes = _thumbnail(thumbnail)
    asset_id = 'import-' + uuid.uuid4().hex
    entry = {'id': asset_id, 'name': name.strip(), 'kind': kind, 'model': models[0],
             'files': {n: True for n in files}, 'triangles': triangles,
             'warning': 'Large model (over 100,000 triangles).' if triangles > 100000 else None}
    with twin_store.LIFECYCLE, twin_store._LOCK:
        root().mkdir(parents=True, exist_ok=True)
        stage = root() / ('.' + asset_id)
        try:
            stage.mkdir()
            for filename, data in files.items():
                target = stage / filename
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            if thumbnail_bytes:
                (stage / '.thumbnail.png').write_bytes(thumbnail_bytes)
                entry['thumbnail'] = '.thumbnail.png'
                entry['files']['.thumbnail.png'] = True
            (stage / META).write_text(json.dumps(entry), encoding='utf-8')
            os.rename(stage, root() / asset_id)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    return entry


def rename(asset_id, name, kind=None, thumbnail=None):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError('Give the model a name of at most 100 characters.')
    with twin_store.LIFECYCLE, twin_store._LOCK:
        entry = get(asset_id)
        if not entry:
            raise KeyError(asset_id)
        entry['name'] = name.strip()
        if kind is not None:
            if not isinstance(kind, str) or kind not in twin_objects.SCHEMA['kinds']:
                raise ValueError('Choose a model kind.')
            if kind != entry['kind'] and twin_objects.placements(twin_store.current_model(), asset_id):
                raise ValueError('Remove placements before changing the model kind.')
            entry['kind'] = kind
        if thumbnail:
            (root() / asset_id / '.thumbnail.png').write_bytes(_thumbnail(thumbnail))
            entry['thumbnail'] = '.thumbnail.png'
            entry['files']['.thumbnail.png'] = True
        target = root() / asset_id / META
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(entry), encoding='utf-8')
        os.replace(temp, target)
        return entry


def delete(asset_id):
    with twin_store.LIFECYCLE, twin_store._LOCK:
        if not get(asset_id):
            raise KeyError(asset_id)
        places = twin_objects.placements(twin_store.current_model(), asset_id)
        if places:
            raise ValueError('Remove its placements first: ' + '; '.join(places))
        # Undo/old rounds retain referenced assets too, so a timeline revert works.
        state = twin_store._state()
        for row in state.get('rounds', []):
            old = twin_store._read_round(state, row['id'])
            if twin_objects.placements(old, asset_id):
                entry = get(asset_id)
                entry['archived'] = True
                (root() / asset_id / META).write_text(json.dumps(entry), encoding='utf-8')
                return
        shutil.rmtree(root() / asset_id)
