"""
Geoscience Australia module to temporarily replace or substitute py_gamma.py.

Gamma's py_gamma module has a race condition which affects the data returned
when calling executables. This module replaces the py_gamma's threaded approach
with a serial interface to avoid race conditions & ensure the data is returned.
"""

import os
import socket
import functools
import subprocess
import warnings
from pathlib import Path

import structlog
import insar.constant as const

# use guard block to distinguish between platforms with(out) Gamma
try:
    import py_gamma as py_gamma_broken
except ImportError as iex:
    hostname = socket.gethostname()

    if hostname.startswith("gadi"):
        # something odd here if can't find py_gamma path on NCI
        raise iex

    # ugly hack
    class DummyPyGamma:
        ParFile = None

    py_gamma_broken = DummyPyGamma()


_LOG = structlog.get_logger("insar")


class GammaInterfaceException(Exception):
    """Generic exception class for the alternate Gamma interface."""

    pass


# customise the py_gamma calling interface to automate repetitive tasks
def auto_logging_decorator(func, exception_type, logger):
    """
    Decorate & expand 'func' with default logging & error handling for Ifg processing.

    The automatic adding of logging & error handling simplifies Gamma calls considerably, in addition
    to reducing a large amount of code duplication.

    :param func: function to decorate (e.g. py_gamma_ga.subprocess_wrapper)
    :param exception_type: type of exception to throw e.g. IOError
    :param logger: object to call logging methods on (error(), info() etc)
    :return: a decorated function
    """

    def error_handler(cmd, *args, **kwargs):
        if const.COUT not in kwargs:
            kwargs[const.COUT] = []
        if const.CERR not in kwargs:
            kwargs[const.CERR] = []

        stat = func(cmd, *args, **kwargs)
        cout = kwargs[const.COUT]
        cerr = kwargs[const.CERR]

        if stat:
            msg = f"Failed to execute gamma command: {cmd}"
            logger.error(msg, args=args, **kwargs)  # NB: cout/cerr already in kwargs
            raise exception_type(msg)
        else:
            msg = f"Successfully execute gamma command: {cmd}"
            logger.info(msg, args=args, **kwargs)

        return stat, cout, cerr

    return error_handler


# potentially installed gamma packages
_GAMMA_PACKAGES = ("DISP", "DIFF", "IPTA", "ISP", "LAT", "MSP", "GEO")

GAMMA_INSTALL_DIR = None
GAMMA_INSTALLED_PACKAGES = None
GAMMA_INSTALLED_EXES = {}

COUT = "cout"
CERR = "cerr"


def find_gamma_installed_packages(install_dir):
    """Search install_dir for Gamma pkgs. Return list of packages."""
    try:
        res = tuple(n for n in _GAMMA_PACKAGES if n in os.listdir(install_dir))

        if res is not None and len(res) > 0: # success
            return res

    except FileNotFoundError:
        pass

    msg = "No Gamma packages found in {}"
    raise GammaInterfaceException(msg.format(install_dir))


def find_gamma_installed_exes(install_dir, packages):
    """
    Search package dirs for Gamma exes.

    :param install_dir: base dir str of the Gamma install
    :param packages: sequence of strings of Gamma packages ("ISP", "DIFF" etc)
    :returns: mapping {k=exe_name: v=exe_relative_path}.
    """
    ignored_exes = ["ASAR_XCA"]  # duplicate program, for unrelated Envisat data

    # bin directory is the main directory of executables.
    dirs = [os.path.join(install_dir, p, "bin") for p in packages]
    # but scripts directory also has scripts that are run as if they're
    # gamma commands as well, thus we also need to search this dir.
    dirs += [os.path.join(install_dir, p, "scripts") for p in packages]

    exes = {}
    for d in dirs:
        for dirpath, _, filenames in os.walk(d):
            for f in filenames:
                fullpath = os.path.join(dirpath, f)

                if os.access(fullpath, os.R_OK):  # only add executables
                    if f in exes and f not in ignored_exes:
                        msg = "{} duplicate in Gamma exe lookup under {}. Skipped!"
                        warnings.warn(msg.format(f, exes[f]))
                    else:
                        exes[f] = fullpath

    return exes


def subprocess_wrapper(cmd, *args, **kwargs):
    """Shim to map GammaInterface methods to subprocess.run() calls for running Gamma EXEs."""
    cmd_list = [cmd]
    cmd_list.extend("-" if a is None else str(a) for a in args)

    p = subprocess.run(
        cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True
    )

    _LOG.info("calling Gamma", cmd=cmd, cmd_list=cmd_list)

    if COUT in kwargs:
        kwargs[COUT].extend(p.stdout.split("\n"))

    if CERR in kwargs:
        if p.stderr is not None:
            kwargs[CERR].extend(p.stderr.split("\n"))

    return p.returncode


