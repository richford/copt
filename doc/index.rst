

Welcome to copt!
================

copt is a library for mathematical optimization written in pure Python.


.. warning::
    This library is a work in progress, expect some rough edges.


Philosophy
----------

   * Modular, general-purpose optimization library.
   * API similar to that of scipy.optimize.
   * State of the art performance, with emphasis on large-scale optimization.
   * Few dependencies, pure Python library for easy deployment.


Optimization algorithms
-----------------------
.. autosummary::

C-OPT contains implementations of different optimization methods. These are categorized as:

 * Proximal gradient: :meth:`proximal gradient descent <copt.minimize_proximal_gradient>`

 * Proximal splitting: :meth:`three operator splitting <copt.minimize_three_split>`, :meth:`primal-dual hybrid gradient <copt.minimize_primal_dual>`

 * Frank-Wolfe: :meth:`Frank-Wolfe <copt.minimize_frank_wolfe>`, :meth:`Pairwise Frank-Wolfe <copt.minimize_pfw_l1>`

 * Variance-reduced stochastic methods: :meth:`SAGA <copt.minimize_saga>`, :meth:`SVRG <copt.minimize_SVRG>`, :meth:`variance-reduced three operator splitting <copt.minimize_vrtos>`


Getting started
---------------

If you already have a working installation of numpy and scipy,
the easiest way to install copt is using ``pip`` ::

    pip install -U copt


Alternatively, you can install the latest development from github with the command::

    pip install git+https://github.com/openopt/copt.git

.. toctree::
    :maxdepth: 2
    :hidden:

    proximal_gradient.rst
    proximal_splitting.rst
    frank_wolfe.rst
    incremental.rst
    loss_functions.rst
    auto_examples/index.rst
    datasets.rst
