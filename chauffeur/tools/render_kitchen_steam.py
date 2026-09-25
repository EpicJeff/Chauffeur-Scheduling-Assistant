"""Bake an original, transparent Mantaflow saucepan steam loop in Blender 4.5.

blender -b -t 8 --python chauffeur/tools/render_kitchen_steam.py -- scratch/kitchen-steam
"""
import bpy
import sys
from pathlib import Path
from mathutils import Vector

def fade_vapour():
    """Let the simulated vapor disappear into room air before the crop edges."""
    mat=bpy.data.materials['Soft pale water vapour'];n=mat.node_tree.nodes;l=mat.node_tree.links
    info=next(node for node in n if node.type=='VOLUME_INFO')
    density=next(node for node in n if node.type=='MATH' and node.inputs[1].default_value==8)
    glow=next(node for node in n if node.type=='MATH' and node.inputs[1].default_value==.25)
    tex=n.new('ShaderNodeTexCoord');xyz=n.new('ShaderNodeSeparateXYZ');l.new(tex.outputs['Generated'],xyz.inputs[0])
    height=n.new('ShaderNodeMapRange');height.interpolation_type='SMOOTHERSTEP'
    height.inputs['From Min'].default_value=.12;height.inputs['From Max'].default_value=.52
    height.inputs['To Min'].default_value=1;height.inputs['To Max'].default_value=0
    l.new(xyz.outputs['Z'],height.inputs['Value'])
    center=n.new('ShaderNodeMath');center.operation='SUBTRACT';center.inputs[1].default_value=.5;l.new(xyz.outputs['X'],center.inputs[0])
    distance=n.new('ShaderNodeMath');distance.operation='ABSOLUTE';l.new(center.outputs[0],distance.inputs[0])
    width=n.new('ShaderNodeMapRange');width.interpolation_type='SMOOTHERSTEP'
    width.inputs['From Min'].default_value=.13;width.inputs['From Max'].default_value=.34
    width.inputs['To Min'].default_value=1;width.inputs['To Max'].default_value=0;l.new(distance.outputs[0],width.inputs['Value'])
    vertical=n.new('ShaderNodeMath');vertical.operation='MULTIPLY';l.new(info.outputs['Density'],vertical.inputs[0]);l.new(height.outputs[0],vertical.inputs[1])
    faded=n.new('ShaderNodeMath');faded.operation='MULTIPLY';l.new(vertical.outputs[0],faded.inputs[0]);l.new(width.outputs[0],faded.inputs[1])
    l.new(faded.outputs[0],density.inputs[0]);l.new(faded.outputs[0],glow.inputs[0])

args=sys.argv[sys.argv.index('--')+1:]
out=Path(args[0]).resolve();out.mkdir(parents=True,exist_ok=True)
if '--refine-existing' in args:
    bpy.ops.wm.open_mainfile(filepath=str(out/'steam.blend'))
    fade_vapour()
    bpy.ops.wm.save_as_mainfile(filepath=str(out/'steam.blend'))
    s=bpy.context.scene
    prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
    for device in prefs.devices:device.use=device.type=='OPTIX'
    s.cycles.device='GPU'
    for frame in (64,112,160):
        s.frame_set(frame);s.render.filepath=str(out/f'preview-{frame:04}.png');bpy.ops.render.render(write_still=True)
    sys.exit(0)
if '--render-existing' in args:
    bpy.ops.wm.open_mainfile(filepath=str(out/'steam.blend'))
    s=bpy.context.scene
    prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
    for device in prefs.devices:device.use=device.type=='OPTIX'
    s.cycles.device='GPU'
    (out/'frames').mkdir(exist_ok=True)
    s.frame_start=49;s.frame_end=192;s.render.filepath=str(out/'frames/steam_')
    bpy.ops.render.render(animation=True)
    sys.exit(0)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.samples=256;s.cycles.use_denoising=True
