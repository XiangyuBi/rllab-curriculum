from rllab.misc import ext
from rllab.misc import krylov
from rllab.misc import logger
from rllab.core.serializable import Serializable
import theano.tensor as TT
import theano
import numpy as np
import multiprocessing as mp
from rllab.misc.ext import sliced_fun
from sandbox.adam.parallel.util import SimpleContainer


class ParallelPerlmutterHvp(Serializable):
    """
    Only difference from serial is the function defined within build_eval().
    """

    def __init__(self, num_slices=1):
        Serializable.quick_init(self, locals())
        self.target = None
        self.reg_coeff = None
        self.opt_fun = None
        self._num_slices = num_slices
        self._par_data = None  # objects for parallelism, to be populated
        self._shareds = None
        self._mgr_objs = None

    def update_opt(self, f, target, inputs, reg_coeff):
        self.target = target
        self.reg_coeff = reg_coeff
        params = target.get_params(trainable=True)

        constraint_grads = theano.grad(
            f, wrt=params, disconnected_inputs='warn')
        xs = tuple([ext.new_tensor_like("%s x" % p.name, p) for p in params])

        def Hx_plain():
            Hx_plain_splits = TT.grad(
                TT.sum([TT.sum(g * x)
                        for g, x in zip(constraint_grads, xs)]),
                wrt=params,
                disconnected_inputs='warn'
            )
            return TT.concatenate([TT.flatten(s) for s in Hx_plain_splits])

        self.opt_fun = ext.lazydict(
            f_Hx_plain=lambda: ext.compile_function(
                inputs=inputs + xs,
                outputs=Hx_plain(),
                log_name="f_Hx_plain",
            ),
        )

    def build_eval(self, inputs):
        def parallel_eval(x):
            """
            This function is parallelized.
            """
            par_data, shareds, mgr_objs = self._par_objs

            xs = tuple(self.target.flat_to_params(x, trainable=True))

            shareds.grads_2d[:, par_data.rank] = \
                sliced_fun(self.opt_fun["f_Hx_plain"], self._num_slices)(inputs, xs)
            mgr_objs.barriers_Hx[0].wait() * par_data.avg_fac

            shareds.flat_g[par_data.vb[0]:par_data.vb[1]] = \
                np.sum(shareds.grads_2d[par_data.vb[0]:par_data.vb[1], :], axis=1)
            mgr_objs.barriers_Hx[1].wait()

            if par_data.rank == 0:
                shareds.flat_g += self.reg_coeff * x
            mgr_objs.barriers_Hx[2].wait()

            return shareds.flat_g

        return parallel_eval


# class FiniteDifferenceHvp(Serializable):

#     def __init__(self, base_eps=1e-8, symmetric=True, grad_clip=None, num_slices=1):
#         Serializable.quick_init(self, locals())
#         self.base_eps = base_eps
#         self.symmetric = symmetric
#         self.grad_clip = grad_clip
#         self._num_slices = num_slices

#     def update_opt(self, f, target, inputs, reg_coeff):
#         self.target = target
#         self.reg_coeff = reg_coeff

#         params = target.get_params(trainable=True)

#         constraint_grads = theano.grad(
#             f, wrt=params, disconnected_inputs='warn')
#         flat_grad = ext.flatten_tensor_variables(constraint_grads)

#         def f_Hx_plain(*args):
#             inputs_ = args[:len(inputs)]
#             xs = args[len(inputs):]
#             flat_xs = np.concatenate([np.reshape(x, (-1,)) for x in xs])
#             param_val = self.target.get_param_values(trainable=True)
#             eps = np.cast['float32'](
#                 self.base_eps / (np.linalg.norm(param_val) + 1e-8))
#             self.target.set_param_values(
#                 param_val + eps * flat_xs, trainable=True)
#             flat_grad_dvplus = self.opt_fun["f_grad"](*inputs_)
#             if self.symmetric:
#                 self.target.set_param_values(
#                     param_val - eps * flat_xs, trainable=True)
#                 flat_grad_dvminus = self.opt_fun["f_grad"](*inputs_)
#                 hx = (flat_grad_dvplus - flat_grad_dvminus) / (2 * eps)
#                 self.target.set_param_values(param_val, trainable=True)
#             else:
#                 self.target.set_param_values(param_val, trainable=True)
#                 flat_grad = self.opt_fun["f_grad"](*inputs_)
#                 hx = (flat_grad_dvplus - flat_grad) / eps
#             return hx

