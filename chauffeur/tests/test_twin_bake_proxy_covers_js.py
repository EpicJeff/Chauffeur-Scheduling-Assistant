"""The wall texels under a batten bake as the batten's own face, in the host chart's own rect.

Owner 2026-11-21: at 4 texels/ft every batten drew a dark strip in baked light. The wall
texels a batten covers sit 2.7 cm behind it and see no light; their black was smeared by
bilinear sampling and borrowed by the batten (a lightmap proxy). bake_pass.proxyCovers draws
each proxy face in its host chart's lightmap coordinates (moved with the host's bank rect),
with the face's own position and normal, so renderPage replaces the buried wall texels with
what the face sees. This runs the production module in node, plus the dilation that still
fills any cleared texel no face covers.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_twin_tree_once_js import PREFIX  # noqa: E402
from twin_editor_dom import run_node  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

DRIVER = PREFIX + r"""
const THREE=await import('three');
const {proxyCovers,dilateCharts}=await import(file('static/twin/bake/bake_pass.js'));
// One mesh: faces 0-1 the wall (host chart), faces 2-3 a batten front (its proxy).
const pos=[], uv3=[];
const quad=(x0,x1,z,u0,u1)=>{for(const [x,y,u,v] of [[x0,0,u0,0],[x1,0,u1,0],[x1,1,u1,.5],[x0,0,u0,0],[x1,1,u1,.5],[x0,1,u0,.5]]){pos.push(x,y,z);uv3.push(u,v);}};
quad(0,1,0,0,.5);            // wall, uv 0..0.5
quad(.45,.55,.03,.225,.275); // batten front, 3 cm proud, mapped into the wall's uv
const g=new THREE.BufferGeometry();
g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3));
g.setAttribute('uv3',new THREE.Float32BufferAttribute(uv3,2));
const mesh=new THREE.Mesh(g);mesh.updateMatrixWorld(true);
const base={mesh,faces:[0,1],rect:{x:0,y:0,w:8,h:8},proxies:[{mesh,faces:[2,3]}]};
const layout={room:{charts:[base]}};
// The bank moved this chart 16 texels right on a 64-texel page.
const banked={...base,rect:{x:16,y:0,w:8,h:8}};
const scene=proxyCovers([banked],64,layout);
assert.equal(scene.children.length,1,'one cover mesh for the batten');
const cover=scene.children[0].geometry;
assert.deepEqual([...cover.index.array],[6,7,8,9,10,11],'only the proxy faces are drawn');
const uv=cover.attributes.bakeUV.array;
assert.ok(Math.abs(uv[12]-(.225+16/64))<1e-6,'the cover moves with its host chart rect');
assert.ok(Math.abs(g.attributes.uv3.array[12]-.225)<1e-6,'the mesh own uv3 is untouched');
assert.equal(proxyCovers([{...base,proxies:undefined}],64,layout).children.length,0,'no proxies, nothing drawn');

// A cleared strip (alpha 0) inside a lit chart is refilled from its neighbours, never left black.
const size=8,bytes=new Uint8Array(size*size*4);
for(let i=0;i<size*size;i++){bytes[i*4]=200;bytes[i*4+3]=255;}
for(let y=0;y<size;y++)for(const x of [3,4]){const p=(y*size+x)*4;bytes[p]=0;bytes[p+3]=0;}
dilateCharts(bytes,[{rect:{x:0,y:0,w:size,h:size}}],size);
for(let y=0;y<size;y++)for(const x of [3,4])assert.equal(bytes[(y*size+x)*4],200,'covered texel filled from the lit wall');
console.log('PASS proxy covers clear the wall under a batten and dilation refills it');
process.exit(0);
"""


def main():
    code, output = run_node(DRIVER, {'root': ROOT.as_posix()}, timeout=180)
    print(output, flush=True)
    if code is None:
        return
    assert code == 0, output


if __name__ == '__main__':
    main()
