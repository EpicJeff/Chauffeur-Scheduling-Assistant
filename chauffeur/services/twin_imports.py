"""Household model store, beside twin/library, never under static.

Original uploads are retained. glTF remains glTF (no exporter is vendored).
Only local, self-contained resources are accepted, including zip bundles.
"""
import base64
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import struct
import time
import uuid
import zipfile

from services import storage, twin_store, twin_objects

DEFAULT_LIMIT_MB = 50
MAX_TRIANGLES = 1000000
CHUNK_BYTES = 4 * 1024 * 1024
MAX_FILES = 512
UPLOAD_TTL = 3600
META = '.asset.json'


def limit_mb():
    value = storage.get_settings().get('twin_import_limit_mb', DEFAULT_LIMIT_MB)
    return value if type(value) is int and 1 <= value <= 200 else DEFAULT_LIMIT_MB


def unpacked_limit_mb():
    value = storage.get_settings().get('twin_import_unpacked_limit_mb', 200)
    return value if type(value) is int and 1 <= value <= 1000 else 200


def _uploads():
    folder = root() / '.uploads'
    folder.mkdir(parents=True, exist_ok=True)
    for upload in folder.iterdir():
        if upload.is_dir():
            try:
                meta = json.loads((upload / 'meta.json').read_text(encoding='utf-8'))
                expired = time.time() >= meta['expires']
            except (FileNotFoundError, ValueError, KeyError, TypeError):
                expired = True  # An interrupted start must not block future uploads.
            if expired:
                shutil.rmtree(upload)
    return folder


def _upload(upload_id):
    import re
    folder = _uploads()
    if not re.fullmatch(r'[a-f0-9]{32}', upload_id):
        raise ValueError('Unknown model upload. Start the upload again.')
    folder = folder / upload_id
    if not folder.is_dir():
        raise ValueError('This model upload expired or was cancelled. Start it again.')
    return folder, json.loads((folder / 'meta.json').read_text(encoding='utf-8'))


def start_upload(body):
    name, size, files = body.get('name'), body.get('size'), body.get('files')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError('Give the model a name of at most 100 characters.')
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise ValueError('Choose from 1 to 512 model files.')
    declared, names = [], set()
    for row in files:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str):
            raise ValueError('Declare each model filename and size.')
        filename = path_name(row['name'])
        if filename in names or type(row.get('size')) is not int or row['size'] < 0:
            raise ValueError('Use distinct model filenames and valid file sizes.')
        names.add(filename)
        declared.append({'name': filename, 'size': row['size']})
    if type(size) is not int or size <= 0 or size != sum(row['size'] for row in declared):
        raise ValueError('The declared model sizes do not match.')
    if size > limit_mb() * 1024 * 1024:
        raise ValueError(f'Models may be at most {limit_mb()} MB uploaded.')
    with twin_store.LIFECYCLE, twin_store._LOCK:
        folder = _uploads()
        if len(list(folder.iterdir())) >= 2:
            raise ValueError('Two models are already uploading. Finish or cancel one first.')
        upload_id = uuid.uuid4().hex
        folder = folder / upload_id
        folder.mkdir()
        (folder / 'body').write_bytes(b'')
        (folder / 'meta.json').write_text(json.dumps({'name': name.strip(), 'size': size,
            'files': declared, 'received': 0, 'index': 0, 'expires': time.time() + UPLOAD_TTL}), encoding='utf-8')
    return {'upload_id': upload_id, 'chunk_bytes': CHUNK_BYTES}


def upload_chunk(upload_id, index, data):
    with twin_store.LIFECYCLE, twin_store._LOCK:
        folder, meta = _upload(upload_id)
        if index != meta['index']:
            raise ValueError(f"Send model chunk {meta['index']} next.")
        if not data or len(data) > CHUNK_BYTES or meta['received'] + len(data) > meta['size']:
            raise ValueError('This chunk exceeds the declared model size or the 4 MB chunk limit.')
        if meta['size'] > limit_mb() * 1024 * 1024:
            raise ValueError(f'Models may be at most {limit_mb()} MB uploaded.')
        # Truncate any unacknowledged append left by an interrupted write.
        with (folder / 'body').open('r+b') as stream:
            stream.truncate(meta['received'])
            stream.seek(meta['received'])
            stream.write(data)
        meta['received'] += len(data)
        meta['index'] += 1
        temp = folder / 'meta.tmp'
        temp.write_text(json.dumps(meta), encoding='utf-8')
        os.replace(temp, folder / 'meta.json')
        return {'received': meta['received'], 'index': meta['index']}


