from concurrent import futures
from typing import Callable
from datetime import datetime
import numpy as np
from scipy import sparse, optimize
from numba import njit
from copt.utils import norm_rows


@njit
def f_squared(w, x, y):
    # squared loss
    return 0.5 * ((y - np.dot(x, w)) ** 2)


@njit
def deriv_squared(w, x, y):
    # derivative of squared loss
    return - (y - np.dot(x, w))


@njit
def f_logistic(w, x, y):
    # logistic loss
    # same as in lightning
    p = y * np.dot(x, w)
    if p > 0:
        return np.log(1 + np.exp(-p))
    else:
        return -p + np.log(1 + np.exp(p))


@njit
def deriv_logistic(w, x, y):
    # derivative of logistic loss
    # same as in lightning (with minus sign)
    p = y * np.dot(x, w)
    if p > 0:
        phi = 1. / (1 + np.exp(-p))
    else:
        exp_t = np.exp(p)
        phi = exp_t / (1. + exp_t)
    return (phi - 1) * y


@njit
def _debiasing_vec(A_indices, A_indptr, n_samples, n_features):
    d = np.zeros(n_features)
    for i in range(n_samples):
        for j in A_indices[A_indptr[i]:A_indptr[i + 1]]:
            d[j] += 1
    for j in range(n_features):
        if d[j] != 0.0:
            d[j] = n_samples / d[j]
    return d


def compute_step_size(loss: str, A, step_size_factor=4) -> float:
    """
    Helper function to compute the step size for common loss
    functions.

    Parameters
    ----------
    loss
    A
    step_size_factor

    Returns
    -------

    """
    if loss == 'logistic':
        return 4.0 / (norm_rows(A) * step_size_factor)
    elif loss == 'squared':
        return 1.0 / (norm_rows(A) * step_size_factor)
    else:
        raise NotImplementedError('loss %s is not implemented' % loss)


def fmin_SAGA(
        fun: Callable, fun_deriv: Callable, A, b, x0: np.ndarray,
        step_size: float=-1, g_prox: Callable=None, g_blocks: np.ndarray=None,
        beta: float=1.0,
        n_jobs: int=1,
        max_iter=1000, tol=1e-6, verbose=False, callback=None, trace=False) -> optimize.OptimizeResult:
    """Stochastic average gradient augmented (SAGA) algorithm.

    The SAGA algorithm can solve optimization problems of the form

        argmin_x 1/n \sum_{i=1}^n f(a_i^T x, b_i) + alpha * L2 + beta * g(x)


    Parameters
    ----------
    fun
        loss function

    fun_deriv
        derivative function

    x0
        Starting point

    g_blocks
        If g is a block-separable function, this allows to specify which are the
        blocks in this penalty. It is an array of integers with the same size as
        x0 where each coordinate represents the group to which that coordinate
        belongs to.

    Returns
    -------
    opt
        The optimization result represented as a
        ``scipy.optimize.OptimizeResult`` object. Important attributes are:
        ``x`` the solution array, ``success`` a Boolean flag indicating if
        the optimizer exited successfully and ``message`` which describes
        the cause of the termination. See `scipy.optimize.OptimizeResult`
        for a description of other attributes.

    References
    ----------
    Defazio, Aaron, Francis Bach, and Simon Lacoste-Julien. "SAGA: A fast
    incremental gradient method with support for non-strongly convex composite
    objectives." Advances in Neural Information Processing Systems. 2014.
    """

    x = np.ascontiguousarray(x0).copy()
    assert x.size == A.shape[1]
    assert A.shape[0] == b.size

    if step_size < 0:
        raise ValueError

    if hasattr(g_prox, '__call__'):
        g_prox = njit(g_prox)
    elif g_prox is None:
        @njit
        def g_prox(step_size, x, *args): return x
    else:
        raise NotImplementedError

    n_samples, n_features = A.shape
    success = False

    if sparse.issparse(A):
        A = sparse.csr_matrix(A)
        if g_blocks is None:
            g_blocks = np.arange(n_features)
        epoch_iteration, trace_loss = _epoch_factory_sparse_SAGA(
                fun, fun_deriv, g_prox, g_blocks, A, b, beta)
    else:
        epoch_iteration, trace_loss = _epoch_factory_SAGA(
            fun, fun_deriv, g_prox, A, b, beta)

    start_time = datetime.now()
    trace_fun = []
    trace_time = []
    trace_x = []

    # .. memory terms ..
    memory_gradient = np.zeros(n_samples)
    gradient_average = np.zeros(n_features)

    # .. iterate on epochs ..
    for it in range(max_iter):
        with futures.ThreadPoolExecutor(max_workers=n_jobs) as executor:
            fut = []
            for _ in range(n_jobs):
                fut.append(executor.submit(
                    epoch_iteration, x, memory_gradient, gradient_average,
                    np.random.permutation(n_samples), step_size))
            futures.wait(fut)
        if callback is not None:
            callback(x)
        if trace:
            trace_x.append(x.copy())
            trace_time.append((datetime.now() - start_time).total_seconds())

        grad_map = x - g_prox(beta * step_size, x - step_size * gradient_average)
        norm_grad_map = np.linalg.norm(grad_map)
        if verbose:
            print(it, norm_grad_map)
        if norm_grad_map < tol:
            success = True
            break
    if trace:
        if verbose:
            print('.. computing trace ..')
        # .. compute function values ..
        with futures.ThreadPoolExecutor(max_workers=n_jobs) as executor:
            trace_fun = [t for t in executor.map(trace_loss, trace_x)]

    return optimize.OptimizeResult(
        x=x, success=success, nit=it, trace_fun=trace_fun, trace_time=trace_time)


