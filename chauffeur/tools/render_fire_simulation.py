"""Bake Mantaflow flames for a fireplace and export native RGBA frames.

Run with Blender 4.5 LTS, not the application's Python interpreter:
  blender -b -t 8 --python render_fire_simulation.py -- <output-directory>
  blender -b -t 8 --python render_fire_simulation.py -- <output-directory> --render-existing

The output directory holds the editable .blend, OpenVDB cache and PNG frames.
The app only needs the encoded WebM; it has no Blender runtime dependency.
"""
import bpy, sys, math, json
from pathlib import Path
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view

args=sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []
out=Path(args[0]).resolve() if args else Path('scratch/blender-fire').resolve()
out.mkdir(parents=True,exist_ok=True)
if '--render-existing' in args:
    bpy.ops.wm.open_mainfile(filepath=str(out/'fireplace.blend'))
    scene=bpy.context.scene
    prefs=bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type='OPTIX';prefs.get_devices()
    for device in prefs.devices:device.use=device.type=='OPTIX'
    scene.cycles.device='GPU';scene.cycles.samples=64
    # Holdout logs stay render-visible: they occlude rear flames without
    # contributing wood pixels. Hiding them would destroy that depth cue.
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'fireplace-flames.blend'))
    scene.frame_start=49;scene.frame_end=168
    (out/'frames').mkdir(exist_ok=True)
    scene.render.filepath=str(out/'frames/fire_')
    bpy.ops.render.render(animation=True)
    print('ANIMATION DONE',flush=True)
    sys.exit(0)

bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
s=bpy.context.scene
s.render.engine='CYCLES';s.cycles.samples=32;s.cycles.use_denoising=True
prefs=bpy.context.preferences.addons['cycles'].preferences
try:
    prefs.compute_device_type='OPTIX';prefs.get_devices()
    for d in prefs.devices:d.use=d.type=='OPTIX'
    s.cycles.device='GPU'
except Exception as e:print('CPU render fallback',e)
s.render.resolution_x=400;s.render.resolution_y=480;s.render.resolution_percentage=100
s.render.fps=24;s.frame_start=1;s.frame_end=168
s.render.film_transparent=True;s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGBA';s.render.image_settings.color_depth='8'
s.world.color=(0,0,0);s.world.node_tree.nodes['Background'].inputs['Strength'].default_value=0
s.view_settings.view_transform='Standard';s.view_settings.exposure=0
s.render.threads_mode='FIXED';s.render.threads=8

# Mantaflow gas domain: fuel combustion, buoyancy and vortical advection.
bpy.ops.mesh.primitive_cube_add(size=1,location=(0,0,1.25));domain=bpy.context.object;domain.name='Mantaflow fireplace combustion';domain.dimensions=(2.5,1.4,2.8);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
mod=domain.modifiers.new('Combustion simulation','FLUID');mod.fluid_type='DOMAIN';d=mod.domain_settings
d.domain_type='GAS';d.resolution_max=80;d.cache_type='MODULAR';d.cache_directory=str(out/'cache');d.cache_frame_start=1;d.cache_frame_end=168;d.cache_data_format='OPENVDB';d.time_scale=.85;d.use_noise=False
# Keep all boundaries open; the crop must not truncate a rising flame.
d.use_collision_border_front=False;d.use_collision_border_back=False;d.use_collision_border_left=False;d.use_collision_border_right=False;d.use_collision_border_top=False;d.use_collision_border_bottom=False
d.burning_rate=.9;d.flame_smoke=.02;d.flame_vorticity=.7;d.vorticity=.12;d.flame_ignition=1.3;d.flame_max_temp=2.4
d.use_dissolve_smoke=True;d.dissolve_speed=12;d.use_adaptive_domain=False
fire=bpy.data.materials.new('Fire volume with physical opacity');fire.use_nodes=True
n=fire.node_tree.nodes;l=fire.node_tree.links;n.clear()
output=n.new('ShaderNodeOutputMaterial');vol=n.new('ShaderNodeVolumePrincipled');l.new(vol.outputs['Volume'],output.inputs['Volume'])
vol.inputs['Density Attribute'].default_value='';vol.inputs['Blackbody Intensity'].default_value=0;vol.inputs['Color'].default_value=(.04,.01,.002,1)
info=n.new('ShaderNodeVolumeInfo');power=n.new('ShaderNodeMath');power.operation='POWER';power.inputs[1].default_value=1.5;l.new(info.outputs['Flame'],power.inputs[0])
# Both coverage and radiance come from the simulated burning-fuel field.
# Finite extinction gives PNG alpha usable on light as well as dark backgrounds.
density=n.new('ShaderNodeMath');density.operation='MULTIPLY';density.inputs[1].default_value=40;l.new(power.outputs[0],density.inputs[0]);l.new(density.outputs[0],vol.inputs['Density'])
strength=n.new('ShaderNodeMath');strength.operation='MULTIPLY';strength.inputs[1].default_value=24;l.new(power.outputs[0],strength.inputs[0]);l.new(strength.outputs[0],vol.inputs['Emission Strength'])
ramp=n.new('ShaderNodeValToRGB');r=ramp.color_ramp;r.elements.remove(r.elements[1]);r.elements[0].position=0;r.elements[0].color=(.15,.002,0,1)
for pos,col in [(.2,(1,.035,.001,1)),(.5,(1,.25,.008,1)),(.75,(1,.65,.16,1)),(1,(1,.94,.72,1))]:r.elements.new(pos).color=col
l.new(info.outputs['Flame'],ramp.inputs[0]);l.new(ramp.outputs[0],vol.inputs['Emission Color'])
domain.data.materials.append(fire)
# Camera framing equals the 200x240 layer in the 1536x1024 room image.
bpy.ops.object.camera_add(location=(2.2,-7,3.1))
cam=bpy.context.object
cam.rotation_euler=(Vector((0,0,1.13))-cam.location).to_track_quat('-Z','Y').to_euler()
cam.data.type='ORTHO';cam.data.ortho_scale=3.15;s.camera=cam
bpy.context.view_layer.update()