def finish_upload(upload_id):
    with twin_store.LIFECYCLE, twin_store._LOCK:
        folder, meta = _upload(upload_id)
        if meta['received'] != meta['size'] or (folder / 'body').stat().st_size != meta['size']:
            raise ValueError('The model upload is incomplete. Send the remaining chunks first.')
        try:
            with (folder / 'body').open('rb') as stream:
                files = {row['name']: stream.read(row['size']) for row in meta['files']}
            return create(files, meta['name'], 'other')
        finally:
            shutil.rmtree(folder)


def cancel_upload(upload_id):
    with twin_store.LIFECYCLE, twin_store._LOCK:
        folder, _ = _upload(upload_id)
        shutil.rmtree(folder)
    return {'ok': True}


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
            if type(count) is not int or count < 0:
                raise ValueError('Invalid model vertex count.')
            if count > MAX_TRIANGLES * 3:
                raise ValueError('This model exceeds 1,000,000 triangles. Simplify it before importing.')
            mode = primitive.get('mode', 4)
            triangles += count // 3 if mode == 4 else max(0, count - 2) if mode in (5, 6) else count
        counts.append(triangles)
    # Count every node instance, not just each unique mesh.
    triangles = sum(counts[node['mesh']] for node in doc.get('nodes', []) if 'mesh' in node)
    if triangles > MAX_TRIANGLES:
        raise ValueError('This model exceeds 1,000,000 triangles. Simplify it before importing.')
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
    if not files or len(files) > MAX_FILES or sum(len(data) for data in files.values()) > cap:
        raise ValueError(f'Models may be at most {limit_mb()} MB.')
    files = {path_name(n): d for n, d in files.items()}
    original = dict(files)
    unpacked = sum(len(d) for n, d in files.items() if not n.lower().endswith('.zip'))
    entries = len(files)
    def check_unpacked():
        if unpacked > unpacked_limit_mb() * 1024 * 1024:
            raise ValueError(f'This model unpacks to {unpacked / (1024 * 1024):.0f} MB; the limit is {unpacked_limit_mb()} MB.')
    check_unpacked()
    for filename, data in original.items():
        if filename.lower().endswith(('.dae', '.kmz')):
            raise ValueError('Collada and KMZ are not available in this build; use glTF or GLB.')
        if filename.lower().endswith('.zip'):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries += len(archive.infolist())
                if entries > MAX_FILES:
                    raise ValueError('Models may contain at most 512 files and zip entries.')
                unpacked += sum(i.file_size for i in archive.infolist())
                check_unpacked()
                if any(i.file_size > 100 * i.compress_size for i in archive.infolist()):
                    raise ValueError('This zip expands more than 100 times its compressed size. Export a less compressed zip.')
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
             'heavy': triangles > 300000,
             'warning': (f'Heavy model: {triangles / 1000:.0f}k triangles. It shows in full on the High setting; the wall panel shows a simple stand-in.'
                         if triangles > 300000 else 'Large model (over 100,000 triangles).' if triangles > 100000 else None)}
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


def rename(asset_id, name, kind=None, thumbnail=None, size=None):
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError('Give the model a name of at most 100 characters.')
    if size is not None and (not isinstance(size, list) or len(size) != 3
            or any(type(n) not in (int, float) or not math.isfinite(n) or n < 0 for n in size)):
        raise ValueError('Use the model width, height and depth in metres.')
    with twin_store.LIFECYCLE, twin_store._LOCK:
        entry = get(asset_id)
        if not entry:
            raise KeyError(asset_id)
        entry['name'] = name.strip()
        if size is not None:
            entry['size'] = size
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
