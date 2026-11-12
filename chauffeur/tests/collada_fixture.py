"""Small authored-inch, Z-up model shared by runtime and browser scenarios."""
import base64
import io
import zipfile


def dae(texture=None, shading='phong'):
    images = f'<library_images><image id="image"><init_from>{texture}</init_from></image></library_images>' if texture else ''
    params = '<newparam sid="surface"><surface type="2D"><init_from>image</init_from></surface></newparam><newparam sid="sampler"><sampler2D><source>surface</source></sampler2D></newparam>' if texture else ''
    diffuse = '<texture texture="sampler" texcoord="UVSET0"/>' if texture else '<color>0.2 0.4 0.6 1</color>'
    return f'''<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit name="inch" meter="0.0254"/><up_axis>Z_UP</up_axis></asset>
{images}<library_effects><effect id="effect"><profile_COMMON>{params}<technique sid="common"><{shading}><diffuse>{diffuse}</diffuse><transparent opaque="A_ONE"><color>1 1 1 0.6</color></transparent></{shading}></technique></profile_COMMON></effect></library_effects>
<library_materials><material id="material" name="Fixture"><instance_effect url="#effect"/></material></library_materials>
<library_geometries><geometry id="triangle"><mesh>
<source id="positions"><float_array id="positions-array" count="9">10 20 30 110 20 30 10 70 230</float_array><technique_common><accessor source="#positions-array" count="3" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<source id="uv"><float_array id="uv-array" count="6">0 0 1 0 0 1</float_array><technique_common><accessor source="#uv-array" count="3" stride="2"><param name="S" type="float"/><param name="T" type="float"/></accessor></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
<triangles count="1" material="mat"><input semantic="VERTEX" source="#vertices" offset="0"/><input semantic="TEXCOORD" source="#uv" offset="1" set="0"/><p>0 0 1 1 2 2</p></triangles>
</mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="Scene"><node id="node"><instance_geometry url="#triangle"><bind_material><technique_common><instance_material symbol="mat" target="#material"><bind_vertex_input semantic="UVSET0" input_semantic="TEXCOORD" input_set="0"/></instance_material></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes>
<scene><instance_visual_scene url="#Scene"/></scene></COLLADA>'''.encode()


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aY1kAAAAASUVORK5CYII=')
# Uncompressed 1x1 BGR TGA, top-left origin.
TGA = bytes([0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0, 24, 32, 40, 80, 160])


def packed(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return stream.getvalue()