def source_to_world(pixel, height):
    """Back-project an observed image point onto a known log-height plane."""
    desired=Vector(((pixel[0]-508)/200,1-(pixel[1]-294)/240))
    origin=world_to_camera_view(s,cam,Vector((0,0,height)))
    px=world_to_camera_view(s,cam,Vector((1,0,height)))
    py=world_to_camera_view(s,cam,Vector((0,1,height)))
    jacobian=Matrix(((px.x-origin.x,py.x-origin.x),(px.y-origin.y,py.y-origin.y)))
    xy=jacobian.inverted()@(desired-Vector((origin.x,origin.y)))
    return Vector((xy.x,xy.y,height))

holdout=bpy.data.materials.new('Invisible log occlusion');holdout.use_nodes=True
hn=holdout.node_tree.nodes;hn.clear()
ho=hn.new('ShaderNodeHoldout');hout=hn.new('ShaderNodeOutputMaterial')
holdout.node_tree.links.new(ho.outputs[0],hout.inputs['Surface'])

# Near/far cut-face centers measured in the static room photograph. Bottom
# logs rest on the hearth; the third crosses above them. Bark weights vary
# continuously over the entire upper surface, not at detached point sources.
log_specs=[
    ('Front lower log',(553,492),(642,455),.145,.145),
    ('Rear lower log',(536,480),(659,473),.13,.13),
    ('Crossed upper log',(649,482),(578,452),.39,.15),
]
all_vertices=[];registration=[]
for index,(name,near,far,height,radius) in enumerate(log_specs):
    start=source_to_world(near,height);end=source_to_world(far,height)
    axis=(end-start).normalized();length=(end-start).length
    across=axis.cross(Vector((0,0,1))).normalized()
    up=across.cross(axis).normalized()
    vertices=[];weights=[];faces=[];rings=33;sides=32
    for j in range(rings):
        t=j/(rings-1)
        for k in range(sides):
            angle=2*math.pi*k/sides
            radial=math.cos(angle)*up+math.sin(angle)*across
            bark=1+.025*math.sin(k*5+j*.9)+.018*math.sin(j*2.7+k*3)
            taper=.93+.07*math.sin(math.pi*t)
            point=start+axis*length*t+radial*radius*bark*taper
            vertices.append(point)
            exposure=max(0,radial.z)
            # Actual inactive bark between irregular burning regions.
            patch=max(0,min(1,.35+.55*math.sin(t*19+index*2+angle*3)
                            +.3*math.sin(t*37-angle*5+index)))
            weights.append(min(1,exposure**.75*patch))
    for j in range(rings-1):
        for k in range(sides):
            a=j*sides+k;b=j*sides+(k+1)%sides
            faces.append((a,b,b+sides,a+sides))
    faces.append(tuple(reversed(range(sides))))
    faces.append(tuple((rings-1)*sides+k for k in range(sides)))
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(vertices,[],faces);mesh.update()
    emitter=bpy.data.objects.new(name+' | burning bark',mesh);s.collection.objects.link(emitter)
    group=emitter.vertex_groups.new(name='Exposed burning bark')
    for i,weight in enumerate(weights):group.add([i],weight,'REPLACE')
    flow=emitter.modifiers.new('Fuel from log surface','FLUID');flow.fluid_type='FLOW'
    f=flow.flow_settings;f.flow_type='FIRE';f.flow_behavior='INFLOW'
    f.fuel_amount=.8;f.surface_distance=1.0;f.volume_density=0
    f.density_vertex_group=group.name;f.use_initial_velocity=True
    f.velocity_coord=(0,0,.25)
    # Advect a textured ignition pattern over each log. The mesh and its
    # collision/holdout twins stay fixed while active bark patches change.
    texture=bpy.data.textures.new(name+' | changing ignition',type='CLOUDS')
    texture.noise_scale=.3;texture.noise_depth=2
    texture.use_color_ramp=True
    texture.color_ramp.elements[0].position=.32
    texture.color_ramp.elements[1].position=.62
    f.use_texture=True;f.noise_texture=texture;f.texture_map_type='AUTO';f.texture_size=.7
    for frame in range(1,170,8):
        f.texture_offset=index*.71+frame*.018
        f.keyframe_insert(data_path='texture_offset',frame=frame)
        f.fuel_amount=.8+.18*math.sin(frame*.17+index*2.1)+.1*math.sin(frame*.39+index)
        f.keyframe_insert(data_path='fuel_amount',frame=frame)
    s.frame_set(1)
    emitter.hide_render=True
    # Same geometry supplies the holdout and an inset solid collision core.
    occluder=bpy.data.objects.new(name+' | holdout',mesh.copy());s.collection.objects.link(occluder)
    occluder.data.materials.append(holdout)
    core=bpy.data.objects.new(name+' | solid core',mesh.copy());s.collection.objects.link(core)
    for vertex in core.data.vertices:
        along=(vertex.co-start).dot(axis);center=start+axis*along
        vertex.co=center+(vertex.co-center)*.88
    effector=core.modifiers.new('Solid wood collision','FLUID');effector.fluid_type='EFFECTOR'
    effector.effector_settings.surface_distance=.001;core.hide_render=True
    all_vertices.extend(vertices)
    registration.append({'name':name,'near':list(near),'far':list(far),'worldNear':list(start),'worldFar':list(end),'radius':radius})

