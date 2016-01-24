import lasagne.layers as L
import lasagne.nonlinearities as NL
import lasagne
import numpy as np
import theano
import theano.tensor as TT
from pydoc import locate
from rllab.core.lasagne_layers import ParamLayer
from rllab.core.lasagne_powered import LasagnePowered
# from rllab.core.lasagne_layers import batch_norm
from rllab.core.serializable import Serializable
from rllab.policy.base import StochasticPolicy
from rllab.misc.overrides import overrides
from rllab.misc import logger
from rllab.misc import autoargs
from rllab.sampler import parallel_sampler


PG = parallel_sampler.G


def log_normal_pdf(x, mean, log_std):
    normalized = (x - mean) / TT.exp(log_std)
    return -0.5*TT.square(normalized) - np.log((2*np.pi)**0.5) - log_std


def worker_collect_stats(action_dim):
    pdists = PG.samples_data["pdists"]
    log_stds = pdists[:, action_dim:]
    return np.mean(np.exp(log_stds))


class MeanStdNNPolicy(StochasticPolicy, LasagnePowered, Serializable):

    @autoargs.arg('hidden_sizes', type=int, nargs='*',
                  help='list of sizes for the fully-connected hidden layers')
    @autoargs.arg('std_sizes', type=int, nargs='*',
                  help='list of sizes for the fully-connected layers for std, note'
                       'there is a difference in semantics than above: here an empty'
                       'list means that std is independent of input')
    @autoargs.arg('initial_std', type=float,
                  help='Initial std')
    @autoargs.arg('std_trainable', type=bool,
                  help='Is std trainable')
    @autoargs.arg('output_nl', type=str,
                  help='nonlinearity for the output layer')
    @autoargs.arg('nonlinearity', type=str,
                  help='nonlinearity used for each hidden layer, can be one '
                       'of tanh, sigmoid')
    @autoargs.arg('bn', type=bool,
                  help='whether to apply batch normalization to hidden layers')
    # pylint: disable=dangerous-default-value
    def __init__(
            self,
            mdp,
            hidden_sizes=(32, 32),
            std_sizes=tuple(),
            initial_std=1,
            std_trainable=True,
            nonlinearity='lasagne.nonlinearities.tanh',
            output_nl='None',
            bn=False,
            ):
        # pylint: enable=dangerous-default-value
        # create network
        if isinstance(nonlinearity, str):
            nonlinearity = locate(nonlinearity)
        input_var = TT.matrix('input')
        l_input = L.InputLayer(shape=(None, mdp.observation_shape[0]),
                               input_var=input_var)
        l_hidden = l_input
        for idx, hidden_size in enumerate(hidden_sizes):
            l_hidden = L.DenseLayer(
                l_hidden,
                num_units=hidden_size,
                nonlinearity=nonlinearity,
                W=lasagne.init.Normal(0.1),
                name="h%d" % idx)
            if bn:
                l_hidden = L.batch_norm(l_hidden)
        mean_layer = L.DenseLayer(
            l_hidden,
            num_units=mdp.action_dim,
            nonlinearity=eval(output_nl),
            W=lasagne.init.Normal(0.01),
            name="output_mean")

        assert std_trainable or (len(std_sizes) == 0)

        if len(std_sizes) == 0:
            log_std_layer = ParamLayer(
                l_input,
                num_units=mdp.action_dim,
                param=lasagne.init.Constant(np.log(initial_std)),
                name="output_log_std",
                trainable=std_trainable,
            )
        else:
            hidden_log_std_layer = l_input
            for idx, hidden_size in enumerate(std_sizes[:-1]):
                hidden_log_std_layer = L.DenseLayer(
                    hidden_log_std_layer,
                    num_units=hidden_size,
                    nonlinearity=nonlinearity,
                    W=lasagne.init.Normal(0.1),
                    name="std h%d" % idx)
            log_std_layer = L.DenseLayer(
                hidden_log_std_layer,
                num_units=mdp.action_dim,
                nonlinearity=NL.identity,
                W=lasagne.init.Normal(0.1),
                name="output_log_std")
        mean_var = L.get_output(mean_layer)
        log_std_var = L.get_output(log_std_layer)

        self._mean_layer = mean_layer
        self._log_std_layer = log_std_layer
        self._compute_action_params = theano.function(
            [input_var],
            [mean_var, log_std_var],
            allow_input_downcast=True
        )

        super(MeanStdNNPolicy, self).__init__(mdp)
        LasagnePowered.__init__(self, [mean_layer, log_std_layer])
        Serializable.__init__(
            self, mdp=mdp, hidden_sizes=hidden_sizes,
            nonlinearity=nonlinearity, output_nl=output_nl, bn=bn)

    def get_pdist_sym(self, input_var):
        mean_var = L.get_output(self._mean_layer, input_var)
        log_std_var = L.get_output(self._log_std_layer, input_var)
        return TT.concatenate([mean_var, log_std_var], axis=1)

    # Computes D_KL(p_old || p_new)
    @overrides
    def kl(self, old_pdist_var, new_pdist_var):
        old_mean, old_log_std = self._split_pdist(old_pdist_var)
        new_mean, new_log_std = self._split_pdist(new_pdist_var)
        old_std = TT.exp(old_log_std)
        new_std = TT.exp(new_log_std)
        # mean: (N*A)
        # std: (N*A)
        # formula:
        # { (\mu_1 - \mu_2)^2 + \sigma_1^2 - \sigma_2^2 } / (2\sigma_2^2) +
        # ln(\sigma_2/\sigma_1)
        numerator = TT.square(old_mean - new_mean) + \
            TT.square(old_std) - TT.square(new_std)
        denominator = 2*TT.square(new_std) + 1e-8
        return TT.sum(
            numerator / denominator + new_log_std - old_log_std, axis=1)

    @overrides
    def likelihood_ratio(self, old_pdist_var, new_pdist_var, action_var):
        old_mean, old_log_std = self._split_pdist(old_pdist_var)
        new_mean, new_log_std = self._split_pdist(new_pdist_var)
        logli_new = log_normal_pdf(action_var, new_mean, new_log_std)
        logli_old = log_normal_pdf(action_var, old_mean, old_log_std)
        return TT.exp(TT.sum(logli_new - logli_old, axis=1))

    def _split_pdist(self, pdist):
        mean = pdist[:, :self.action_dim]
        log_std = pdist[:, self.action_dim:]
        return mean, log_std

    @overrides
    def compute_entropy(self, pdist):
        _, log_std = self._split_pdist(pdist)
        return np.mean(np.sum(log_std + np.log(np.sqrt(2*np.pi*np.e)), axis=1))

    # The return value is a pair. The first item is a matrix (N, A), where each
    # entry corresponds to the action value taken. The second item is a vector
    # of length N, where each entry is the density value for that action, under
    # the current policy
    @overrides
    def get_actions(self, observations):
        means, log_stds = self._compute_action_params(observations)
        # first get standard normal samples
        rnd = np.random.randn(*means.shape)
        pdists = np.concatenate([means, log_stds], axis=1)
        # transform back to the true distribution
        actions = rnd * np.exp(log_stds) + means
        return actions, pdists

    @overrides
    def get_action(self, observation):
        actions, pdists = self.get_actions([observation])
        return actions[0], pdists[0]

    def get_reparam_action_sym(self, obs_var, eta_var):
        means, log_stds = self._split_pdist(self.get_pdist_sym(obs_var))
        return eta_var * TT.exp(log_stds) + means

    def infer_eta(self, pdists, actions):
        means, log_stds = self._split_pdist(pdists)
        return (actions - means) / np.exp(log_stds)

    def get_log_prob_sym(self, input_var, action_var):
        mean_var = L.get_output(self._mean_layer, input_var)
        log_std_var = L.get_output(self._log_std_layer, input_var)
        stdn = (action_var - mean_var)
        stdn /= TT.exp(log_std_var)
        return - TT.sum(log_std_var, axis=1) - \
            0.5*TT.sum(TT.square(stdn), axis=1) - \
            0.5*self.action_dim*np.log(2*np.pi)

    def log_extra(self):
        stds = parallel_sampler.run_map(worker_collect_stats, self.action_dim)
        logger.record_tabular('AveragePolicyStd', np.mean(stds))

