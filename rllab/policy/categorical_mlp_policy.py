import lasagne.layers as L
import lasagne.nonlinearities as NL
import numpy as np
import theano.tensor.nnet
from rllab.core.lasagne_powered import LasagnePowered
from rllab.core.network import MLP
from rllab.core.serializable import Serializable
from rllab.misc.overrides import overrides
from rllab.misc import special
from rllab.misc import ext
from rllab.policy.base import StochasticPolicy
from rllab.misc import categorical_dist


class CategoricalMLPPolicy(StochasticPolicy, LasagnePowered, Serializable):

    def __init__(
            self,
            mdp_spec,
            hidden_sizes=(32, 32),
            nonlinearity=NL.rectify):
        """
        :param mdp_spec: A spec for the mdp.
        :param hidden_sizes: list of sizes for the fully connected hidden layers
        :param nonlinearity: nonlinearity used for each hidden layer
        :return:
        """
        Serializable.quick_init(self, locals())

        log_prob_network = MLP(
            input_shape=mdp_spec.observation_shape,
            output_dim=mdp_spec.action_dim,
            hidden_sizes=hidden_sizes,
            nonlinearity=nonlinearity,
            output_nonlinearity=theano.tensor.nnet.logsoftmax,
        )

        self._l_log_prob = log_prob_network.output_layer
        self._l_obs = log_prob_network.input_layer
        self._f_log_prob = ext.compile_function([log_prob_network.input_layer.input_var], L.get_output(
            log_prob_network.output_layer))

        super(CategoricalMLPPolicy, self).__init__(mdp_spec)
        LasagnePowered.__init__(self, [log_prob_network.output_layer])

    @overrides
    def get_pdist_sym(self, obs_var, action_var):
        return L.get_output(self._l_log_prob, {self._l_obs: obs_var})

    @overrides
    def kl(self, old_log_prob_var, new_log_prob_var):
        return categorical_dist.kl_sym(old_log_prob_var, new_log_prob_var)

    @overrides
    def likelihood_ratio(self, old_log_prob_var, new_log_prob_var, action_var):
        return categorical_dist.likelihood_ratio_sym(
            action_var, old_log_prob_var, new_log_prob_var)

    @overrides
    def compute_entropy(self, pdist):
        return np.mean(categorical_dist.entropy(pdist))

    def get_pdists(self, observations):
        return self._f_log_prob(observations)

    @property
    @overrides
    def pdist_dim(self):
        return self.action_dim

    # The return value is a pair. The first item is a matrix (N, A), where each
    # entry corresponds to the action value taken. The second item is a vector
    # of length N, where each entry is the density value for that action, under
    # the current policy
    @overrides
    def get_action(self, observation):
        log_prob = self._f_log_prob([observation])
        action = special.weighted_sample(np.exp(log_prob), xrange(self.action_dim))
        return special.to_onehot(action, self.action_dim), log_prob