s.cycles.use_adaptive_sampling=False
prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
for device in prefs.devices:device.use=device.type=='OPTIX'
s.cycles.device='GPU';s.render.threads_mode='FIXED';s.render.threads=8
s.render.resolution_x=384;s.render.resolution_y=576;s.render.resolution_percentage=100
s.render.fps=24;s.frame_start=1;s.frame_end=192;s.render.film_transparent=True
s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGBA'
s.view_settings.view_transform='Standard';s.world.use_nodes=True;s.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.3
bpy.ops.mesh.primitive_cube_add(size=1,location=(0,0,1.25))
domain=bpy.context.object;domain.name='Saucepan steam domain';domain.dimensions=(1.8,1.2,2.7)
bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
mod=domain.modifiers.new('Buoyant steam','FLUID');mod.fluid_type='DOMAIN';d=mod.domain_settings
d.domain_type='GAS';d.resolution_max=96;d.cache_type='MODULAR';d.cache_directory=str(out/'cache')
d.cache_frame_start=1;d.cache_frame_end=192;d.cache_data_format='OPENVDB';d.time_scale=.8
d.use_noise=False;d.use_adaptive_domain=False;d.use_dissolve_smoke=True;d.dissolve_speed=18;d.vorticity=.35
for side in ['front','back','left','right','top','bottom']:setattr(d,'use_collision_border_'+side,False)
mat=bpy.data.materials.new('Soft pale water vapour');mat.use_nodes=True;n=mat.node_tree.nodes;l=mat.node_tree.links;n.clear()
info=n.new('ShaderNodeVolumeInfo');volume=n.new('ShaderNodeVolumePrincipled');output=n.new('ShaderNodeOutputMaterial')
density=n.new('ShaderNodeMath');density.operation='MULTIPLY';density.inputs[1].default_value=8
l.new(info.outputs['Density'],density.inputs[0]);l.new(density.outputs[0],volume.inputs['Density'])
volume.inputs['Density Attribute'].default_value='';volume.inputs['Color'].default_value=(.92,.95,1,1)
volume.inputs['Emission Color'].default_value=(.8,.84,.9,1)
glow=n.new('ShaderNodeMath');glow.operation='MULTIPLY';glow.inputs[1].default_value=.25
l.new(info.outputs['Density'],glow.inputs[0]);l.new(glow.outputs[0],volume.inputs['Emission Strength'])
l.new(volume.outputs['Volume'],output.inputs['Volume']);domain.data.materials.append(mat)
fade_vapour()
# A thin ring represents vapour escaping around the lid, with evolving gaps.
bpy.ops.mesh.primitive_torus_add(major_radius=.24,minor_radius=.035,location=(0,0,.15))
source=bpy.context.object;source.name='Steam escaping lid rim';source.hide_render=True
flow=source.modifiers.new('Warm vapour','FLUID');flow.fluid_type='FLOW';f=flow.flow_settings
f.flow_type='SMOKE';f.flow_behavior='INFLOW';f.density=.5;f.temperature=1.1;f.surface_distance=1.5
f.use_initial_velocity=True;f.velocity_coord=(0,0,.1)
texture=bpy.data.textures.new('Changing rim emission',type='CLOUDS');texture.noise_scale=.2
f.use_texture=True;f.noise_texture=texture;f.texture_map_type='AUTO';f.texture_size=.5
for frame in [1,192]:f.texture_offset=frame*.012;f.keyframe_insert(data_path='texture_offset',frame=frame)
s.frame_set(1)
bpy.ops.object.camera_add(location=(0,-6,1.45));cam=bpy.context.object
cam.rotation_euler=(Vector((0,0,1.3))-cam.location).to_track_quat('-Z','Y').to_euler()
cam.data.type='ORTHO';cam.data.ortho_scale=2.6;s.camera=cam
bpy.ops.object.light_add(type='AREA',location=(-2,-3,3));bpy.context.object.data.energy=350;bpy.context.object.data.size=3
bpy.context.object.rotation_euler=(Vector((0,0,1))-bpy.context.object.location).to_track_quat('-Z','Y').to_euler()
# Filter the supersampled premultiplied RGBA in Blender. Cycles' color denoiser
# alone leaves stochastic volume coverage in alpha; this sub-display-pixel
# reconstruction removes that grain without a browser opacity multiplier.
s.use_nodes=True;nodes=s.node_tree.nodes;nodes.clear()
layers=nodes.new('CompositorNodeRLayers');blur=nodes.new('CompositorNodeBlur')
blur.filter_type='GAUSS';blur.size_x=2;blur.size_y=2
composite=nodes.new('CompositorNodeComposite')
s.node_tree.links.new(layers.outputs['Image'],blur.inputs['Image'])
s.node_tree.links.new(blur.outputs['Image'],composite.inputs['Image'])
bpy.ops.object.select_all(action='DESELECT');domain.select_set(True);bpy.context.view_layer.objects.active=domain
bpy.ops.wm.save_as_mainfile(filepath=str(out/'steam.blend'))
print('BAKE START',flush=True);bpy.ops.fluid.bake_data();print('BAKE DONE',flush=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out/'steam.blend'))
for frame in (64,112,160):
    s.frame_set(frame);s.render.filepath=str(out/f'preview-{frame:04}.png');bpy.ops.render.render(write_still=True)
print('PREVIEWS DONE; use --render-existing for the full loop',flush=True)