def fmin_PSSAGA(
        fun, fun_deriv, A, b, g_prox, h_prox, x0, step_size=-1,
        max_iter=1000, tol=1e-6, verbose=False, callback=None, trace=False,
        step_size_factor=4):

    if hasattr(g_prox, '__call__'):
        g_prox = njit(g_prox)
    elif g_prox is None:
        @njit
        def g_prox(step_size, x, *args): return x
    else:
        raise NotImplementedError

    if hasattr(h_prox, '__call__'):
        h_prox = njit(h_prox)
    elif h_prox is None:
        @njit
        def h_prox(step_size, x, *args): return x
    else:
        raise NotImplementedError

    x = np.ascontiguousarray(x0).copy()
    assert x.size == A.shape[1]
    assert A.shape[0] == b.size

    if step_size < 0:
        raise ValueError

    n_samples, n_features = A.shape
    success = False

    epoch_iteration, trace_loss = _epoch_factory_PSSAGA(
            fun, fun_deriv, g_prox, h_prox, A, b)

    start_time = datetime.now()
    trace_fun = []
    trace_time = []
    trace_x = []

    # .. memory terms ..
    memory_gradient = np.zeros(n_samples)
    gradient_average = np.zeros(n_features)

    # .. iterate on epochs ..
    for it in range(max_iter):
        epoch_iteration(x, memory_gradient, gradient_average,
                    np.random.permutation(n_samples), step_size)
        if callback is not None:
            callback(x)
        if trace:
            trace_x.append(x.copy())
            trace_time.append((datetime.now() - start_time).total_seconds())

        grad_map = np.linalg.norm(gradient_average)
        if verbose:
            print('Iteration %s, gradient mapping norm %s' % (it, grad_map))
        if grad_map < tol:
            success = True
            break
    if trace:
        if verbose:
            print('.. computing trace ..')
        # .. compute function values ..
        with futures.ThreadPoolExecutor(max_workers=1) as executor:
            trace_fun = [t for t in executor.map(trace_loss, trace_x)]

    return optimize.OptimizeResult(
        x=x, success=success, nit=it, trace_fun=trace_fun, trace_time=trace_time)


def _epoch_factory_SAGA(fun, f_prime, g_prox, A, b, beta):

    @njit
    def epoch_iteration_template(
            x, memory_gradient, gradient_average, sample_indices,
            step_size):
        n_samples, n_features = A.shape
        # .. inner iteration ..
        for i in sample_indices:
            grad_i = f_prime(x, A[i], b[i])
            incr = (grad_i - memory_gradient[i]) * A[i]
            x[:] = g_prox(beta * step_size, x - step_size * (incr + gradient_average))
            gradient_average += incr / n_samples
            memory_gradient[i] = grad_i

    @njit
    def full_loss(x):
        obj = 0.
        n_samples, n_features = A.shape
        for i in range(n_samples):
            obj += fun(x, A[i], b[i]) / n_samples
        return obj

    return epoch_iteration_template, full_loss


