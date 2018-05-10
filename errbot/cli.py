#!/usr/bin/env python

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import argparse
import locale
import logging
import os
import sys
from os import path, sep, getcwd, access, W_OK
from platform import system
import ast

from errbot.logs import root_logger
from errbot.plugin_wizard import new_plugin_wizard
from errbot.version import VERSION

log = logging.getLogger(__name__)

if locale.getpreferredencoding().lower() != "utf-8":
    log.warning(
        "Starting errbot with a default system encoding other than 'utf-8'"
        " might cause you a heap of troubles."
        " Your current encoding is set at '%s'" % locale.getpreferredencoding().lower()
    )


# noinspection PyUnusedLocal
def debug(sig, frame):
    """Interrupt running process, and provide a python prompt for
    interactive debugging."""
    d = {"_frame": frame}  # Allow access to frame object.
    d.update(frame.f_globals)  # Unless shadowed by global
    d.update(frame.f_locals)

    i = code.InteractiveConsole(d)
    message = "Signal received : entering python shell.\nTraceback:\n"
    message += "".join(traceback.format_stack(frame))
    i.interact(message)


ON_WINDOWS = system() == "Windows"

if not ON_WINDOWS:
    from daemonize import Daemonize
    import code
    import traceback
    import signal

    signal.signal(signal.SIGUSR1, debug)  # Register handler for debugging


def get_config(config_path):
    config_fullpath = config_path
    if not path.exists(config_fullpath):
        log.error(
            "I cannot find the config file %s \n"
            "(You can change this path with the -c parameter see --help)" % config_path
        )
        log.info(
            "You can use the template %s as a base and copy it to %s. \nYou can then customize it."
            % (os.path.realpath(os.path.join(__file__, os.pardir, "config-template.py")), config_path)
        )
        exit(-1)

    try:
        config = __import__(path.splitext(path.basename(config_fullpath))[0])
        log.info("Config check passed...")
        return config
    except Exception:
        log.exception("I could not import your config from %s, please check the error below..." % config_fullpath)
        exit(-1)


def _read_dict():
    import collections

    new_dict = ast.literal_eval(sys.stdin.read())
    if not isinstance(new_dict, collections.Mapping):
        raise ValueError(
            "A dictionary written in python is needed from stdin. Type=%s, Value = %s"
            % (type(new_dict), repr(new_dict))
        )
    return new_dict


