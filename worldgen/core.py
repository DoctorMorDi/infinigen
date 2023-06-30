import random
import cProfile
import logging
from functools import partial
import pprint



import mathutils
from mathutils import Vector
from numpy.random import uniform, normal, randint
from tqdm import tqdm

from placement import placement, density, camera as cam_util
from placement.split_in_view import split_inview

from assets.trees.generate import TreeFactory, BushFactory, random_season, random_leaf_collection
from assets import boulder
from assets.glowing_rocks import GlowingRocksFactory
from assets.creatures import CarnivoreFactory, HerbivoreFactory, FishFactory, FishSchoolFactory, \
    BeetleFactory, AntSwarmFactory, BirdFactory, SnakeFactory, \
    CrustaceanFactory, FlyingBirdFactory, CrabFactory, LobsterFactory, SpinyLobsterFactory
from assets.insects.assembled.dragonfly import DragonflyFactory
from assets.cloud.generate import CloudFactory
from assets.creatures import boid_swarm
from placement import placement, camera as cam_util
from rendering.resample import resample_scene
from surfaces import surface

import surfaces.scatters
from surfaces.scatters import ground_mushroom, slime_mold, moss, ivy, lichen, snow_layer


from placement.factory import make_asset_collection
from util import blender as butil
from util.math import FixedSeed, int_hash
from util.pipeline import RandomStageExecutor
from util.random import sample_registry
   
@gin.configurable
def populate_scene(
    output_folder, terrain, scene_seed, **params
):
    p = RandomStageExecutor(scene_seed, output_folder, params)
    camera = bpy.context.scene.camera

    season = p.run_stage('choose_season', random_season, use_chance=False, default=[])

    populated = {}
    populated['trees'] = p.run_stage('populate_trees', use_chance=False, default=[],
        fn=lambda: placement.populate_all(TreeFactory, camera, season=season, vis_cull=4, dist_cull=70))#,
                                        #meshing_camera=camera, adapt_mesh_method='subdivide', cam_meshing_max_dist=8)) 
    populated['boulders'] = p.run_stage('populate_boulders', use_chance=False, default=[],
        fn=lambda: placement.populate_all(boulder.BoulderFactory, camera, vis_cull=3, dist_cull=70))#,
                                        #meshing_camera=camera, adapt_mesh_method='subdivide', cam_meshing_max_dist=8))
    p.run_stage('populate_bushes', use_chance=False,
        fn=lambda: placement.populate_all(BushFactory, camera, vis_cull=1, adapt_mesh_method='subdivide'))
    p.run_stage('populate_kelp', use_chance=False,
        fn=lambda: placement.populate_all(kelp.KelpMonocotFactory, camera, vis_cull=5))
    p.run_stage('populate_cactus', use_chance=False,
        fn=lambda: placement.populate_all(CactusFactory, camera, vis_cull=6))
    p.run_stage('populate_clouds', use_chance=False,
        fn=lambda: placement.populate_all(CloudFactory, camera, dist_cull=None, vis_cull=None))
    p.run_stage('populate_glowing_rocks', use_chance=False,
        fn=lambda: placement.populate_all(GlowingRocksFactory, camera, dist_cull=None, vis_cull=None))
    
    grime_selection_funcs = {
    }
    grime_types = {
        'slime_mold': slime_mold.SlimeMold,
        'lichen': lichen.Lichen,
        'ivy': ivy.Ivy,
        'mushroom': ground_mushroom.Mushrooms,
        'moss': moss.MossCover
    }
    def apply_grime(grime_type, surface_cls):
        surface_fac = surface_cls()
        for target_type, results, in populated.items():
            selection_func = grime_selection_funcs.get(target_type, None)
            for fac_seed, fac_pholders, fac_assets in results:
                if len(fac_pholders) == 0:
                    continue
                for inst_seed, obj in fac_assets:
                    with FixedSeed(int_hash((grime_type, fac_seed, inst_seed))):
                        p_k = f'{grime_type}_on_{target_type}_per_instance_chance'
                        if uniform() > params.get(p_k, 0.4):
                            continue
                        logging.debug(f'Applying {surface_fac} on {obj}')
                        surface_fac.apply(obj, selection=selection_func)
    for grime_type, surface_cls in grime_types.items():
        p.run_stage(grime_type, lambda: apply_grime(grime_type, surface_cls))

    def apply_snow_layer(surface_cls):
        surface_fac = surface_cls()
        for target_type, results, in populated.items():
            selection_func = grime_selection_funcs.get(target_type, None)
            for fac_seed, fac_pholders, fac_assets in results:
                if len(fac_pholders) == 0:
                    continue
                for inst_seed, obj in fac_assets:
                    tmp = obj.users_collection[0].hide_viewport
                    obj.users_collection[0].hide_viewport = False
                    surface_fac.apply(obj, selection=selection_func)
                    obj.users_collection[0].hide_viewport = tmp
    p.run_stage("snow_layer", lambda: apply_snow_layer(snow_layer.Snowlayer))

    creature_facs = {
        'carnivore': CarnivoreFactory, 'herbivore': HerbivoreFactory,
        'bird': BirdFactory, 'fish': FishFactory, 'snake': SnakeFactory,
        'beetles': BeetleFactory, 
        'flyingbird': FlyingBirdFactory, 'dragonfly': DragonflyFactory,
        'crab': CrabFactory, 'crustacean': CrustaceanFactory
    }
    for k, fac in creature_facs.items():
        p.run_stage(f'populate_{k}', use_chance=False,
            fn=lambda: placement.populate_all(fac, camera=None))

    p.save_results(output_folder/'pipeline_fine.csv')