# Fit a fixed domain around the complete log stack and rising flame volume.
lo=Vector((min(v.x for v in all_vertices)-.25,min(v.y for v in all_vertices)-.25,-.08))
hi=Vector((max(v.x for v in all_vertices)+.25,max(v.y for v in all_vertices)+.25,2.85))
bpy.ops.object.select_all(action='DESELECT');domain.select_set(True);bpy.context.view_layer.objects.active=domain
domain.location=(lo+hi)/2;domain.dimensions=hi-lo
bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
d.resolution_max=96;d.flame_vorticity=.6;d.burning_rate=.36
d.flame_ignition=2;d.flame_max_temp=3.5
(out/'log-registration.json').write_text(json.dumps(registration,indent=2))
print('DOMAIN',list(domain.dimensions),'LOG REGISTRATION',registration,flush=True)

if '--setup-only' in args:
    # Color-coded geometry diagnostic, never used as the production overlay.
    domain.hide_render=True
    for index,ob in enumerate(o for o in bpy.data.objects if o.name.endswith('| holdout')):
        mat=bpy.data.materials.new('Alignment diagnostic');mat.use_nodes=True
        nodes=mat.node_tree.nodes;nodes.clear();e=nodes.new('ShaderNodeEmission');o=nodes.new('ShaderNodeOutputMaterial')
        e.inputs['Color'].default_value=[(.05,.8,.3,1),(.1,.3,1,1),(1,.1,.2,1)][index]
        mat.node_tree.links.new(e.outputs[0],o.inputs['Surface'])
        ob.data.materials.clear();ob.data.materials.append(mat)
    s.render.filepath=str(out/'alignment.png');bpy.ops.render.render(write_still=True)
    sys.exit(0)
bpy.ops.object.light_add(type='AREA',location=(0,-3,4));bpy.context.object.data.energy=90;bpy.context.object.data.shape='DISK';bpy.context.object.data.size=4
bpy.ops.object.select_all(action='DESELECT');domain.select_set(True);bpy.context.view_layer.objects.active=domain
bpy.ops.wm.save_as_mainfile(filepath=str(out/'fireplace.blend'))
print('BAKE START',flush=True);bpy.ops.fluid.bake_data();print('BAKE DONE',flush=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'fireplace.blend'))
for frame in (48,72,96,120):
    s.frame_set(frame);s.render.filepath=str(out/f'preview-{frame:04}.png');bpy.ops.render.render(write_still=True)
print('PREVIEW DONE',flush=True)
