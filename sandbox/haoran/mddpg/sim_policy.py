from rllab.sampler.utils import rollout
from rllab.misc import tensor_utils
from rllab.envs.proxy_env import ProxyEnv
import argparse
import joblib
import uuid
import os
import random
import numpy as np
import tensorflow as tf
import time
import matplotlib.pyplot as plt


def rollout(sess,env, agent, exploration_strategy, qf, random=False,
    pause=False, max_path_length=np.inf, animated=False, speedup=1,
    optimal=False):
    observations = []
    actions = []
    rewards = []
    agent_infos = []
    env_infos = []
    o = env.reset()
    # agent.reset()
    agent.k = np.mod(agent.k + 1, agent.K)
    path_length = 0

    fig = plt.figure()
    ax_env = fig.add_subplot(211)
    ax_qf = fig.add_subplot(212)
    true_env = env
    while isinstance(true_env,ProxyEnv):
        true_env = true_env._wrapped_env
    true_env.fig = fig
    true_env.ax = ax_env
    if animated:
        env.render()

    def get_Q(o):
        xx = np.arange(-1,1,0.05)
        X,Y = np.meshgrid(xx,xx)
        all_actions = np.vstack([X.ravel(), Y.ravel()]).transpose()
        obs = np.array([o] * all_actions.shape[0])
        feed = {
            qf.observations_placeholder: obs,
            qf.actions_placeholder: all_actions
        }
        Q = sess.run(qf.output, feed).reshape(X.shape)
        return X,Y,Q

    while path_length < max_path_length:
        if optimal:
            X,Y,Q = get_Q(o)
            X = X.ravel()
            Y = Y.ravel()
            Q = Q.ravel()
            index = np.argmax(Q)
            a = np.array((X[index], Y[index]))
        else:
            if random:
                a = exploration_strategy.get_action(0, o, policy)
            else:
                a, agent_info = agent.get_action(o)
            print("head: %d"%(agent.k))
        print('action: ', a)

        agent_info = {}
        next_o, r, d, env_info = env.step(a)

        observations.append(env.observation_space.flatten(o))
        rewards.append(r)
        actions.append(env.action_space.flatten(a))
        agent_infos.append(agent_info)
        env_infos.append(env_info)
        path_length += 1
        if d:
            break
        if animated:
            env.render()
            # render the Q values
            X,Y,Q = get_Q(o)
            ax_qf.clear()
            contours = ax_qf.contour(X,Y,Q, 20)
            ax_qf.clabel(contours,inline=1,fontsize=10,fmt='%.0f')

            # current action
            a = a.ravel()
            ax_qf.plot(a[0],a[1],'r*')

            # all actions
            all_actions, agent_info = policy.get_action(o,k='all')
            for k, action in enumerate(all_actions[0]):
                x = action[0]
                y = action[1]
                ax_qf.plot(x,y,'*')
                ax_qf.text(x,y,'%d'%(k))


            plt.draw()
            timestep = 0.05
            plt.pause(timestep / speedup)
            if pause:
                input()
        o = next_o
    if animated:
        env.render(close=True)
    plt.close(fig)

    return dict(
        observations=tensor_utils.stack_tensor_list(observations),
        actions=tensor_utils.stack_tensor_list(actions),
        rewards=tensor_utils.stack_tensor_list(rewards),
        agent_infos=tensor_utils.stack_tensor_dict_list(agent_infos),
        env_infos=tensor_utils.stack_tensor_dict_list(env_infos),
    )

filename = str(uuid.uuid4())

if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument('file', type=str,
                        help='path to the snapshot file')
    parser.add_argument('--max_path_length', type=int, default=1000,
                        help='Max length of rollout')
    parser.add_argument('--speedup', type=float, default=1,
                        help='Speedup')
    parser.add_argument('--random', default=False,
        action='store_true')
    parser.add_argument('--pause', default=False,
        action='store_true')
    parser.add_argument('--optimal', default=False,
        action='store_true')
    args = parser.parse_args()

    policy = None
    env = None

    while True:
        with tf.Session() as sess:
            data = joblib.load(args.file)
            policy = data['policy']
            env = data['env']
            es = data['es']
            qf = data['qf']
            while True:
                try:
                    path = rollout(
                        sess,
                        env,
                        policy,
                        es,
                        qf,
                        pause=args.pause,
                        optimal=args.optimal,
                        max_path_length=args.max_path_length,
                        animated=True,
                        speedup=args.speedup,
                    )

                # Hack for now. Not sure why rollout assumes that close is an
                # keyword argument
                except TypeError as e:
                    if (str(e) != "render() got an unexpected keyword "
                                  "argument 'close'"):
                        raise e