def get_scene_tag(name):
    try:
        o = next(o for o in bpy.data.objects if o.name.startswith(f'{name}='))
        return o.name.split('=')[-1].strip('\'\"')
    except StopIteration:
        return None
def render(scene_seed, output_folder, camera_id, render_image_func=render_image, resample_idx=None):
    if resample_idx is not None and resample_idx != 0:
        resample_scene(int_hash((scene_seed, resample_idx)))
        render_image_func(frames_folder=Path(output_folder), camera_id=camera_id)
def save_meshes(scene_seed, output_folder, frame_range, camera_id, resample_idx=False):
    
    if resample_idx is not None and resample_idx > 0:
        resample_scene(int_hash((scene_seed, resample_idx)))
        frame_info_folder = Path(output_folder) / f"frame_{frame_idx:04d}"
        logging.info(f"Working on frame {frame_idx}")
def validate_version(scene_version):
    if scene_version is None or scene_version.split('.')[:-1] != VERSION.split('.')[:-1]:
        raise ValueError(
            f'generate.py {VERSION=} attempted to load a scene created by version {scene_version=}')
    if scene_version != VERSION:
        logging.warning(f'Worldgen {VERSION=} has minor version mismatch with {scene_version=}')
@gin.configurable
def group_collections(config):
    for config in config: # Group collections before fine runs
        butil.group_in_collection([o for o in bpy.data.objects if o.name.startswith(f'{config["name"]}:')], config["name"])
        butil.group_toplevel_collections(config['name'], hide_viewport=config['hide_viewport'], hide_render=config['hide_render'])

@gin.configurable
def execute_tasks(
    compose_scene_func,
    input_folder, output_folder,
    task, scene_seed,
    frame_range, camera_id,
    resample_idx=None,
    output_blend_name="scene.blend",
):
        with Timer('Reading input blendfile'):
            bpy.ops.wm.open_mainfile(filepath=str(input_folder / 'scene.blend'))
        scene_version = get_scene_tag('VERSION')
        butil.approve_all_drivers()
    if frame_range[1] < frame_range[0]:
        raise ValueError(f'{frame_range=} is invalid, frame range must be nonempty. Blender end frame is INCLUSIVE')

    logging.info(f'Processing frames {frame_range[0]} through {frame_range[1]} inclusive')
    bpy.context.scene.frame_start = int(frame_range[0])
    bpy.context.scene.frame_end = int(frame_range[1])
    bpy.context.scene.frame_set(int(frame_range[0]))
    bpy.context.view_layer.update()

    surface.registry.initialize_from_gin()
    bpy.ops.preferences.addon_enable(module='ant_landscape')
    bpy.context.preferences.system.scrollback = 0 
    bpy.context.preferences.edit.undo_steps = 0
    bpy.context.scene.render.resolution_x = generate_resolution[0]
    bpy.context.scene.render.resolution_y = generate_resolution[1]
    bpy.context.scene.render.engine = 'CYCLES'
    bpy.context.scene.cycles.device = 'GPU'

    bpy.context.scene.cycles.volume_step_rate = 0.1
    bpy.context.scene.cycles.volume_preview_step_rate = 0.1
    bpy.context.scene.cycles.volume_max_steps = 32

    if Task.Coarse in task or Task.FineTerrain in task or Task.Fine in task or Task.Populate in task:
        butil.clear_scene(targets=[bpy.data.objects])
        butil.spawn_empty(f'{VERSION=}')
        compose_scene_func(output_folder, terrain, scene_seed)

    group_collections()

    if Task.Populate in task:
        populate_scene(output_folder, terrain, scene_seed)
    if Task.Fine in task:
        raise RuntimeError(f'{task=} contains deprecated {Task.Fine=}')

    
    group_collections()
    if Task.Coarse in task or Task.Populate in task or Task.FineTerrain in task:
        bpy.context.preferences.system.scrollback = 100 
        bpy.context.preferences.edit.undo_steps = 100
        with (output_folder/ "version.txt").open('w') as f:
            scene_version = get_scene_tag('VERSION')
            f.write(f"{scene_version}\n")

        with (output_folder/'polycounts.txt').open('w') as f:
            save_polycounts(f)
    for col in bpy.data.collections['unique_assets'].children:
        col.hide_viewport = False

        render(scene_seed, output_folder=output_folder, camera_id=camera_id, resample_idx=resample_idx)
        save_meshes(scene_seed, output_folder=output_folder, frame_range=frame_range, camera_id=camera_id)