def _epoch_factory_sparse_SAGA(fun, f_prime, g_prox, g_blocks, A, b, beta):

    A_data = A.data
    A_indices = A.indices
    A_indptr = A.indptr
    n_samples, n_features = A.shape

    # g_blocks is a map from n_features -> n_features
    unique_blocks = np.unique(g_blocks)
    n_blocks = np.unique(g_blocks).size
    assert np.all(unique_blocks == np.arange(n_blocks))

    # .. compute the block support ..
    BS = sparse.dok_matrix((n_samples, n_blocks), dtype=np.bool)
    for i in range(n_samples):
        for j in A_indices[A_indptr[i]:A_indptr[i + 1]]:
            BS[i, g_blocks[j]] = True
    BS = BS.tocsr()
    BS_indices = BS.indices
    BS_indptr = BS.indptr

    # .. estimate a mapping from blocks to features ..
    reverse_blocks = sparse.dok_matrix((n_blocks, n_features), dtype=np.bool)
    for j in range(n_features):
        i = g_blocks[j]
        reverse_blocks[i, j] = True
    reverse_blocks = reverse_blocks.tocsr()
    reverse_blocks_indices = reverse_blocks.indices
    reverse_blocks_indptr = reverse_blocks.indptr

    d = np.array(BS.sum(0), dtype=np.float).ravel()
    d[d != 0] = n_samples / d

    @njit(nogil=True, cache=True)
    def epoch_iteration_template(
            x, memory_gradient, gradient_average, sample_indices, step_size):

        # .. SAGA estimate of the gradient ..
        grad_est = np.zeros(n_features)

        # .. inner iteration ..
        for i in sample_indices:
            idx = A_indices[A_indptr[i]:A_indptr[i+1]]
            block_idx = BS_indices[BS_indptr[i]:BS_indptr[i+1]]
            A_i = A_data[A_indptr[i]:A_indptr[i+1]]
            grad_i = f_prime(x[idx], A_i, b[i])

            # .. update coefficients ..
            grad_est[idx] = (grad_i - memory_gradient[i]) * A_i
            for g in block_idx:
                idx_g = reverse_blocks_indices[
                    reverse_blocks_indptr[g]:reverse_blocks_indptr[g+1]]
                grad_est[idx_g] += gradient_average[idx_g] * d[g]
                x[idx_g] = g_prox(
                    step_size * beta * d[g], x[idx_g] - step_size * grad_est[idx_g])

                # .. clean up ..
                grad_est[idx_g] = 0

            # .. update memory terms ..
            gradient_average[idx] += (grad_i - memory_gradient[i]) * A_i / n_samples
            memory_gradient[i] = grad_i

    @njit(nogil=True, cache=True)
    def full_loss(x):
        obj = 0.
        for i in range(n_samples):
            idx = A_indices[A_indptr[i]:A_indptr[i + 1]]
            A_i = A_data[A_indptr[i]:A_indptr[i + 1]]
            obj += fun(x[idx], A_i, b[i]) / n_samples
        return obj

    return epoch_iteration_template, full_loss


def _epoch_factory_PSSAGA(fun, f_prime, g_prox, h_prox, A, b):

    @njit(nogil=True, cache=True)
    def epoch_iteration_template(
            y, memory_gradient, gradient_average, sample_indices,
            step_size):
        beta = 1.0
        gamma = 1.0
        n_samples, n_features = A.shape
        # .. inner iteration ..
        for i in sample_indices:
            x = g_prox(beta * step_size, y)
            grad_i = f_prime(x, A[i], b[i])
            incr = (grad_i - memory_gradient[i]) * A[i]
            z = h_prox(gamma * step_size, 2 * x - y - step_size * (incr + gradient_average))
            y -= x - z
            gradient_average += incr / n_samples
            memory_gradient[i] = grad_i

    @njit(nogil=True, cache=True)
    def full_loss(x):
        obj = 0.
        n_samples, n_features = A.shape
        for i in range(n_samples):
            obj += fun(x, A[i], b[i]) / n_samples

    return epoch_iteration_template, full_loss
