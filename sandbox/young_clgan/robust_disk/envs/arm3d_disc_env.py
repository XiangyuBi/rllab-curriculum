import random

import numpy as np

from rllab.core.serializable import Serializable
from rllab.envs.base import Step
from rllab.envs.mujoco.mujoco_env import MujocoEnv
from rllab.misc import autoargs
from rllab.misc import logger
from rllab.spaces.box import Box
from rllab.misc.overrides import overrides
from contextlib import contextmanager


class Arm3dDiscEnv(MujocoEnv, Serializable):
    FILE = "arm3d_disc.xml"

    def __init__(self,
                 init_solved=True,
                 kill_radius=0.4,
                 action_penalty = False,
                 action_torque_lambda = 1,
                 random_torques = False,
                 *args, **kwargs):
        MujocoEnv.__init__(self, *args, **kwargs)
        Serializable.quick_init(self, locals())

        # self.init_qvel = np.zeros_like(self.init_qvel)
        # self.init_qacc = np.zeros_like(self.init_qacc)
        self.init_solved = init_solved
        self.kill_radius = kill_radius
        self.kill_outside = False
        self.action_penalty = action_penalty
        self.action_torque_lambda = action_torque_lambda
        self.random_torques = random_torques
        if self.random_torques:
            import random
        # print("yo!")


    @overrides
    def get_current_obs(self):
        return np.concatenate([
            self.model.data.qpos.flat[:-2], #[:self.model.nq // 2],
            self.model.data.qvel.flat[:-2], #[:self.model.nq // 2],
            # self.model.data.site_xpos[0], # disc position
        ])

    @contextmanager
    def set_kill_outside(self, kill_outside=True, radius=None):
        self.kill_outside = True
        old_kill_radius = self.kill_radius
        if radius is not None:
            self.kill_radius = radius
        try:
            yield
        finally:
            self.kill_outside = False
            self.kill_radius = old_kill_radius

    @property
    def start_observation(self):
        return np.copy(self.model.data.qpos).flatten()

    def reset(self, init_state=None, *args, **kwargs):
        # init_state = (0.387, 1.137, -2.028, -1.744, 2.029, -0.873, 1.55, 0, 0) # TODO: used for debugging only!
        ret = super(Arm3dDiscEnv, self).reset(init_state, *args, **kwargs)
        # self.current_goal = self.model.data.geom_xpos[-1][:2]
        # print(self.current_goal) # I think this is the location of the peg
        return ret

    def step(self, action):
        # action = np.zeros_like(action)
        # print(action.shape)
        self.forward_dynamics(action)
        distance_to_goal = self.get_distance_to_goal()
        action_norm = np.linalg.norm(action)
        velocity_norm = np.linalg.norm(self.model.data.qvel)
        if self.action_penalty:
            reward = -(self.action_torque_lambda * action_norm + velocity_norm)
        else: # I don't think this even matters
            reward = -distance_to_goal
        # print(self.model.data.site_xpos[1])
        # print(self.model.data.qpos[-2:])
        # peg should not move
        # print(self.model.data.xfrc_applied)
        curr_qvel = list(self.model.data.qvel)
        curr_qvel[-2] = 0
        curr_qvel[-1] = 0
        self.model.data.qvel = curr_qvel

        if self.random_torques:
            xfrc = np.zeros(self.model.data.xfrc_applied.shape)

            torque_applied = random.uniform(-1, 1)
            self.joint = random.randint(0, 6) # inclusive
            self.coord = random.randint(0, 5)
            xfrc[self.joint, self.coord] = torque_applied
            self.model.data.xfrc_applied = xfrc

        # if distance_to_goal < 0.03:
        #     print("inside the PR2DiscEnv, the dist is: {}, goal_pos is: {}".format(distance_to_goal, self.get_goal_position()))
            # print("Qpos: " + str(self.model.data.qpos))

        # print(distance_to_goal)
        ob = self.get_current_obs()
        # print(ob)
        done = False

        if self.kill_outside and (distance_to_goal > self.kill_radius):
            print("******** OUT of region ********")
            done = True

        return Step(
            ob, reward, done, distance=distance_to_goal, action_norm=action_norm, velocity_norm=velocity_norm,
        )


    def get_disc_position(self):
        return self.model.data.site_xpos[0]

    # this allows position to be changed todo: check this whenever goal is changing / no reward for reaching goal
    def get_goal_position(self):
        # return self.model.data.site_xpos[1]
        return self.model.data.xpos[-1] + np.array([0, 0, 0.05])

    def get_vec_to_goal(self):
        disc_pos = self.get_disc_position()
        goal_pos = self.get_goal_position()
        return disc_pos - goal_pos # note: great place for breakpoint!

    def get_distance_to_goal(self):
        vec_to_goal = self.get_vec_to_goal()
        return np.linalg.norm(vec_to_goal)


    def set_state(self, qpos, qvel):
        #assert qpos.shape == (self.model.nq, 1) and qvel.shape == (self.model.nv, 1)
        self.model.data.qpos = qpos
        self.model.data.qvel = qvel
        # self.model._compute_subtree() #pylint: disable=W0212
        self.model.forward()

    # want to get some idea of action_norm and velocity_norm

    def log_diagnostics(self, paths):
        action_norms = [path["env_infos"]["action_norm"] for path in paths]
        logger.record_tabular('dist_x', np.mean([np.mean(d) for d in action_norms]))

        velocity_norms = [path["env_infos"]["velocity_norm"] for path in paths]
        logger.record_tabular('dist_x', np.mean([np.mean(d) for d in velocity_norms]))
        
    # def is_feasible(self, goal):
    #     return np.all(np.logical_and(self.goal_lb <= goal, goal <= self.goal_ub))
    #
    # @property
    # def goal_lb(self):
    #     return self.model.jnt_range[:self.model.nq // 2, 0]
    #
    # @property
    # def goal_ub(self):
    #     return self.model.jnt_range[:self.model.nq // 2, 1]
    #
    # @property
    # def goal_dim(self):
    #     return self.model.njnt // 2