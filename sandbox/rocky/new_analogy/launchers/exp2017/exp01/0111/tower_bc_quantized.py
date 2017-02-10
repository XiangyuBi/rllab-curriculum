import pickle

from rllab.misc import logger
from rllab.misc.instrument import run_experiment_lite, variant, VariantGenerator
from sandbox.rocky.cirrascale.launch_job import launch_cirrascale
from sandbox.rocky.tf.envs.base import TfEnv

# MODE = "local_docker"  # _docker"  # _docker"
# # MODE = launch_cirrascale("pascal")
# N_PARALLEL = 8

# MODE = "local_docker"#_docker"  # _docker"
MODE = launch_cirrascale("pascal")
N_PARALLEL = 1#8

class VG(VariantGenerator):
    @variant
    def seed(self):
        return [11, 21, 31, 41, 51]#22, 33, 44, 55]
        # return [11]


def run_task(vv):
    from gpr_package.bin import tower_copter_policy as tower
    from sandbox.rocky.new_analogy.envs.gpr_env import GprEnv
    import tensorflow as tf
    from sandbox.rocky.new_analogy.tf.algos import Trainer
    from sandbox.rocky.s3.resource_manager import resource_manager

    with tf.Session() as sess:
        logger.log("Loading data...")
        file_name = resource_manager.get_file("tower_copter_paths_ab")
        with open(file_name, 'rb') as f:
            paths = pickle.load(f)
        logger.log("Loaded")

        task_id = tower.get_task_from_text("ab")
        # expr = tower.Experiment(2, 1000)

        env = TfEnv(GprEnv("tower", task_id=task_id, experiment_args=dict(nboxes=2, horizon=1000)))

        # policy = GaussianMLPPolicy(
        #     env_spec=env.spec,
        #     hidden_sizes=(64, 64),  # 256, 256, 256),
        #     hidden_nonlinearity=tf.nn.tanh,
        #     name="policy"
        # )
        # policy = NormalizingPolicy(wrapped_policy=policy, paths=paths, normalize_obs=True, normalize_actions=True)

        algo = Trainer(
            env=env,
            # policy=policy,
            paths=paths,
            n_epochs=1000,
            evaluate_performance=True,  # False,
            train_ratio=0.9,
            max_path_length=1000,
            n_eval_trajs=10,
            eval_batch_size=10000,
            n_eval_envs=1,
        )

        algo.train(sess=sess)


variants = VG().variants()

print("#Experiments:", len(variants))

for v in variants:

    kwargs = dict(
        use_cloudpickle=True,
        exp_prefix="tower-bc-quantized",
        mode=MODE,
        use_gpu=True,
        snapshot_mode="last",
        sync_all_data_node_to_s3=False,
        n_parallel=N_PARALLEL,
        env=dict(CUDA_VISIBLE_DEVICES="0", PYTHONPATH="/root/code/rllab:/root/code/rllab/gpr_package"),
        variant=v,
        seed=v["seed"],
    )

    if MODE == "local":
        del kwargs["env"]["PYTHONPATH"]  # =
    else:
        kwargs = dict(
            kwargs,
            docker_image="quay.io/openai/rocky-rllab3-gpr-gpu-pascal:20170111",
            docker_args=" -v /home/rocky/conopt-shared-data:/shared-data",
        )

    run_experiment_lite(
        run_task,
        **kwargs
    )