#         self.opt_fun = ext.lazydict(
#             f_grad=lambda: ext.compile_function(
#                 inputs=inputs,
#                 outputs=flat_grad,
#                 log_name="f_grad",
#             ),
#             f_Hx_plain=lambda: f_Hx_plain,
#         )

#     def build_eval(self, inputs):
#         def eval(x):
#             xs = tuple(self.target.flat_to_params(x, trainable=True))
#             ret = sliced_fun(self.opt_fun["f_Hx_plain"], self._num_slices)(
#                 inputs, xs) + self.reg_coeff * x
#             return ret

#         return eval


class ParallelConjugateGradientOptimizer(Serializable):
    """
    Performs constrained optimization via line search. The search direction is computed using a conjugate gradient
    algorithm, which gives x = A^{-1}g, where A is a second order approximation of the constraint and g is the gradient
    of the loss function.

    Only the optimize() method changes for parallel implementation, but some
    options of serial implementation may not be available.
    """

    def __init__(
            self,
            cg_iters=10,
            reg_coeff=1e-5,
            subsample_factor=1.,
            backtrack_ratio=0.8,
            max_backtracks=15,
            accept_violation=False,
            hvp_approach=None,
            num_slices=1):
        """

        :param cg_iters: The number of CG iterations used to calculate A^-1 g
        :param reg_coeff: A small value so that A -> A + reg*I
        :param subsample_factor: Subsampling factor to reduce samples when using "conjugate gradient. Since the
        computation time for the descent direction dominates, this can greatly reduce the overall computation time.
        :param accept_violation: whether to accept the descent step if it violates the line search condition after
        exhausting all backtracking budgets
        :return:
        """
        Serializable.quick_init(self, locals())
        self._cg_iters = cg_iters
        self._reg_coeff = reg_coeff
        self._subsample_factor = subsample_factor
        self._backtrack_ratio = backtrack_ratio
        self._max_backtracks = max_backtracks
        self._num_slices = num_slices

        self._opt_fun = None
        self._target = None
        self._max_constraint_val = None
        self._constraint_name = None
        self._accept_violation = accept_violation
        # if hvp_approach is None:
        #     hvp_approach = PerlmutterHvp(num_slices)
        hvp_approach = ParallelPerlmutterHvp(num_slices)  # Only option supported.
        self._hvp_approach = hvp_approach
        self._par_data = None  # objects for parallelism, to be populated
        self._shareds = None
        self._mgr_objs = None

    def update_opt(self, loss, target, leq_constraint, inputs, extra_inputs=None, constraint_name="constraint", *args,
                   **kwargs):
        """
        :param loss: Symbolic expression for the loss function.
        :param target: A parameterized object to optimize over. It should implement methods of the
        :class:`rllab.core.paramerized.Parameterized` class.
        :param leq_constraint: A constraint provided as a tuple (f, epsilon), of the form f(*inputs) <= epsilon.
        :param inputs: A list of symbolic variables as inputs, which could be subsampled if needed. It is assumed
        that the first dimension of these inputs should correspond to the number of data points
        :param extra_inputs: A list of symbolic variables as extra inputs which should not be subsampled
        :return: No return value.
        """

        inputs = tuple(inputs)
        if extra_inputs is None:
            extra_inputs = tuple()
        else:
            extra_inputs = tuple(extra_inputs)

        constraint_term, constraint_value = leq_constraint

        params = target.get_params(trainable=True)
        grads = theano.grad(loss, wrt=params, disconnected_inputs='warn')
        flat_grad = ext.flatten_tensor_variables(grads)

        self._hvp_approach.update_opt(f=constraint_term, target=target, inputs=inputs + extra_inputs,
                                      reg_coeff=self._reg_coeff)

        self._target = target
        self._max_constraint_val = constraint_value
        self._constraint_name = constraint_name

        self._opt_fun = ext.lazydict(
            f_loss=lambda: ext.compile_function(
                inputs=inputs + extra_inputs,
                outputs=loss,
                log_name="f_loss",
            ),
            f_grad=lambda: ext.compile_function(
                inputs=inputs + extra_inputs,
                outputs=flat_grad,
                log_name="f_grad",
            ),
            f_constraint=lambda: ext.compile_function(
                inputs=inputs + extra_inputs,
                outputs=constraint_term,
                log_name="constraint",
            ),
            f_loss_constraint=lambda: ext.compile_function(
                inputs=inputs + extra_inputs,
                outputs=[loss, constraint_term],
                log_name="f_loss_constraint",
            ),
        )

    def loss(self, inputs, extra_inputs=None):
        """
        Parallelized: returns the same value in all workers.
        """
        par_data, shareds, mgr_objs = self._par_objs

        inputs = tuple(inputs)
        if extra_inputs is None:
            extra_inputs = tuple()
        loss = sliced_fun(self._opt_fun["f_loss"], self._num_slices)(inputs, extra_inputs)

        if par_data.rank == 0:
            shareds.loss.value = loss * par_data.avg_fac
            mgr_objs.barriers_loss[0].wait()
        else:
            mgr_objs.barriers_loss[0].wait()
            with mgr_objs.lock:
                shareds.loss.value += loss * par_data.avg_fac
        mgr_objs.barriers_loss[1].wait()

        return shareds.loss.value

    def constraint_val(self, inputs, extra_inputs=None):
        """
        Parallelized: returns the same value in all workers.
        """
        par_data, shareds, mgr_objs = self._par_objs

        inputs = tuple(inputs)
        if extra_inputs is None:
            extra_inputs = tuple()
        constraint_val = sliced_fun(self._opt_fun["f_constraint"], self._num_slices)(inputs, extra_inputs)

        if par_data.rank == 0:
            shareds.constraint_val.value = constraint_val * par_data.avg_fac
            mgr_objs.barriers_cnstr[0].wait()
        else:
            mgr_objs.barriers_cnstr[0].wait()
            with mgr_objs.lock:
                shareds.constraint_val.value += constraint_val * par_data.avg_fac
        mgr_objs.barriers_cnstr[1].wait()

        return shareds.constraint_val.value

    def init_par_objs(self, n_parallel, size_grad):
        """
        These objects will be inherited by forked subprocesses.
        (Also possible to return these and attach them explicitly within
        subprocess--needed in Windows.)
        """
        avg_fac = 1. / n_parallel  # later can be made different per worker.
        n_grad_elm_worker = -(-size_grad // n_parallel)  # ceiling div
        vb_idx = [n_grad_elm_worker * i for i in range(n_parallel + 1)]
        vb_idx[-1] = size_grad
        vb = [(vb_idx[i], vb_idx[i + 1]) for i in range(n_parallel)]

        par_data = SimpleContainer(
            rank=None,  # populate once in subprocess
            avg_fac=avg_fac,
            vb=vb
        )
        shareds = SimpleContainer(
            flat_g=np.frombuffer(mp.RawArray('d', size_grad)),
            grads_2d=np.reshape(
                np.frombuffer(mp.RawArray('d', size_grad * n_parallel)),
                (size_grad, n_parallel)),
            loss=mp.RawValue('d'),
            constraint_val=mp.RawValue('d'),
            loss_before=mp.RawValue('d'),
            loss_bktrk=mp.RawValue('d'),
            constraint_val_bktrk=mp.RawValue('d'),
        )
        mgr_objs = SimpleContainer(
            lock=mp.Lock(),
            barriers_grad=[mp.Barrier(n_parallel) for _ in range(2)],
            barriers_Hx=[mp.Barrier(n_parallel) for _ in range(3)],
            barriers_bktrk=[mp.Barrier(n_parallel) for _ in range(3)],
            barriers_loss=[mp.Barrier(n_parallel) for _ in range(2)],
            barriers_cnstr=[mp.Barrier(n_parallel) for _ in range(2)],
        )
        self._par_objs = (par_data, shareds, mgr_objs)
        self._hvp_approach._par_objs = self._par_objs

    def set_rank(self, rank):
        par_data, _, _ = self._par_objs
        par_data.rank = rank
        par_data.vb = par_data.vb[rank]  # (assign gradient vector boundaries)

    def set_avg_fac(self, avg_fac):
        par_data, _, _ = self._par_objs
        par_data.avg_fac = avg_fac

    def optimize(self, inputs, extra_inputs=None, subsample_grouped_inputs=None):
        """
        Parallelized: all workers get the same parameter update.
        """
        par_data, shareds, mgr_objs = self._par_objs

        inputs = tuple(inputs)
        if extra_inputs is None:
            extra_inputs = tuple()

        if self._subsample_factor < 1:
            if subsample_grouped_inputs is None:
                subsample_grouped_inputs = [inputs]
            subsample_inputs = tuple()
            for inputs_grouped in subsample_grouped_inputs:
                n_samples = len(inputs_grouped[0])
                inds = np.random.choice(
                    n_samples, int(n_samples * self._subsample_factor), replace=False)
                subsample_inputs += tuple([x[inds] for x in inputs_grouped])
        else:
            subsample_inputs = inputs

        if par_data.rank == 0:
            logger.log("computing loss before")

        loss_before = sliced_fun(self._opt_fun["f_loss"], self._num_slices)(
            inputs, extra_inputs)

        if par_data.rank == 0:
            logger.log("performing update")
            logger.log("computing descent direction")

        # Each worker records result available to all.
        shareds.grads_2d[:, par_data.rank] = sliced_fun(self._opt_fun["f_grad"], self._num_slices)(
            inputs, extra_inputs) * par_data.avg_fac

        if par_data.rank == 0:
            shareds.loss_before.value = loss_before * par_data.avg_fac
            mgr_objs.barriers_grad[0].wait()
        else:
            mgr_objs.barriers_grad[0].wait()
            with mgr_objs.lock:
                shareds.loss_before.value += loss_before * par_data.avg_fac

        # Each worker sums over an equal share of the grad elements across workers.
        shareds.flat_g[par_data.vb[0]:par_data.vb[1]] = \
            np.sum(shareds.grads_2d[par_data.vb[0]:par_data.vb[1], :], axis=1)
        mgr_objs.barriers_grad[1].wait()

        loss_before = shareds.loss_before.value

        # Function Hx is parallelized: every worker gets same returned value.
        Hx = self._hvp_approach.build_eval(subsample_inputs + extra_inputs)

        descent_direction = krylov.cg(Hx, shareds.flat_g, cg_iters=self._cg_iters)

        # NOTE: can this expression be simplified?
        initial_step_size = np.sqrt(
            2.0 * self._max_constraint_val *
            (1. / (descent_direction.dot(Hx(descent_direction)) + 1e-8))
        )
        if np.isnan(initial_step_size):
            initial_step_size = 1.
        flat_descent_step = initial_step_size * descent_direction

        if par_data.rank == 0:
            logger.log("descent direction computed")

        prev_param = np.copy(self._target.get_param_values(trainable=True))
        n_iter = 0
        for n_iter, ratio in enumerate(self._backtrack_ratio ** np.arange(self._max_backtracks)):

            cur_step = ratio * flat_descent_step
            cur_param = prev_param - cur_step
            self._target.set_param_values(cur_param, trainable=True)
            loss_bktrk, constraint_val_bktrk = sliced_fun(
                self._opt_fun["f_loss_constraint"], self._num_slices)(inputs, extra_inputs)

            if par_data.rank == 0:
                shareds.loss_bktrk.value = loss_bktrk * par_data.avg_fac
                shareds.constraint_val_bktrk.value = constraint_val_bktrk * par_data.avg_fac
                mgr_objs.barriers_bktrk[0].wait()
            else:
                mgr_objs.barriers_bktrk[0].wait()
                with mgr_objs.lock:
                    shareds.loss_bktrk.value += loss_bktrk * par_data.avg_fac
                    shareds.constraint_val_bktrk.value += constraint_val_bktrk * par_data.avg_fac
            mgr_objs.barriers_bktrk[1].wait()
            loss_bktrk = shareds.loss_bktrk.value
            constraint_val_bktrk = shareds.constraint_val_bktrk.value

            if loss_bktrk < loss_before and constraint_val_bktrk <= self._max_constraint_val:
                break

            # Wait for everyone to check exit condition before repeating loop
            # (and resetting shareds).
            mgr_objs.barriers_bktrk[2].wait()

        if ((np.isnan(loss_bktrk) or np.isnan(constraint_val_bktrk) or loss_bktrk >= loss_before or
                constraint_val_bktrk >= self._max_constraint_val) and not self._accept_violation):
            self._target.set_param_values(prev_param, trainable=True)
            if par_data.rank == 0:
                logger.log("Line search condition violated. Rejecting the step!")
                if np.isnan(loss_bktrk):
                    logger.log("Violated because loss is NaN")
                if np.isnan(constraint_val_bktrk):
                    logger.log("Violated because constraint %s is NaN" %
                               self._constraint_name)
                if loss_bktrk >= loss_before:
                    logger.log("Violated because loss not improving")
                if constraint_val_bktrk >= self._max_constraint_val:
                    logger.log(
                        "Violated because constraint %s is violated" % self._constraint_name)

        if par_data.rank == 0:
            logger.log("backtrack iters: %d" % n_iter)
            logger.log("computing loss after")
            logger.log("optimization finished")
