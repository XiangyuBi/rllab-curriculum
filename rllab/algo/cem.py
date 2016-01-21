from rllab.algo.base import RLAlgorithm

import theano.tensor as TT
import numpy as np

from rllab.misc import autoargs
from rllab.misc.special import discount_cumsum
from rllab.sampler import parallel_sampler
from rllab.sampler.parallel_sampler import pool_map
from rllab.sampler.utils import rollout
import rllab.misc.logger as logger
import rllab.plotter as plotter

def sample_return(mdp, policy, params, max_path_length, discount):
    # mdp, policy, params, max_path_length, discount = args
    # of course we make the strong assumption that there is no race condition
    policy.set_param_values(params)
    path = rollout(
        mdp,
        policy,
        max_path_length,
    )
    path["returns"] = discount_cumsum(path["rewards"], discount)
    return dict(
        returns=path['returns']
    )


class CEM(RLAlgorithm):
    @autoargs.arg("n_itr", type=int,
                  help="Number of iterations.")
    @autoargs.arg("max_path_length", type=int,
                  help="Maximum length of a single rollout.")
    @autoargs.arg("discount", type=float,
                  help="Discount.")
    @autoargs.arg("whole_paths", type=bool,
                  help="Make sure that the samples contain whole "
                       "trajectories, even if the actual batch size is "
                       "slightly larger than the specified batch_size.")
    @autoargs.arg("init_std", type=float,
                  help="Initial std for param distribution")
    @autoargs.arg("extra_std", type=float,
                  help="Decaying std added to param distribution at each iteration")
    @autoargs.arg("extra_decay_time", type=int,
                  help="Iterations that it takes to decay extra std")
    @autoargs.arg("n_samples", type=int,
                  help="# of samples from param distribution")
    @autoargs.arg("best_frac", type=float,
                  help="Best fraction of the sampled params")
    @autoargs.arg("plot", type=bool,
                  help="Plot evaluation run after each iteration")
    def __init__(
            self,
            n_itr=500,
            max_path_length=500,
            discount=1.,
            whole_paths=True,
            init_std=1.,
            n_samples=100,
            best_frac=0.05,
            extra_std=1.,
            extra_decay_time=100,
            plot=False,
            **kwargs
    ):
        super(CEM, self).__init__(**kwargs)
        self.plot = plot
        self.extra_decay_time = extra_decay_time
        self.extra_std = extra_std
        self.best_frac = best_frac
        self.n_samples = n_samples
        self.init_std = init_std
        self.whole_paths = whole_paths
        self.discount = discount
        self.max_path_length = max_path_length
        self.n_itr = n_itr

    def train(self, mdp, policy, **kwargs):
        parallel_sampler.populate_task(mdp, policy)
        if self.plot:
            plotter.init_plot(mdp, policy)

        cur_std = self.init_std
        cur_mean = policy.get_param_values()
        K = cur_mean.size
        n_best = int(self.n_samples * self.best_frac)

        for itr in range(self.n_itr):
            # sample around the current distribution
            extra_var_mult = max(1.0 - itr / self.extra_decay_time, 0)
            sample_std = np.sqrt(np.square(cur_std) + np.square(self.extra_std) * extra_var_mult)
            xs = np.random.randn(self.n_samples, K) * sample_std.reshape(1, -1) + cur_mean.reshape(1, -1)
            infos = (pool_map(sample_return, [(x, self.max_path_length, self.discount) for x in xs]))
            fs = np.array([info['returns'][0] for info in infos])
            best_inds = (-fs).argsort()[:n_best]
            best_xs = xs[best_inds]
            cur_mean = best_xs.mean(axis=0)
            cur_std = best_xs.std(axis=0)
            best_x = best_xs[0]
            logger.push_prefix('itr #%d | ' % itr)
            logger.record_tabular('Iteration', itr)
            logger.record_tabular('CurStdMean', np.mean(cur_std))
            logger.record_tabular('AverageReturn',
                                  np.mean(fs))
            logger.record_tabular('StdReturn',
                                  np.std(fs))
            logger.record_tabular('MaxReturn',
                                  np.max(fs))
            logger.record_tabular('MinReturn',
                                  np.min(fs))
            logger.record_tabular('AvgTrajLen',
                                  np.mean([len(info['returns']) for info in infos]))
            policy.set_param_values(best_x)
            logger.save_itr_params(itr, dict(
                itr=itr,
                policy=policy,
                mdp=mdp,
                cur_mean=cur_mean,
                cur_std=cur_std,
            ))
            logger.dump_tabular(with_prefix=False)
            if self.plot:
                plotter.update_plot(policy, self.max_path_length)