class GammaInterface:
    """
    Alternate interface class/shim to temporarily(?) replace the official py_gamma.py module.

    The GAMMA supplied py_gamma.py module is fairly new (as of July/Aug 2020) & has problems which
    this module is designed to work around.
    """

    _gamma_proxy = None

    def __init__(self, install_dir=None, gamma_exes=None, subprocess_func=None):
        """
        Create an GammaInterface shim class.
        :param install_dir: base install dir str of Gamma. If None is specified, the install dir must
                            be configured elsewhere for the dynamic
        :param gamma_exes: Mapping of {k=exe_name: v=exe_relative_path}
        :param subprocess_func: function to call Gamma exes, with signature (gamma_cmd_name, *args, **kwargs)
                                see subprocess_wrapper() in this module for an example.
        """
        # k=program, v=exe path relative to install dir
        self._gamma_exes = gamma_exes if gamma_exes else GAMMA_INSTALLED_EXES
        self.install_dir = install_dir if install_dir else GAMMA_INSTALL_DIR
        self.subprocess_func = (
            subprocess_wrapper if subprocess_func is None else subprocess_func
        )

        _LOG.info("GAMMA install location", install_dir=install_dir)

    def __getattr__(self, name):
        """
        Dynamically lookup Gamma programs as methods to avoid hardcoding.

        By default this will scan the GAMMA_INSTALL_DIR env var for executable
        programs/scripts, to determine what GAMMA calls are available... however
        it's also possible for the user to set a proxy object to use for
        implementing a GAMMA-like interface instead.

        If a proxy object is available it takes priority over any underlying
        GAMMA install (if any exists).
        """

        # Forward to a proxy object's version of the call/program, if the user
        # has set a GAMMA proxy (typically used by unit tests).
        proxy = self._gamma_proxy or GammaInterface._gamma_proxy
        if proxy:
            return getattr(proxy, name)

        # Otherwise get a subprocess functor for the appropriate executable
        if self.install_dir is None:
            msg = (
                "GammaInterface shim install_dir not set. Check for the GAMMA_INSTALL_DIR environ var, "
                "or ensure the setup code manually sets the install dir."
            )
            raise GammaInterfaceException(msg)

        if name not in self._gamma_exes:
            msg = (
                "Unrecognised attribute '{}'. Check the calling function name, or for unimplemented"
                "attributes.\nKnown GAMMA exes for this shim are:\n{}"
            )
            raise AttributeError(msg.format(name, self._gamma_exes))

        cmd = os.path.join(self.install_dir, self._gamma_exes[name])
        return functools.partial(self.subprocess_func, cmd)

    def ParFile(self, filepath: str):
        if not Path(filepath).exists():
            raise Exception(f"The specified path does not exist: {filepath}")

        proxy = self._gamma_proxy or GammaInterface._gamma_proxy
        if proxy:
            return proxy.ParFile(filepath)

        return py_gamma_broken.ParFile(str(filepath))

    @classmethod
    def set_proxy(cls, proxy_object):
        """
        Sets the GAMMA-like proxy object to use for GAMMA programs/calls.

        See :func:`~.GammaInterface.__getattr__`
        """
        GammaInterface._gamma_proxy = proxy_object

try:
    GAMMA_INSTALL_DIR = os.environ["GAMMA_INSTALL_DIR"]

    if not os.path.exists(GAMMA_INSTALL_DIR):
        warnings.warn(f"Problem with GAMMA_INSTALL_DIR={GAMMA_INSTALL_DIR} as this path does not exist. This means that GAMMA will not be able to run and only a proxy object will be used.")
        GAMMA_INSTALL_DIR=None

except KeyError:
    # skip this under the assumption users will manually configure the shim
    pass

if GAMMA_INSTALL_DIR:
    GAMMA_INSTALLED_PACKAGES = find_gamma_installed_packages(GAMMA_INSTALL_DIR)
    GAMMA_INSTALLED_EXES = find_gamma_installed_exes(
        GAMMA_INSTALL_DIR, GAMMA_INSTALLED_PACKAGES
    )
    pg = GammaInterface(GAMMA_INSTALL_DIR, GAMMA_INSTALLED_EXES)

    # HACK: InSAR packaging workflow requires pg.__file__, fake it so the GammaInterface shim looks
    # like the actual py_gamma module. Hopefully this shouldn't break anything.
    pg.__file__ = os.path.join(GAMMA_INSTALL_DIR, "py_gamma.py")
else:
    # assume user will configure manually
    warnings.warn("GAMMA_INSTALL_DIR not set, user needs to configure this in code...")
    pg = GammaInterface()