def determine_scene_seed(args):
    if args.seed is None:
        if Task.Coarse not in args.task:
            raise ValueError(
                f'Running tasks on an already generated scene, you need to specify --seed or results will'
                f' not be view-consistent')
        return randint(1e7), 'chosen at random'

    # WARNING: Do not add support for decimal numbers here, it will cause ambiguity, as some hex numbers are valid decimals

        return int(args.seed, 16), 'parsed as hexadecimal'
        pass

    return int_hash(args.seed), 'hashed string to integer'

def apply_scene_seed(args):
    scene_seed, reason = determine_scene_seed(args)
    logging.info(f'Converted {args.seed=} to {scene_seed=}, {reason}')
    gin.constant('OVERALL_SEED', scene_seed)
    del args.seed

    random.seed(scene_seed)
    np.random.seed(scene_seed)
    return scene_seed

def apply_gin_configs(args, scene_seed, skip_unknown=False):
    scene_types = [p.stem for p in Path('config/scene_types').iterdir()]
    weights = {
        "kelp_forest": 0.3,
        "coral_reef": 1,
        "forest": 2,
        "river": 2,
        "desert": 1,
        "coast": 1,
        "cave": 1,
        "mountain": 1,
        "canyon": 1,
        "plain": 1,
        "cliff": 1,
        "arctic": 1,
        "snowy_mountain": 1,
    }
    assert all(k in scene_types for k in weights)

    scene_types = [s for s in scene_types if s in weights]
    weights = np.array([weights[k] for k in scene_types], dtype=float)
    weights /= weights.sum()

        scene_type = np.random.RandomState(scene_seed).choice(scene_types, p=weights)
        logging.warning(f'Randomly selected {scene_type=}. IF THIS IS NOT INTENDED THEN YOU ARE MISSING SCENE CONFIGS')
    def find_config(g):
        as_scene_type = f'config/scene_types/{g}.gin'
        if os.path.exists(as_scene_type):
            return as_scene_type
        as_base = f'config/{g}.gin'
        if os.path.exists(as_base):
            return as_base
        raise ValueError(f'Couldn not locate {g} in either config/ or config/scene_types')
    confs = [find_config(g) for g in ['base'] + args.gin_config]
    gin.parse_config_files_and_bindings(confs, bindings=bindings, skip_unknown=skip_unknown)
def main(
    input_folder, 
    output_folder,
    scene_seed,
    task, 
    task_uniqname,
    **kwargs
):
    
    version_req = ['3.3.1']
    assert bpy.app.version_string in version_req, f'You are using blender={bpy.app.version_string} which is ' \
                                                  f'not supported. Please use {version_req}'
    logging.info(f'infinigen version {VERSION}')
    logging.info(f"CUDA_VISIBLE_DEVICES={os.environ.get('CUDA_VISIBLE_DEVICES')}")

    if input_folder is not None:
        input_folder = Path(input_folder).absolute()
    output_folder = Path(output_folder).absolute()
    output_folder.mkdir(exist_ok=True, parents=True)

    if task_uniqname is not None:
        create_text_file(filename=f"START_{task_uniqname}")

    with Timer('MAIN TOTAL'):
        execute_tasks(
            input_folder=input_folder, output_folder=output_folder,
            task=task, scene_seed=scene_seed, **kwargs
        )

    if task_uniqname is not None:
        create_text_file(filename=f"FINISH_{task_uniqname}")
        create_text_file(filename=f"operative_gin_{task_uniqname}.txt", text=gin.operative_config_str())