def main():

    execution_dir = getcwd()

    # By default insert the execution path (useful to be able to execute Errbot from
    # the source tree directly without installing it.
    sys.path.insert(0, execution_dir)

    parser = argparse.ArgumentParser(description="The main entry point of the errbot.")
    parser.add_argument(
        "-c",
        "--config",
        default=None,
        help="Full path to your config.py (default: config.py in current working directory).",
    )

    mode_selection = parser.add_mutually_exclusive_group()
    mode_selection.add_argument("-v", "--version", action="version", version="Errbot version {}".format(VERSION))
    mode_selection.add_argument(
        "-r",
        "--restore",
        nargs="?",
        default=None,
        const="default",
        help="restore a bot from backup.py (default: backup.py from the bot data directory)",
    )
    mode_selection.add_argument("-l", "--list", action="store_true", help="list all available backends")
    mode_selection.add_argument(
        "--new-plugin",
        nargs="?",
        default=None,
        const="current_dir",
        help="create a new plugin in the specified directory",
    )
    mode_selection.add_argument(
        "-i",
        "--init",
        nargs="?",
        default=None,
        const=".",
        help="Initialize a simple bot minimal configuration in the optionally "
        "given directory (otherwise it will be the working directory). "
        "This will create a data subdirectory for the bot data dir and a plugins directory"
        " for your plugin development with an example in it to get you started.",
    )
    # storage manipulation
    mode_selection.add_argument(
        "--storage-set",
        nargs=1,
        help="DANGER: Delete the given storage namespace "
        "and set the python dictionary expression "
        "passed on stdin.",
    )
    mode_selection.add_argument(
        "--storage-merge",
        nargs=1,
        help="DANGER: Merge in the python dictionary expression " "passed on stdin into the given storage namespace.",
    )
    mode_selection.add_argument(
        "--storage-get",
        nargs=1,
        help="Dump the given storage namespace in a " "format compatible for --storage-set and " "--storage-merge.",
    )

    mode_selection.add_argument(
        "-T", "--text", dest="backend", action="store_const", const="Text", help="force local text backend"
    )
    mode_selection.add_argument(
        "-G", "--graphic", dest="backend", action="store_const", const="Graphic", help="force local graphical backend"
    )

    if not ON_WINDOWS:
        option_group = parser.add_argument_group("optional daemonization arguments")
        option_group.add_argument("-d", "--daemon", action="store_true", help="Detach the process from the console")
        option_group.add_argument(
            "-p",
            "--pidfile",
            default=None,
            help="Specify the pid file for the daemon (default: current bot data directory)",
        )

    args = vars(parser.parse_args())  # create a dictionary of args

    if args["init"]:
        try:
            import jinja2
            import shutil

            base_dir = os.getcwd() if args["init"] == "." else args["init"]

            if not os.path.isdir(base_dir):
                print("Target directory %s must exist. Please create it." % base_dir)

            base_dir = os.path.abspath(base_dir)
            data_dir = os.path.join(base_dir, "data")
            extra_plugin_dir = os.path.join(base_dir, "plugins")
            example_plugin_dir = os.path.join(extra_plugin_dir, "err-example")
            log_path = os.path.join(base_dir, "errbot.log")
            templates_dir = os.path.join(os.path.dirname(__file__), "templates", "initdir")
            env = jinja2.Environment(loader=jinja2.FileSystemLoader(templates_dir), autoescape=True)
            config_template = env.get_template("config.py.tmpl")

            os.mkdir(data_dir)
            os.mkdir(extra_plugin_dir)
            os.mkdir(example_plugin_dir)

            with open(os.path.join(base_dir, "config.py"), "w") as f:
                f.write(config_template.render(data_dir=data_dir, extra_plugin_dir=extra_plugin_dir, log_path=log_path))
            shutil.copyfile(
                os.path.join(templates_dir, "example.plug"), os.path.join(example_plugin_dir, "example.plug")
            )
            shutil.copyfile(os.path.join(templates_dir, "example.py"), os.path.join(example_plugin_dir, "example.py"))
            print("Your Errbot directory has been correctly initialized !")
            if base_dir == os.getcwd():
                print('Just do "errbot" and it should start in text/development mode.')
            else:
                print('Just do "cd %s" then "errbot" and it should start in text/development mode.' % args["init"])
            sys.exit(0)
        except Exception as e:
            print("The initialization of your errbot directory failed: %s" % e)
            sys.exit(1)

    # This must come BEFORE the config is loaded below, to avoid printing
    # logs as a side effect of config loading.
    if args["new_plugin"]:
        directory = os.getcwd() if args["new_plugin"] == "current_dir" else args["new_plugin"]
        for handler in logging.getLogger().handlers:
            root_logger.removeHandler(handler)
        try:
            new_plugin_wizard(directory)
        except KeyboardInterrupt:
            sys.exit(1)
        except Exception as e:
            sys.stderr.write(str(e) + "\n")
            sys.exit(1)
        finally:
            sys.exit(0)

    config_path = args["config"]
    # setup the environment to be able to import the config.py
    if config_path:
        # appends the current config in order to find config.py
        sys.path.insert(0, path.dirname(path.abspath(config_path)))
    else:
        config_path = execution_dir + sep + "config.py"

    config = get_config(config_path)  # will exit if load fails
    if args["list"]:
        from errbot.bootstrap import enumerate_backends

        print("Available backends:")
        for backend_name in enumerate_backends(config):
            print("\t\t%s" % backend_name)
        sys.exit(0)

    def storage_action(namespace, fn):
        # Used to defer imports until it is really necessary during the loading time.
        from errbot.bootstrap import get_storage_plugin
        from errbot.storage import StoreMixin

        try:
            with StoreMixin() as sdm:
                sdm.open_storage(get_storage_plugin(config), namespace)
                fn(sdm)
            return 0
        except Exception as e:
            print(str(e), file=sys.stderr)
            return -3

    if args["storage_get"]:

        def p(sdm):
            print(repr(dict(sdm)))

        err_value = storage_action(args["storage_get"][0], p)
        sys.exit(err_value)

    if args["storage_set"]:

        def replace(sdm):
            new_dict = _read_dict()  # fail early and don't erase the storage if the input is invalid.
            sdm.clear()
            sdm.update(new_dict)

        err_value = storage_action(args["storage_set"][0], replace)
        sys.exit(err_value)

    if args["storage_merge"]:

        def merge(sdm):
            new_dict = _read_dict()
            sdm.update(new_dict)

        err_value = storage_action(args["storage_merge"][0], merge)
        sys.exit(err_value)

    if args["restore"]:
        backend = "Null"  # we don't want any backend when we restore
    elif args["backend"] is None:
        if not hasattr(config, "BACKEND"):
            log.fatal("The BACKEND configuration option is missing in config.py")
            sys.exit(1)
        backend = config.BACKEND
    else:
        backend = args["backend"]

    log.info("Selected backend '%s'." % backend)

    # Check if at least we can start to log something before trying to start
    # the bot (esp. daemonize it).

    log.info("Checking for '%s'..." % config.BOT_DATA_DIR)
    if not path.exists(config.BOT_DATA_DIR):
        raise Exception("The data directory '%s' for the bot does not exist" % config.BOT_DATA_DIR)
    if not access(config.BOT_DATA_DIR, W_OK):
        raise Exception("The data directory '%s' should be writable for the bot" % config.BOT_DATA_DIR)

    if (not ON_WINDOWS) and args["daemon"]:
        if args["backend"] == "Text":
            raise Exception("You cannot run in text and daemon mode at the same time")
        if args["restore"]:
            raise Exception("You cannot restore a backup in daemon mode.")
        if args["pidfile"]:
            pid = args["pidfile"]
        else:
            pid = config.BOT_DATA_DIR + sep + "err.pid"

        # noinspection PyBroadException
        try:

            def action():
                from errbot.bootstrap import bootstrap

                bootstrap(backend, root_logger, config)

            daemon = Daemonize(app="err", pid=pid, action=action, chdir=os.getcwd())
            log.info("Daemonizing")
            daemon.start()
        except Exception:
            log.exception("Failed to daemonize the process")
        exit(0)
    from errbot.bootstrap import bootstrap

    restore = args["restore"]
    if restore == "default":  # restore with no argument, get the default location
        restore = path.join(config.BOT_DATA_DIR, "backup.py")

    bootstrap(backend, root_logger, config, restore)
    log.info("Process exiting")


if __name__ == "__main__":
    main()
