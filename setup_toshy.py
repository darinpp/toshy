#!/usr/bin/env python3

import os
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'     # prevent this script from creating cache files
import re
import sys
import pwd
import grp
import random
import string
import signal
import shutil
import zipfile
import argparse
import datetime
import platform
import textwrap
import subprocess

from subprocess import DEVNULL, PIPE
from typing import Dict

# local import
import lib.env as env
from lib.logger import debug, error, warn, info

if os.name == 'posix' and os.geteuid() == 0:
    error("This app should not be run as root/superuser. Exiting.")
    sys.exit(1)

def signal_handler(sig, frame):
    """Handle signals like Ctrl+C"""
    if sig in (signal.SIGINT, signal.SIGQUIT):
        # Perform any cleanup code here before exiting
        # traceback.print_stack(frame)
        print('\n')
        debug(f'SIGINT or SIGQUIT received. Exiting.\n')
        sys.exit(1)

if platform.system() != 'Windows':
    signal.signal(signal.SIGINT,    signal_handler)
    signal.signal(signal.SIGQUIT,   signal_handler)
    signal.signal(signal.SIGHUP,    signal_handler)
    signal.signal(signal.SIGUSR1,   signal_handler)
    signal.signal(signal.SIGUSR2,   signal_handler)
else:
    signal.signal(signal.SIGINT,    signal_handler)
    error(f'This is only meant to run on Linux. Exiting.')
    sys.exit(1)

original_PATH_str       = os.getenv('PATH')
if original_PATH_str is None:
    print()
    error(f"ERROR: PATH variable is not set. This is abnormal. Exiting.")
    print()
    sys.exit(1)

home_dir                = os.path.expanduser('~')
trash_dir               = os.path.join(home_dir, '.local', 'share', 'Trash')
this_file_path          = os.path.realpath(__file__)
this_file_dir           = os.path.dirname(this_file_path)
this_file_name          = os.path.basename(__file__)
if trash_dir in this_file_path or '/trash/' in this_file_path.lower():
    print()
    error(f"Path to this file:\n\t{this_file_path}")
    error(f"You probably did not intend to run this from the TRASH. See path. Exiting.")
    print()
    sys.exit(1)

home_local_bin          = os.path.join(home_dir, '.local', 'bin')
run_tmp_dir             = os.environ.get('XDG_RUNTIME_DIR') or '/tmp'

good_path_tmp_file      = 'toshy_installer_says_path_is_good'
good_path_tmp_path      = os.path.join(run_tmp_dir, good_path_tmp_file)

fix_path_tmp_file       = 'toshy_installer_says_fix_path'
fix_path_tmp_path       = os.path.join(run_tmp_dir, fix_path_tmp_file)

# set a standard path for duration of script run, to avoid issues with user customized paths
os.environ['PATH']  = '/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin'

# deactivate Python virtual environment, if one is active, to avoid issues with sys.executable
if sys.prefix != sys.base_prefix:
    os.environ["VIRTUAL_ENV"] = ""
    sys.path = [p for p in sys.path if not p.startswith(sys.prefix)]
    sys.prefix = sys.base_prefix

# Check if 'sudo' command is available to user
if not shutil.which('sudo'):
    print("Error: 'sudo' not found. Installer will fail without it. Exiting.")
    sys.exit(1)

do_not_ask_about_path = None
if home_local_bin in original_PATH_str:
    with open(good_path_tmp_path, 'a') as file:
        file.write('Nothing to see here.')
    # subprocess.run(['touch', path_good_tmp_path])
    do_not_ask_about_path = True
else:
    debug("Home user local bin not part of PATH string.")
# do the 'else' of creating 'path_fix_tmp_path' later in function that prompts user

# system Python version
py_ver_mjr, py_ver_mnr  = sys.version_info[:2]
py_interp_ver_tup       = (py_ver_mjr, py_ver_mnr)
py_pkg_ver_str          = f'{py_ver_mjr}{py_ver_mnr}'


class InstallerSettings:
    """Set up variables for necessary information to be used by all functions"""
    def __init__(self) -> None:
        sep_reps                    = 80
        self.sep_char               = '='
        self.separator              = self.sep_char * sep_reps
        self.override_distro        = None
        self.DISTRO_NAME            = None
        self.DISTRO_VER: str        = ""
        self.SESSION_TYPE           = None
        self.DESKTOP_ENV            = None

        self.distro_mjr_ver: str    = ""
        self.distro_mnr_ver: str    = ""

        self.systemctl_present      = shutil.which('systemctl') is not None
        self.init_system            = None

        self.pkgs_for_distro        = None

        self.qdbus                  = 'qdbus-qt5' if shutil.which('qdbus-qt5') else 'qdbus'

        # current stable Python release version (TODO: update when needed):
        # 3.11 Release Date: Oct. 24, 2022
        self.curr_py_rel_ver_mjr     = 3
        self.curr_py_rel_ver_mnr     = 11
        self.curr_py_rel_ver_tup     = (self.curr_py_rel_ver_mjr, self.curr_py_rel_ver_mnr)
        self.curr_py_rel_ver_str     = f'{self.curr_py_rel_ver_mjr}.{self.curr_py_rel_ver_mnr}'

        self.py_interp_ver          = f'{py_ver_mjr}.{py_ver_mnr}'
        self.py_interp_path         = shutil.which('python3')

        self.toshy_dir_path         = os.path.join(home_dir, '.config', 'toshy')
        self.db_file_name           = 'toshy_user_preferences.sqlite'
        self.db_file_path           = os.path.join(self.toshy_dir_path, self.db_file_name)
        self.backup_succeeded       = None
        self.existing_cfg_data      = None
        self.existing_cfg_slices    = None
        self.venv_path              = os.path.join(self.toshy_dir_path, '.venv')

        self.keyszer_tmp_path       = os.path.join(this_file_dir, 'keyszer-temp')

        # self.keyszer_branch         = 'environ_api_kde'
        self.keyszer_branch         = 'environ_api_hyprland'
        # self.keyszer_branch         = 'environ_api_wlroots' # doesn't work yet
        self.keyszer_url            = 'https://github.com/RedBearAK/keyszer.git'
        self.keyszer_clone_cmd      = f'git clone -b {self.keyszer_branch} {self.keyszer_url}'

        self.input_group       = 'input'
        self.user_name              = pwd.getpwuid(os.getuid()).pw_name

        self.barebones_config       = None
        self.skip_native            = None
        self.fancy_pants            = None
        self.tweak_applied          = None
        self.remind_extensions      = None

        self.should_reboot          = None
        self.run_tmp_dir            = run_tmp_dir
        self.reboot_tmp_file        = f"{self.run_tmp_dir}/toshy_installer_says_reboot"
        self.reboot_ascii_art       = textwrap.dedent("""
                ██████      ███████     ██████       ██████       ██████      ████████     ██ 
                ██   ██     ██          ██   ██     ██    ██     ██    ██        ██        ██ 
                ██████      █████       ██████      ██    ██     ██    ██        ██        ██ 
                ██   ██     ██          ██   ██     ██    ██     ██    ██        ██           
                ██   ██     ███████     ██████       ██████       ██████         ██        ██ 
                """)


def safe_shutdown(exit_code: int):
    """do some stuff on the way out"""
    # good place to do some file cleanup?
    # 
    # invalidate the sudo ticket, don't leave system in "superuser" state
    subprocess.run(['sudo', '-k'])
    print()                         # avoid crowding the prompt on exit
    sys.exit(exit_code)


def show_reboot_prompt():
    """show the big ASCII reboot prompt"""
    print()
    print()
    print()
    print(cnfg.separator)
    print(cnfg.separator)
    print(cnfg.reboot_ascii_art)
    print(cnfg.separator)
    print(cnfg.separator)


def get_environment_info():
    """Get back the distro name (ID), distro version, session type and desktop 
        environment from `env.py` module"""
    print(f'\n§  Getting environment information...\n{cnfg.separator}')

    known_init_systems = {
        'systemd':              'Systemd',
        'init':                 'SysVinit',
        'upstart':              'Upstart',
        'openrc':               'OpenRC',
        'runit':                'Runit',
        'initng':               'Initng'
    }

    try:
        with open('/proc/1/comm', 'r') as f:
            cnfg.init_system = f.read().strip()
    except (PermissionError, FileNotFoundError, OSError) as init_check_err:
        error(f'ERROR: Problem when checking init system:\n\t{init_check_err}')

    if cnfg.init_system:
        if cnfg.init_system in known_init_systems:
            init_sys_full_name = known_init_systems[cnfg.init_system]
            print(f"The active init system is: '{cnfg.init_system}' ({init_sys_full_name})")
        else:
            print(f"Init system process unknown: '{cnfg.init_system}'")
    else:
        error("ERROR: Init system (process 1) could not be determined. (See above error.)")
    print()   # blank line after init system message

    env_info_dct   = env.get_env_info()

    # Avoid casefold() errors by converting all to strings
    if cnfg.override_distro:
        cnfg.DISTRO_NAME    = str(cnfg.override_distro).casefold()
    else:
        cnfg.DISTRO_NAME    = str(env_info_dct.get('DISTRO_NAME',  'keymissing')).casefold()
    cnfg.DISTRO_VER     = str(env_info_dct.get('DISTRO_VER',   'keymissing')).casefold()
    cnfg.SESSION_TYPE   = str(env_info_dct.get('SESSION_TYPE', 'keymissing')).casefold()
    cnfg.DESKTOP_ENV    = str(env_info_dct.get('DESKTOP_ENV',  'keymissing')).casefold()

    # split out the major version from the minor version, if there is one
    distro_ver_parts            = cnfg.DISTRO_VER.split('.') if cnfg.DISTRO_VER else []
    cnfg.distro_mjr_ver         = distro_ver_parts[0] if distro_ver_parts else 'NO_VER'
    cnfg.distro_mnr_ver         = distro_ver_parts[1] if len(distro_ver_parts) > 1 else 'no_mnr_ver'

    debug('Toshy installer sees this environment:'
        f"\n\t DISTRO_NAME  = '{cnfg.DISTRO_NAME}'"
        f"\n\t DISTRO_VER   = '{cnfg.DISTRO_VER}'"
        f"\n\t SESSION_TYPE = '{cnfg.SESSION_TYPE}'"
        f"\n\t DESKTOP_ENV  = '{cnfg.DESKTOP_ENV}'"
        '\n', ctx='EV')


def fancy_str(text, color_name, *, bold=False):
    """
    Return text wrapped in the specified color code.
    :param text: Text to be colorized.
    :param color_name: Natural name of the color.
    :param bold: Boolean to indicate if text should be bold.
    :return: Colorized string if terminal likely supports it, otherwise the original string.
    """
    color_codes = { 'red': '31', 'green': '32', 'yellow': '33', 'blue': '34', 
                    'magenta': '35', 'cyan': '36', 'white': '37', 'default': '0'}
    if os.getenv('COLORTERM') and color_name in color_codes:
        bold_code = '1;' if bold else ''
        return f"\033[{bold_code}{color_codes[color_name]}m{text}\033[0m"
    else:
        return text


def call_attention_to_password_prompt():
    """Utility function to emphasize the sudo password prompt"""
    try:
        subprocess.run( ['sudo', '-n', 'true'], stdout=DEVNULL, stderr=DEVNULL, check=True)
    except subprocess.CalledProcessError:
        # sudo ticket not valid, requires a password, so get user attention
        print()
        print(fancy_str('  -----------------------------------  ', 'magenta', bold=True))
        print(fancy_str('  -- PASSWORD REQUIRED TO CONTINUE --  ', 'magenta', bold=True))
        print(fancy_str('  -----------------------------------  ', 'magenta', bold=True))
        print()


def enable_prompt_for_reboot():
    """Utility function to make sure user is reminded to reboot if necessary"""
    cnfg.should_reboot = True
    if not os.path.exists(cnfg.reboot_tmp_file):
        os.mknod(cnfg.reboot_tmp_file)


def show_task_completed_msg():
    """Utility function to show a standard message after each major section completes"""
    print(fancy_str(' >> Task completed successfully << ', 'green', bold=True))


def dot_Xmodmap_warning():
    """Check for '.Xmodmap' file in user's home folder, show warning about mod key remaps"""

    xmodmap_file_path = os.path.join(home_dir, '.Xmodmap')

    if os.path.isfile(xmodmap_file_path):
        print()
        print(f'{cnfg.separator}')
        print(f'{cnfg.separator}')
        warn_str    = "\t WARNING: You have an '.Xmodmap' file in your home folder!!!"
        print(fancy_str(warn_str, "red"))
        print(f'   This can cause confusing PROBLEMS if you are remapping any modifier keys!')
        print(f'{cnfg.separator}')
        print(f'{cnfg.separator}')
        print()

        secret_code = ''.join(random.choice(string.ascii_letters) for _ in range(4))

        response = input(
            f"You must take responsibility for the issues an '.Xmodmap' file may cause."
            f"\n\n\t If you understand, enter the secret code '{secret_code}': "
        )

        if response == secret_code:
            print()
            info("Good code. User has taken responsibility for '.Xmodmap' file. Proceeding...\n")
        else:
            print()
            error("Code does not match! Try the installer again after dealing with '.Xmodmap'.")
            safe_shutdown(1)


def ask_is_distro_updated():
    """Ask user if the distro has recently been updated"""
    print()
    debug('NOTICE: It is ESSENTIAL to have your system completely updated.', ctx="!!")
    print()
    response = input('Have you updated your system recently? [y/N]: ')
    if response not in ['y', 'Y']:
        print()
        error("Try the installer again after you've done a full system update. Exiting.")
        safe_shutdown(1)


def ask_add_home_local_bin():
    """
    Check if `~/.local/bin` is in original PATH. Done earlier in script.
    Ask user if it is OK to add the `~/.local/bin` folder to the PATH permanently.
    Create temp file to allow bincommands script to bypass question.
    """
    if do_not_ask_about_path:
        pass
    else:
        print()
        response = input('The "~/.local/bin" folder is not in PATH. OK to add it? [Y/n]: ') or 'y'
        if response in ['y', 'Y']:
            # create temp file that will get script to add local bin to path without asking
            with open(fix_path_tmp_path, 'a') as file:
                file.write('Nothing to see here.')


def elevate_privileges():
    """Elevate privileges early in the installer process"""
    call_attention_to_password_prompt()
    subprocess.run(['sudo', 'bash', '-c', 'echo -e "\nUsing elevated privileges..."'], check=True)


def do_kwin_reconfigure():
    """Utility function to run the KWin reconfigure command"""
    try:
        subprocess.run([cnfg.qdbus, 'org.kde.KWin', '/KWin', 'reconfigure'],
                        check=True, stderr=DEVNULL, stdout=DEVNULL)
    except subprocess.CalledProcessError as proc_err:
        error(f'Error while running KWin reconfigure.\n\t{proc_err}')


distro_groups_map = {

    # separate references for RHEL types versus Fedora types
    'fedora-based':             ["fedora", "fedoralinux", "ultramarine", "nobara"],
    'rhel-based':               ["rhel", "almalinux", "rocky", "eurolinux", "centos"],

    # separate references for Fedora immutables using rpm-ostree
    'fedora-immutables':        ["silverblue-experimental", "kinoite-experimental"],

    # separate references for Tumbleweed types versus Leap types
    'tumbleweed-based':         ["opensuse-tumbleweed"],
    'leap-based':               ["opensuse-leap"],

    'mandriva-based':           ["openmandriva"],

    'ubuntu-based':             ["ubuntu", "mint", "pop", "elementary", "neon", "tuxedo", "zorin"],
    'debian-based':             ["lmde", "peppermint", "debian", "kali", "q4os"],

    'arch-based':               ["arch", "arcolinux", "endeavouros", "manjaro"],
    'solus-based':              ["solus"],
    # Add more as needed...
}

pkg_groups_map = {

    # NOTE: Do not add 'gnome-shell-extension-appindicator' to Fedora/RHELs.
    #       This will install extension but requires logging out of GNOME to activate.
    'fedora-based':        ["cairo-devel", "cairo-gobject-devel",
                            "dbus-daemon", "dbus-devel",
                            "evtest",
                            "gcc", "git", "gobject-introspection-devel",
                            "libappindicator-gtk3", "libnotify",
                            "python3-dbus", "python3-devel", "python3-pip", "python3-tkinter",
                            "systemd-devel",
                            "xset",
                            "zenity"],

    'rhel-based':          ["cairo-devel", "cairo-gobject-devel",
                            "dbus-daemon", "dbus-devel",
                            "gcc", "git", "gobject-introspection-devel",
                            "libappindicator-gtk3", "libnotify",
                            "python3-dbus", "python3-devel", "python3-pip", "python3-tkinter",
                            "systemd-devel",
                            "xset",
                            "zenity"],

    'fedora-immutables':   ["cairo-devel", "cairo-gobject-devel",
                            "dbus-daemon", "dbus-devel",
                            "evtest",
                            "gcc", "git", "gobject-introspection-devel",
                            "libappindicator-gtk3", "libnotify",
                            "python3-dbus", "python3-devel", "python3-pip", "python3-tkinter",
                            "systemd-devel",
                            "xset",
                            "zenity"],

    # NOTE: for openSUSE (Tumbleweed, not applicable to Leap):
    # How to get rid of the need to use specific version numbers in packages: 
    # pkgconfig(packagename)>=N.nn (version symbols optional)
    # How to query a package to see what the equivalent pkgconfig(packagename) syntax would be:
    # rpm -q --provides packagename | grep -i pkgconfig
    'tumbleweed-based':    ["cairo-devel",
                            "dbus-1-daemon", "dbus-1-devel",
                            "gcc", "git", "gobject-introspection-devel",
                            "libappindicator3-devel", "libnotify-tools",
                            # f"python{py_pkg_ver}-dbus-python-devel",
                            "python3-dbus-python-devel",
                            # f"python{py_pkg_ver}-devel",
                            "python3-devel",
                            # f"python{py_pkg_ver}-tk",
                            "python3-tk",
                            "systemd-devel",
                            "tk", "typelib-1_0-AyatanaAppIndicator3-0_1",
                            "zenity"],

    # TODO: update Leap Python package versions as it makes newer Python available
    'leap-based':          ["cairo-devel",
                            "dbus-1-devel",
                            "gcc", "git", "gobject-introspection-devel",
                            "libappindicator3-devel", "libnotify-tools",
                            "python3-dbus-python-devel",
                                "python311",
                                "python311-devel",
                                "python311-tk",
                            "systemd-devel",
                            "tk", "typelib-1_0-AyatanaAppIndicator3-0_1",
                            "zenity"],

    'mandriva-based':      ["cairo-devel",
                            "dbus-daemon", "dbus-devel",
                            "git", "gobject-introspection-devel",
                            "lib64ayatana-appindicator3_1", "lib64ayatana-appindicator3-gir0.1",
                                "lib64cairo-gobject2", "lib64python-devel", "lib64systemd-devel",
                                "libnotify",
                            "python-dbus", "python-dbus-devel", "python-ensurepip", "python3-pip",
                            "task-devel", "tkinter",
                            "xset",
                            "zenity"],

    # TODO: see if this needs "dbus-daemon" added as dependency (for containers)
    'ubuntu-based':        ["curl",
                            "git", "gir1.2-ayatanaappindicator3-0.1",
                            "input-utils",
                            "libcairo2-dev", "libdbus-1-dev", "libgirepository1.0-dev",
                                "libnotify-bin", "libsystemd-dev",
                            "python3-dbus", "python3-dev", "python3-pip", "python3-tk",
                                "python3-venv",
                            "zenity"],

    # TODO: see if this needs "dbus-daemon" added as dependency (for containers)
    'debian-based':        ["curl",
                            "git", "gir1.2-ayatanaappindicator3-0.1",
                            "input-utils",
                            "libcairo2-dev", "libdbus-1-dev", "libgirepository1.0-dev",
                                "libnotify-bin", "libsystemd-dev",
                            "python3-dbus", "python3-dev", "python3-pip", "python3-tk",
                                "python3-venv",
                            "zenity"],

    # TODO: see if this needs "dbus-daemon" added as dependency (for containers)
    'arch-based':          ["cairo",
                            "dbus",
                            "evtest",
                            "git", "gobject-introspection",
                            "libappindicator-gtk3", "libnotify",
                            "pkg-config", "python", "python-dbus", "python-pip",
                            "systemd",
                            "tk",
                            "zenity"],

    # TODO: see if this needs "dbus-daemon" added as dependency (for containers)
    'solus-based':         ["gcc", "git",
                            "libayatana-appindicator", "libcairo-devel", "libnotify",
                            "pip", "python3-dbus", "python3-devel", "python3-tkinter",
                                "python-dbus-devel", "python-gobject-devel",
                            "systemd-devel",
                            "zenity"],
}

extra_pkgs_map = {
    # Add a tuple with distro name (ID), major version (or None) and packages to be added...
    # ('distro_name', '22'): ["pkg1", "pkg2", ...],
    # ('distro_name', None): ["pkg1", "pkg2", ...],
}

remove_pkgs_map = {
    # Add a tuple with distro name (ID), major version (or None) and packages to be removed...
    # ('distro_name', '22'): ["pkg1", "pkg2", ...],
    # ('distro_name', None): ["pkg1", "pkg2", ...],
    ('centos', '7'):        ['dbus-daemon', 'gnome-shell-extension-appindicator'],
}


def get_distro_names():
    """Utility function to return list of available distro names (IDs)"""
    distro_list = []
    for group in distro_groups_map.values():
        distro_list.extend(group)
    sorted_distro_list = sorted(distro_list)
    prev_char: str = sorted_distro_list[0][0]
    # start index with the initial letter
    distro_index = prev_char.upper() + ": "
    for distro in sorted_distro_list:
        if distro[0] != prev_char:
            # type hint to help out VSCode syntax highlighter
            distro: str
            # remove last comma and space from previous line
            distro_index = distro_index[:-2]
            # start a new line with new initial letter
            distro_index += "\n\t" + distro[0].upper() + ": " + distro + ", "
            prev_char = distro[0]
        else:
            distro_index += distro + ", "
    # remove last comma and space from the final line
    distro_index = distro_index[:-2]
    return distro_index


def exit_with_invalid_distro_error(pkg_mgr_err=None):
    """Utility function to show error message and exit when distro is not valid"""
    print()
    error(f'ERROR: Installer does not know how to handle distro: "{cnfg.DISTRO_NAME}"')
    if pkg_mgr_err:
        error('ERROR: No valid package manager logic was encountered for this distro.')
    print()
    print(f'Try some options in "./{this_file_name} --help".')
    print()
    print(f'Maybe try one of these with "--override-distro" option:\n\n\t{get_distro_names()}')
    safe_shutdown(1)


class DistroQuirksHandler:
    """Object to contain static methods for prepping specific distro variants that
        need some extra prep work before installing the native package list"""

    def __init__(self) -> None:
        pass

    def handle_quirks_CentOS_7(self):
        print('Doing prep/checks for CentOS 7...')

        native_pkg_installer.check_for_pkg_mgr_cmd('yum')
        yum_cmd_lst = ['sudo', 'yum', 'install', '-y']
        if py_interp_ver_tup >= (3, 8):
            print(f"Good, Python version is 3.8 or later: "
                    f"'{cnfg.py_interp_ver}'")
        else:
            try:
                scl_repo = ['centos-release-scl']
                subprocess.run(yum_cmd_lst + scl_repo, check=True)
                py38_pkgs = [   'rh-python38',
                                'rh-python38-python-devel',
                                'rh-python38-python-tkinter',
                                'rh-python38-python-wheel-wheel'    ]
                subprocess.run(yum_cmd_lst + py38_pkgs, check=True)
                #
                # set new Python interpreter version and path to reflect what was installed
                cnfg.py_interp_path = '/opt/rh/rh-python38/root/usr/bin/python3.8'
                cnfg.py_interp_ver  = '3.8'
                # avoid using systemd packages/services for CentOS
                cnfg.systemctl_present = False
            except subprocess.CalledProcessError as proc_err:
                print()
                error(f'ERROR: (CentOS 7-specific) Problem installing/enabling Python 3.8:'
                        f'\n\t{proc_err}')
                safe_shutdown(1)
        # use yum to install dnf package manager
        try:
            subprocess.run(yum_cmd_lst + ['dnf'], check=True)
        except subprocess.CalledProcessError as proc_err:
            print()
            error(f'ERROR: Failed to install DNF package manager.\n\t{proc_err}')
            safe_shutdown(1)

    def handle_quirks_CentOS_Stream_8(self):
        print('Doing prep/checks for CentOS Stream 8...')
        min_mnr_ver = cnfg.curr_py_rel_ver_mnr - 3           # check up to 2 vers before current
        max_mnr_ver = cnfg.curr_py_rel_ver_mnr + 3           # check up to 3 vers after current
        py_minor_ver_rng = range(max_mnr_ver, min_mnr_ver, -1)
        if py_interp_ver_tup < cnfg.curr_py_rel_ver_tup:
            print(f"Checking for appropriate Python version on system...")
            for check_py_minor_ver in py_minor_ver_rng:
                if shutil.which(f'python3.{check_py_minor_ver}'):
                    cnfg.py_interp_path = shutil.which(f'python3.{check_py_minor_ver}')
                    cnfg.py_interp_ver = f'3.{check_py_minor_ver}'
                    print(f'Found Python version {cnfg.py_interp_ver} available.')
                    break
            else:
                error(  f'ERROR: Did not find any appropriate Python interpreter version.')
                safe_shutdown(1)
        try:
            # for dbus-python
            subprocess.run(['sudo', 'dnf', 'install', '-y',
                            f'python{cnfg.py_interp_ver}-devel'], check=True)
            # for Toshy Preferences GUI app
            subprocess.run(['sudo', 'dnf', 'install', '-y',
                            f'python{cnfg.py_interp_ver}-tkinter'], check=True)
        except subprocess.CalledProcessError as proc_err:
            error(f'ERROR: Problem installing necessary packages on CentOS Stream 8:'
                    f'\n\t{proc_err}')
            safe_shutdown(1)

    def handle_quirks_RHEL(self):
        print('Doing prep/checks for RHEL-type distro...')

        # for libappindicator-gtk3: sudo dnf install -y epel-release
        try:
            native_pkg_installer.check_for_pkg_mgr_cmd('dnf')
            subprocess.run(['sudo', 'dnf', 'install', '-y', 'epel-release'], check=True)
            subprocess.run(['sudo', 'dnf', 'makecache'], check=True)
        except subprocess.CalledProcessError as proc_err:
            print()
            error(f'ERROR: Problem while adding "epel-release" repo.\n\t{proc_err}')
            safe_shutdown(1)

        # Need to do this AFTER the 'epel-release' install
        if cnfg.DISTRO_NAME != 'centos' and cnfg.distro_mjr_ver in ['8']:
            # enable CRB repo on RHEL 8.x distros, but not CentOS Stream 8:
            cmd_lst = ['sudo', '/usr/bin/crb', 'enable']
            try:
                subprocess.run(cmd_lst, check=True)
            except subprocess.CalledProcessError as proc_err:
                print()
                error(f'ERROR: Problem while enabling CRB repo.\n\t{proc_err}')
                safe_shutdown(1)
            #
            # TODO: Add higher version if ever necessary (keep minimum 3.8)
            potential_versions = ['3.14', '3.13', '3.12', '3.11', '3.10', '3.9', '3.8']
            #
            for version in potential_versions:
                # check if the version is already installed
                if shutil.which(f'python{version}'):
                    cnfg.py_interp_path = f'/usr/bin/python{version}'
                    cnfg.py_interp_ver  = version
                    break
                # try to install the corresponding packages
                cmd_lst = ['sudo', 'dnf', 'install', '-y']
                pkg_lst = [f'python{version}', f'python{version}-devel', f'python{version}-tkinter']
                try:
                    subprocess.run(cmd_lst + pkg_lst, check=True)
                    # if the installation succeeds, set the interpreter path and version
                    cnfg.py_interp_path = f'/usr/bin/python{version}'
                    cnfg.py_interp_ver  = version
                    break
                # if the installation fails, continue with the next version
                except subprocess.CalledProcessError:
                    print(f'No match for potential Python version {version}.')
                    continue
            # this 'else' is part of the 'for' loop above, not an 'if' condition
            else:
                # if no suitable version was found, print an error message and exit
                error('ERROR: Did not find any appropriate Python interpreter version.')
                safe_shutdown(1)

        if cnfg.distro_mjr_ver in ['9']:
            #
            # enable "CodeReady Builder" repo for 'gobject-introspection-devel' only on 
            # RHEL 9.x and CentOS Stream 9 (TODO: Add v10 if it uses the same command):
            # sudo dnf config-manager --set-enabled crb
            cmd_lst = ['sudo', 'dnf', 'config-manager', '--set-enabled', 'crb']
            try:
                subprocess.run(cmd_lst, check=True)
            except subprocess.CalledProcessError as proc_err:
                print()
                error(f'ERROR: Problem while enabling CRB repo:\n\t{proc_err}')
                safe_shutdown(1)


class NativePackageInstaller:
    """Object to handle tasks related to installing native packages"""
    def __init__(self) -> None:
        pass

    def check_for_pkg_mgr_cmd(self, pkg_mgr_cmd):
        """Make sure native package installer command exists before using it, or exit"""
        call_attention_to_password_prompt()
        if not shutil.which(pkg_mgr_cmd):
            print()
            error(f'Package manager command ({pkg_mgr_cmd}) not available. Unable to continue.')
            safe_shutdown(1)

    def exit_with_pkg_install_error(self, proc_err):
        """shutdown with error message if there is a problem with installing package list"""
        print()
        error(f'ERROR: Problem installing package list for distro type:\n\t{proc_err}')
        safe_shutdown(1)

    def show_pkg_install_success_msg(self):
        # Have something come out even if package list is empty (like Arch after initial run)
        print('All necessary native distro packages are installed.')

    def install_pkg_list(self, cmd_lst, pkg_lst):
        """Install packages using the given package manager command list and package list."""
        
        # Extract the package manager command to check
        pkg_mgr_cmd = next((cmd for cmd in cmd_lst if cmd != 'sudo'), None)
        # If we couldn't extract the command, exit with an error
        if not pkg_mgr_cmd:
            error(f'No valid package manager command in provided command list:\n\t{cmd_lst}')
            safe_shutdown(1)
        
        call_attention_to_password_prompt()
        self.check_for_pkg_mgr_cmd(pkg_mgr_cmd)
        
        # Execute the package installation command
        try:
            subprocess.run(cmd_lst + pkg_lst, check=True)
            # self.show_pkg_install_success_msg()
        except subprocess.CalledProcessError as proc_err:
            self.exit_with_pkg_install_error(proc_err)


def install_distro_pkgs():
    """Install needed packages from list for distro type"""
    print(f'\n\n§  Installing native packages for this distro type...\n{cnfg.separator}')

    pkg_group = None
    for group, distros in distro_groups_map.items():
        if cnfg.DISTRO_NAME in distros:
            pkg_group = group
            break

    if pkg_group is None:
        print()
        print(f"ERROR: No list of packages found for this distro: '{cnfg.DISTRO_NAME}'")
        print(f'Installation cannot proceed without a list of packages. Sorry.')
        print(f'Try some options in "./{this_file_name} --help"')
        safe_shutdown(1)

    cnfg.pkgs_for_distro: list = pkg_groups_map[pkg_group]

    # Add extra packages for specific distros and versions
    for version in [cnfg.distro_mjr_ver, None]:
        distro_key = (cnfg.DISTRO_NAME, version)
        if distro_key in extra_pkgs_map:
            cnfg.pkgs_for_distro.extend(extra_pkgs_map[distro_key])

    # Remove packages for specific distros and versions
    for version in [cnfg.distro_mjr_ver, None]:
        distro_key = (cnfg.DISTRO_NAME, version)
        if distro_key in remove_pkgs_map:
            for pkg in remove_pkgs_map[distro_key]:
                if pkg in cnfg.pkgs_for_distro:
                    cnfg.pkgs_for_distro.remove(pkg)

    # Filter out systemd packages if if systemctl is not present
    cnfg.pkgs_for_distro = [
        pkg for pkg in cnfg.pkgs_for_distro 
        if cnfg.systemctl_present or 'systemd' not in pkg
    ]

    rpmostree_distros           = []
    dnf_distros                 = []
    zypper_distros              = []
    apt_distros                 = []
    pacman_distros              = []
    eopkg_distros               = []

    # assemble specific pkg mgr distro lists

    try:
        rpmostree_distros       += distro_groups_map['fedora-immutables']

        dnf_distros             += distro_groups_map['fedora-based']
        dnf_distros             += distro_groups_map['rhel-based']
        dnf_distros             += distro_groups_map['mandriva-based']

        zypper_distros          += distro_groups_map['tumbleweed-based']
        zypper_distros          += distro_groups_map['leap-based']

        apt_distros             += distro_groups_map['ubuntu-based']
        apt_distros             += distro_groups_map['debian-based']

        pacman_distros          += distro_groups_map['arch-based']

        eopkg_distros           += distro_groups_map['solus-based']
    except (KeyError, TypeError) as key_err:
        print()
        error(f'Problem setting up package manager distro lists:\n\t{key_err}')
        safe_shutdown(1)

    # create the quirks handler object
    quirks_handler              = DistroQuirksHandler()

    ###########################################################################
    ###  RPM-OSTREE DISTROS  ##################################################
    ###########################################################################
    def install_on_rpmostree_distro():
        """utility function that gets dispatched for distros that use RPM-OSTree"""
        if cnfg.DISTRO_NAME in distro_groups_map['fedora-immutables']:
            print(f'Distro is Fedora-type immutable. Using "rpm-ostree" instead of DNF.')

            # Filter out packages that are already installed
            filtered_pkg_lst = []
            for pkg in cnfg.pkgs_for_distro:
                result = subprocess.run(["rpm", "-q", pkg], stdout=PIPE, stderr=PIPE)
                if result.returncode != 0:
                    filtered_pkg_lst.append(pkg)
                else:
                    print(fancy_str(f"Package '{pkg}' is already installed. Skipping.", "green"))

            if filtered_pkg_lst:
                cmd_lst = ['sudo', 'rpm-ostree', 'install', '--idempotent',
                            '--allow-inactive', '--apply-live', '-y']
                native_pkg_installer.install_pkg_list(cmd_lst, filtered_pkg_lst)

    ###########################################################################
    ###  DNF DISTROS  #########################################################
    ###########################################################################
    def install_on_dnf_distro():
        """utility function that gets dispatched for distros that use DNF package manager"""
        call_attention_to_password_prompt()

        # OpenMandriva uses DNF, so it's here in the "dnf_distros" block
        if cnfg.DISTRO_NAME in distro_groups_map['mandriva-based']:
            cmd_lst = ['sudo', 'dnf', 'install', '-y']
            native_pkg_installer.install_pkg_list(cmd_lst, cnfg.pkgs_for_distro)
            return  # no need to continue after this

        # do extra prep/checks if distro is CentOS 7
        if cnfg.DISTRO_NAME in ['centos'] and cnfg.distro_mjr_ver == '7':
            quirks_handler.handle_quirks_CentOS_7()

        # do extra prep/checks if distro is CentOS Stream 8
        if cnfg.DISTRO_NAME in ['centos'] and cnfg.distro_mjr_ver == '8':
            quirks_handler.handle_quirks_CentOS_Stream_8()

        # do extra stuff only if distro is a RHEL type (not Fedora type)
        if cnfg.DISTRO_NAME in distro_groups_map['rhel-based']:
            quirks_handler.handle_quirks_RHEL()

        # finally, do the install of the main list of packages for Fedora/RHEL distro types
        if cnfg.DISTRO_NAME in distro_groups_map['rhel-based'] + distro_groups_map['fedora-based']:
            cmd_lst = ['sudo', 'dnf', 'install', '-y']
            native_pkg_installer.install_pkg_list(cmd_lst, cnfg.pkgs_for_distro)

    ###########################################################################
    ###  ZYPPER DISTROS  ######################################################
    ###########################################################################
    def install_on_zypper_distro():
        """utility function that gets dispatched for distros that use Zypper package manager"""
        cmd_lst = ['sudo', 'zypper', '--non-interactive', 'install']
        native_pkg_installer.install_pkg_list(cmd_lst, cnfg.pkgs_for_distro)

    ###########################################################################
    ###  APT DISTROS  #########################################################
    ###########################################################################
    def install_on_apt_distro():
        """utility function that gets dispatched for distros that use APT package manager"""
        cmd_lst = ['sudo', 'apt', 'install', '-y']
        native_pkg_installer.install_pkg_list(cmd_lst, cnfg.pkgs_for_distro)

    ###########################################################################
    ###  PACMAN DISTROS  ######################################################
    ###########################################################################
    def install_on_pacman_distro():
        """utility function that gets dispatched for distros that use Pacman package manager"""
        native_pkg_installer.check_for_pkg_mgr_cmd('pacman')

        def is_pkg_installed_pacman(package):
            """utility function to help avoid 'reinstalling' existing packages on Arch"""
            result = subprocess.run(['pacman', '-Q', package], stdout=DEVNULL, stderr=DEVNULL)
            return result.returncode == 0

        pkgs_to_install = [
            pkg
            for pkg in cnfg.pkgs_for_distro
            if not is_pkg_installed_pacman(pkg)
        ]
        if pkgs_to_install:
            cmd_lst = ['sudo', 'pacman', '-S', '--noconfirm']
            native_pkg_installer.install_pkg_list(cmd_lst, pkgs_to_install)

    ###########################################################################
    ###  EOPKG DISTROS  #######################################################
    ###########################################################################
    def install_on_eopkg_distro():
        """utility function that gets dispatched for distros that use Eopkg package manager"""
        dev_cmd_lst = ['sudo', 'eopkg', 'install', '-y', '-c']
        dev_pkg_lst = ['system.devel']
        native_pkg_installer.install_pkg_list(dev_cmd_lst, dev_pkg_lst)
        cmd_lst = ['sudo', 'eopkg', 'install', '-y']
        native_pkg_installer.install_pkg_list(cmd_lst, cnfg.pkgs_for_distro)

    # map installer sub-functions to each pkg mgr distro list
    pkg_mgr_dispatch = {
        tuple(rpmostree_distros):       install_on_rpmostree_distro,
        tuple(dnf_distros):             install_on_dnf_distro,
        tuple(zypper_distros):          install_on_zypper_distro,
        tuple(apt_distros):             install_on_apt_distro,
        tuple(pacman_distros):          install_on_pacman_distro,
        tuple(eopkg_distros):           install_on_eopkg_distro,
        # add any new package manager distro lists...
    }

    # Determine the correct installation function
    for distro_list, installer_function in pkg_mgr_dispatch.items():
        if cnfg.DISTRO_NAME in distro_list:
            installer_function()
            native_pkg_installer.show_pkg_install_success_msg()
            show_task_completed_msg()
            return
    # exit message in case there is no package manager distro list with distro name inside
    exit_with_invalid_distro_error(pkg_mgr_err=True)


#####################################################################################################
###   END OF NATIVE PACKAGE INSTALLER SECTION
#####################################################################################################


def load_uinput_module():
    """Check to see if `uinput` kernel module is loaded"""

    print(f'\n\n§  Checking status of "uinput" kernel module...\n{cnfg.separator}')

    try:
        subprocess.check_output("lsmod | grep uinput", shell=True)
        print('The "uinput" module is already loaded.')
    except subprocess.CalledProcessError:
        print('The "uinput" module is not loaded, loading now...')
        call_attention_to_password_prompt()
        subprocess.run(['sudo', 'modprobe', 'uinput'], check=True)

    # Check if /etc/modules-load.d/ directory exists
    if os.path.isdir("/etc/modules-load.d/"):
        # Check if /etc/modules-load.d/uinput.conf exists
        if not os.path.exists("/etc/modules-load.d/uinput.conf"):
            # If not, create it and add "uinput"
            try:
                call_attention_to_password_prompt()
                command = "echo 'uinput' | sudo tee /etc/modules-load.d/uinput.conf >/dev/null"
                subprocess.run(command, shell=True, check=True)
            except subprocess.CalledProcessError as proc_err:
                error(f"Failed to create /etc/modules-load.d/uinput.conf:\n\t{proc_err}")
                error(f'ERROR: Install failed.')
                safe_shutdown(1)

    else:
        # Check if /etc/modules file exists
        if os.path.isfile("/etc/modules"):
            # If it exists, check if "uinput" is already listed in it
            with open("/etc/modules", "r") as f:
                if "uinput" not in f.read():
                    # If "uinput" is not listed, append it
                    try:
                        call_attention_to_password_prompt()
                        command = "echo 'uinput' | sudo tee -a /etc/modules >/dev/null"
                        subprocess.run(command, shell=True, check=True)
                    except subprocess.CalledProcessError as proc_err:
                        error(f"ERROR: Failed to append 'uinput' to /etc/modules:\n\t{proc_err}")
                        error(f'ERROR: Install failed.')
                        safe_shutdown(1)
    show_task_completed_msg()


def reload_udev_rules():
    """utility function to reload udev rules in case of changes to rules file"""
    try:
        call_attention_to_password_prompt()
        subprocess.run(['sudo', 'udevadm', 'control', '--reload-rules'], check=True)
        subprocess.run(['sudo', 'udevadm', 'trigger'], check=True)
        print('Reloaded the "udev" rules successfully.')
    except subprocess.CalledProcessError as proc_err:
        print(f'Failed to reload "udev" rules:\n\t{proc_err}')
        enable_prompt_for_reboot()


def install_udev_rules():
    """Set up `udev` rules file to give user/keyszer access to uinput"""
    print(f'\n\n§  Installing "udev" rules file for keymapper...\n{cnfg.separator}')
    rules_file_path = '/etc/udev/rules.d/90-toshy-keymapper-input.rules'
    setfacl_path = shutil.which('setfacl')
    acl_rule = ''
    if setfacl_path is not None:
        acl_rule = f', RUN+="{setfacl_path} -m g::rw /dev/uinput"'
    rule_content = (
        'SUBSYSTEM=="input", GROUP="input"\n'
        f'KERNEL=="uinput", SUBSYSTEM=="misc", GROUP="input", MODE="0660"{acl_rule}\n'
    )
    # Only write the file if it doesn't exist or its contents are different
    if not os.path.exists(rules_file_path) or open(rules_file_path).read() != rule_content:
        command = f'sudo tee {rules_file_path}'
        try:
            call_attention_to_password_prompt()
            print(f'Using these "udev" rules for "uinput" device: ')
            print()
            subprocess.run(command, input=rule_content.encode(), shell=True, check=True)
            print()
            print(f'Toshy "udev" rules file successfully installed.')
            reload_udev_rules()
        except subprocess.CalledProcessError as proc_err:
            print()
            error(f'ERROR: Problem while installing "udev" rules file for keymapper.\n')
            err_output: bytes = proc_err.output  # Type hinting the error output variable
            # Deal with possible 'NoneType' error output
            error(f'Command output:\n{err_output.decode() if err_output else "No error output"}')
            print()
            error(f'ERROR: Install failed.')
            safe_shutdown(1)
    else:
        print(f'Correct "udev" rules already in place.')
    show_task_completed_msg()


def create_group(group_name):
    """Utility function to create the specified group if it does not already exist."""
    try:
        grp.getgrnam(group_name)
        print(f'Group "{group_name}" already exists.')
    except KeyError:
        print(f'Creating "{group_name}" group...')
        call_attention_to_password_prompt()
        if cnfg.DISTRO_NAME in distro_groups_map['fedora-immutables']:
            # Special handling for Fedora immutable distributions
            with open('/etc/group') as f:
                if not re.search(rf'^{group_name}:', f.read(), re.MULTILINE):
                    # https://docs.fedoraproject.org/en-US/fedora-silverblue/troubleshooting/
                    # Special command to make Fedora Silverblue/uBlue work, or usermod will fail: 
                    # grep -E '^input:' /usr/lib/group | sudo tee -a /etc/group
                    command = f"grep -E '^{group_name}:' /usr/lib/group | sudo tee -a /etc/group >/dev/null"
                    try:
                        subprocess.run(command, shell=True, check=True)
                        print(f"Added '{group_name}' group to system.")
                    except subprocess.CalledProcessError as proc_err:
                        error(f"Problem adding '{group_name}' group to system.\n\t{proc_err}")
                        safe_shutdown(1)
        else:
            try:
                cmd_lst = ['sudo', 'groupadd', group_name]
                subprocess.run(cmd_lst, check=True)
                print(f'Group "{group_name}" created successfully.')
            except subprocess.CalledProcessError as proc_err:
                print()
                error(f'ERROR: Problem when trying to create "input" group.\n')
                err_output: bytes = proc_err.output  # Type hinting the error output variable
                # Deal with possible 'NoneType' error output
                error(f'Command output:\n{err_output.decode() if err_output else "No error output"}')
                safe_shutdown(1)


def verify_user_groups():
    """Check if the `input` group exists and user is in group"""
    print(f'\n\n§  Checking if user is in "input" group...\n{cnfg.separator}')
    create_group(cnfg.input_group)
    # Check if the user is already in the `input` group
    group_info = grp.getgrnam(cnfg.input_group)
    if cnfg.user_name in group_info.gr_mem:
        print(f'User "{cnfg.user_name}" is a member of '
                f'group "{cnfg.input_group}".')
    else:
        # Add the user to the input group
        try:
            call_attention_to_password_prompt()
            subprocess.run(
                ['sudo', 'usermod', '-aG', cnfg.input_group, cnfg.user_name], check=True)
        except subprocess.CalledProcessError as proc_err:
            print()
            error(f'ERROR: Problem when trying to add user "{cnfg.user_name}" to '
                    f'group "{cnfg.input_group}".\n')
            err_output: bytes = proc_err.output  # Type hinting the error output variable
            # Deal with possible 'NoneType' error output
            error(f'Command output:\n{err_output.decode() if err_output else "No error output"}')
            print()
            error(f'ERROR: Install failed.')
            safe_shutdown(1)
        #
        print(f'User "{cnfg.user_name}" added to group "{cnfg.input_group}".')
        enable_prompt_for_reboot()
    show_task_completed_msg()


def clone_keyszer_branch():
    """Clone the designated `keyszer` branch from GitHub"""
    print(f'\n\n§  Cloning keyszer branch ({cnfg.keyszer_branch})...\n{cnfg.separator}')
    
    # Check if `git` command exists. If not, exit script with error.
    has_git = shutil.which('git')
    if not has_git:
        print(f'ERROR: "git" is not installed, for some reason. Cannot continue.')
        safe_shutdown(1)

    if os.path.exists(cnfg.keyszer_tmp_path):
        # force a fresh copy of keyszer every time script is run
        try:
            shutil.rmtree(cnfg.keyszer_tmp_path)
        except (OSError, PermissionError, FileNotFoundError) as file_err:
            error(f"Problem removing existing '{cnfg.keyszer_tmp_path}' folder:\n\t{file_err}")
    try:
        subprocess.run(cnfg.keyszer_clone_cmd.split() + [cnfg.keyszer_tmp_path], check=True)
    except subprocess.CalledProcessError as proc_err:
        print()
        error(f'Problem while cloning keyszer branch from GitHub:\n\t{proc_err}')
        safe_shutdown(1)
    show_task_completed_msg()


def extract_slices(data: str) -> Dict[str, str]:
    """Utility function to store user content slices from existing config file data"""
    slices              = {}
    pattern_start       = r'###  SLICE_MARK_START: (\w+)  ###.*'
    pattern_end         = r'###  SLICE_MARK_END: (\w+)  ###.*'
    matches_start       = list(re.finditer(pattern_start, data))
    matches_end         = list(re.finditer(pattern_end, data))
    if len(matches_start) != len(matches_end):
        raise ValueError(   f'Mismatched slice markers in config file:'
                            f'\n\t{matches_start}, {matches_end}')
    for begin, end in zip(matches_start, matches_end):
        slice_name = begin.group(1)
        if end.group(1) != slice_name:
            raise ValueError(f'Mismatched slice markers in config file:\n\t{slice_name}')
        slice_start         = begin.end()
        slice_end           = end.start()
        slices[slice_name]  = data[slice_start:slice_end]
    # Protect the barebones config file if a slice tagged with "barebones" found, 
    if 'barebones_user_cfg' in slices or any('barebones' in key for key in slices):
        cnfg.barebones_config = True
        print(f'Found "barebones" type config file. Will upgrade with same type.')
    # Confirm replacement of regular config file with barebones config if CLI option is used
    # and there is a non-barebones existing config file. 
    elif cnfg.barebones_config:
        for attempt in range(3):
            response = input(
                f'\n'
                f'ALERT:\n'
                f'Existing config file is not a barebones config, but the barebones CLI \n'
                f'option was specified. Do you want to proceed and replace the existing \n'
                f'config with a barebones config? This will discard all existing settings. \n'
                f'A timestamped backup of the existing config folder will still be made. \n'
                f'Enter "YES" to proceed or "N" to exit:'
            )
            if response.lower() not in ['n', 'yes']: continue
            if response.lower() == 'yes':
                # User confirmed to replace the existing config with a barebones config.
                # So, return an empty slices dictionary.
                return {}
            elif response.lower() == 'n':
                print(f'User chose to exit installer...')
                safe_shutdown(0)
        # If user didn't confirm after 3 attempts, exit the program.
        print('User input invalid. Exiting...')
        safe_shutdown(1)
    # 
    return slices


def merge_slices(data: str, slices: Dict[str, str]) -> str:
    """Utility function to merge stored slices into new config file data"""
    pattern_start   = r'###  SLICE_MARK_START: (\w+)  ###.*'
    pattern_end     = r'###  SLICE_MARK_END: (\w+)  ###.*'
    matches_start   = list(re.finditer(pattern_start, data))
    matches_end     = list(re.finditer(pattern_end, data))
    data_slices     = []
    previous_end    = 0
    for begin, end in zip(matches_start, matches_end):
        slice_name = begin.group(1)
        if end.group(1) != slice_name:
            raise ValueError(f'Mismatched slice markers in config file:\n\t{slice_name}')
        slice_start     = begin.end()
        slice_end       = end.start()
        # add the part of the data before the slice, and the slice itself
        data_slices.extend([data[previous_end:slice_start], 
                            slices.get(slice_name, data[slice_start:slice_end])])
        previous_end = slice_end
    # add the part of the data after the last slice
    data_slices.append(data[previous_end:])
    # 
    return "".join(data_slices)


def backup_toshy_config():
    """Backup existing Toshy config folder"""
    print(f'\n\n§  Backing up existing Toshy config folder...\n{cnfg.separator}')

    timestamp = datetime.datetime.now().strftime('_%Y%m%d_%H%M%S')
    toshy_cfg_bkups_base_dir  = os.path.join(home_dir, '.config', 'toshy_config_backups')
    toshy_cfg_bkup_timestamp_dir  = os.path.realpath(
        os.path.join(toshy_cfg_bkups_base_dir, 'toshy' + timestamp))

    if not os.path.exists(cnfg.toshy_dir_path):
        print(f'No existing Toshy folder to backup.')
        cnfg.backup_succeeded = True
    else:
        cfg_file_path   = os.path.join(cnfg.toshy_dir_path, 'toshy_config.py')

        if os.path.isfile(cfg_file_path):
            try:
                with open(cfg_file_path, 'r', encoding='UTF-8') as file:
                    cnfg.existing_cfg_data = file.read()
                print(f'Prepared existing config file data for merging into new config.')
            except (FileNotFoundError, PermissionError, OSError) as file_err:
                cnfg.existing_cfg_data = None
                error(f'Problem reading existing config file contents.\n\t{file_err}')
            if cnfg.existing_cfg_data is not None:
                try:
                    cnfg.existing_cfg_slices = extract_slices(cnfg.existing_cfg_data)
                except ValueError as value_err:
                    error(f'Problem extracting marked slices from existing config.\n\t{value_err}')
        else:
            print(f"No existing config file found in {cnfg.toshy_dir_path}.")

        if os.path.isfile(cnfg.db_file_path):
            try:
                os.unlink(f'{cnfg.run_tmp_dir}/{cnfg.db_file_name}')
            except (FileNotFoundError, PermissionError, OSError): pass
            try:
                shutil.copy(cnfg.db_file_path, f'{cnfg.run_tmp_dir}/')
            except (FileNotFoundError, PermissionError, OSError) as file_err:
                error(f"Problem copying preferences db file to '{cnfg.run_tmp_dir}':\n\t{file_err}")
        else:
            print(f'No existing preferences db file found in {cnfg.toshy_dir_path}.')
        try:
            # Define the ignore function
            def ignore_venv(dirname, filenames):
                return ['.venv'] if '.venv' in filenames else []
            # Copy files recursively from source to destination
            shutil.copytree(cnfg.toshy_dir_path, toshy_cfg_bkup_timestamp_dir, ignore=ignore_venv)
        except shutil.Error as copy_error:
            print(f"Failed to copy directory: {copy_error}")
            safe_shutdown(1)
        except OSError as os_error:
            print(f"Failed to copy directory: {os_error}")
            safe_shutdown(1)
        print(f"Backup completed to '{toshy_cfg_bkup_timestamp_dir}'")
        cnfg.backup_succeeded = True
    show_task_completed_msg()


def install_toshy_files():
    """Install Toshy files"""
    print(f'\n\n§  Installing Toshy files...\n{cnfg.separator}')
    if not cnfg.backup_succeeded:
        error(f'Backup of Toshy config folder failed? Bailing out.')
        safe_shutdown(1)
    keyszer_tmp_dir     = os.path.basename(cnfg.keyszer_tmp_path)
    try:
        if os.path.exists(cnfg.toshy_dir_path):
            try:
                shutil.rmtree(cnfg.toshy_dir_path)
            except (OSError, PermissionError, FileNotFoundError) as file_err:
                error(f'Problem removing existing Toshy config folder after backup:\n\t{file_err}')
        patterns_to_ignore = [
                '.github',
                '.gitignore',
                '__pycache__',
                keyszer_tmp_dir,
                'kwin-application-switcher',
                'LICENSE',
                'packages.json',
                'README.md',
                this_file_name,
        ]
        # must use list unpacking (*) ignore_patterns() requires individual pattern arguments
        ignore_fn = shutil.ignore_patterns(*patterns_to_ignore)
        # Copy files recursively from source to destination
        shutil.copytree(this_file_dir, cnfg.toshy_dir_path, ignore=ignore_fn)
    except shutil.Error as copy_error:
        error(f"Failed to copy directory: {copy_error}")
    except OSError as os_error:
        error(f"Failed to create backup directory: {os_error}")
    if cnfg.barebones_config is True:
        toshy_default_cfg_barebones = os.path.join(
            cnfg.toshy_dir_path, 'default-toshy-config', 'toshy_config_barebones.py')
        toshy_new_cfg = os.path.join(
            cnfg.toshy_dir_path, 'toshy_config.py')
        shutil.copy(toshy_default_cfg_barebones, toshy_new_cfg)
        print(f'Installed default "barebones" Toshy config file.')
    else:
        toshy_default_cfg = os.path.join(
            cnfg.toshy_dir_path, 'default-toshy-config', 'toshy_config.py')
        toshy_new_cfg = os.path.join(
            cnfg.toshy_dir_path, 'toshy_config.py')
        shutil.copy(toshy_default_cfg, toshy_new_cfg)
        print(f'Installed default Toshy config file.')
    print(f"Toshy files installed in '{cnfg.toshy_dir_path}'.")

    # Copy the existing user prefs database file
    if os.path.isfile(f'{cnfg.run_tmp_dir}/{cnfg.db_file_name}'):
        try:
            shutil.copy(f'{cnfg.run_tmp_dir}/{cnfg.db_file_name}', cnfg.toshy_dir_path)
            print(f'Copied preferences db file from existing config folder.')
        except (FileExistsError, FileNotFoundError, PermissionError, OSError) as file_err:
            error(f"Problem copying preferences db file from '{cnfg.run_tmp_dir}':\n\t{file_err}")

    # Apply user customizations to the new config file.
    new_cfg_file = os.path.join(cnfg.toshy_dir_path, 'toshy_config.py')
    if cnfg.existing_cfg_slices is not None:
        try:
            with open(new_cfg_file, 'r', encoding='UTF-8') as file:
                new_cfg_data = file.read()
        except (FileNotFoundError, PermissionError, OSError) as file_err:
            error(f'Problem reading new config file:\n\t{file_err}')
            safe_shutdown(1)
        merged_cfg_data = None
        try:
            merged_cfg_data = merge_slices(new_cfg_data, cnfg.existing_cfg_slices)
        except ValueError as value_err:
            error(f'Problem when merging user customizations with new config file:\n\t{value_err}')
        if merged_cfg_data is not None:
            try:
                with open(new_cfg_file, 'w', encoding='UTF-8') as file:
                    file.write(merged_cfg_data)
            except (FileNotFoundError, PermissionError, OSError) as file_err:
                error(f'Problem writing to new config file:\n\t{file_err}')
                safe_shutdown(1)
            print(f"Existing user customizations applied to the new config file.")
    show_task_completed_msg()


def setup_python_vir_env():
    """Setup a virtual environment to install Python packages"""
    print(f'\n\n§  Setting up the Python virtual environment...\n{cnfg.separator}')
    #
    # Create the virtual environment if it doesn't exist
    if not os.path.exists(cnfg.venv_path):
        # change the Python interpreter path to use current release version from pkg list
        # if distro is openSUSE Leap type (instead of old 3.6 version)
        if cnfg.DISTRO_NAME in distro_groups_map['leap-based']:
            if shutil.which(f'python{cnfg.curr_py_rel_ver_str}'):
                cnfg.py_interp_path = shutil.which(f'python{cnfg.curr_py_rel_ver_str}')
                print(f'Using Python version {cnfg.curr_py_rel_ver_str}.')
            else:
                print(  f'Current stable Python release version '
                        f'({cnfg.curr_py_rel_ver_str}) not found. ')
        else:
            print(f'Using Python version {cnfg.py_interp_ver}.')
        try:
            venv_cmd_lst = [cnfg.py_interp_path, '-m', 'venv', cnfg.venv_path]
            subprocess.run(venv_cmd_lst, check=True)
            # need to run the same command twice on OpenMandriva, for some reason
            if cnfg.DISTRO_NAME in ['openmandriva']:
                subprocess.run(venv_cmd_lst, check=True)
        except subprocess.CalledProcessError as proc_err:
            error(f'ERROR: Problem creating the Python virtual environment:\n\t{proc_err}')
            safe_shutdown(1)
    #
    # We do not need to "activate" the venv right now, just create it
    print(f'Python virtual environment setup complete.')
    show_task_completed_msg()


def install_pip_packages():
    """Install `pip` packages for Python"""
    print(f'\n\n§  Installing/upgrading Python packages...\n{cnfg.separator}')
    venv_python_cmd = os.path.join(cnfg.venv_path, 'bin', 'python')
    venv_pip_cmd    = os.path.join(cnfg.venv_path, 'bin', 'pip')

    pip_pkgs   = [
        # pinning pygobject to 3.44.1 (or earlier) to get through install on RHEL 8.x and clones
        # TODO: may need to pin other packages to go along with the pinned pygobject
        "lockfile", "dbus-python", "systemd-python", "pygobject<=3.44.1", "tk",
        "sv_ttk", "watchdog", "psutil", "hyprpy", "i3ipc", "pywayland", # "pywlroots",

        # installing 'pywlroots' will require native pkg 'libxkbcommon-devel' (Fedora)

        # TODO: Check on 'python-xlib' project by early-mid 2024 to see if this bug is fixed:
        #   [AttributeError: 'BadRRModeError' object has no attribute 'sequence_number']
        # If the bug is fixed, remove pinning to v0.31 here:

        # everything from 'inotify-simple' to 'six' is just to make `keyszer` install smoother
        "inotify-simple", "evdev", "appdirs", "ordered-set", "python-xlib==0.31", "six"
    ]

    # Filter out systemd packages if no 'systemctl' present
    filtered_pip_pkgs   = [
        pkg for pkg in pip_pkgs 
        if cnfg.systemctl_present or 'systemd' not in pkg
    ]

    commands        = [
        [venv_python_cmd, '-m', 'pip', 'install', '--upgrade', 'pip'],
        [venv_pip_cmd, 'install', '--upgrade', 'wheel'],
        [venv_pip_cmd, 'install', '--upgrade', 'setuptools'],
        [venv_pip_cmd, 'install', '--upgrade', 'pillow'],
        [venv_pip_cmd, 'install', '--upgrade'] + filtered_pip_pkgs
    ]
    for command in commands:
        result = subprocess.run(command)
        if result.returncode != 0:
            print(f'Error installing/upgrading Python packages. Installer exiting.')
            safe_shutdown(1)
    if os.path.exists(cnfg.keyszer_tmp_path):
        result = subprocess.run([venv_pip_cmd, 'install', '--upgrade', cnfg.keyszer_tmp_path])
        if result.returncode != 0:
            print(f'Error installing/upgrading "keyszer".')
            safe_shutdown(1)
    else:
        print(f'Temporary "keyszer" clone folder missing. Unable to install "keyszer".')
        safe_shutdown(1)
    show_task_completed_msg()


def install_bin_commands():
    """Install the convenient terminal commands (symlinks to scripts) to manage Toshy"""
    print(f'\n\n§  Installing Toshy terminal commands...\n{cnfg.separator}')
    script_path = os.path.join(cnfg.toshy_dir_path, 'scripts', 'toshy-bincommands-setup.sh')
    try:
        subprocess.run([script_path], check=True)
    except subprocess.CalledProcessError as proc_err:
        print()
        error(f'Problem while installing terminal commands:\n\t{proc_err}')
        safe_shutdown(1)
    show_task_completed_msg()


def replace_home_in_file(filename):
    """Utility function to replace '$HOME' in .desktop files with actual home path"""
    # Read in the file
    with open(filename, 'r') as file:
        file_data = file.read()
    # Replace the target string
    file_data = file_data.replace('$HOME', home_dir)
    # Write the file out again
    with open(filename, 'w') as file:
        file.write(file_data)


def install_desktop_apps():
    """Install the convenient desktop apps to manage Toshy"""
    print(f'\n\n§  Installing Toshy desktop apps...\n{cnfg.separator}')
    script_path = os.path.join(cnfg.toshy_dir_path, 'scripts', 'toshy-desktopapps-setup.sh')

    try:
        subprocess.run([script_path], check=True)
    except subprocess.CalledProcessError as proc_err:
        print()
        error(f'Problem installing Toshy desktop apps:\n\t{proc_err}')
        safe_shutdown(1)

    desktop_files_path  = os.path.join(home_dir, '.local', 'share', 'applications')
    tray_desktop_file   = os.path.join(desktop_files_path, 'Toshy_Tray.desktop')
    gui_desktop_file    = os.path.join(desktop_files_path, 'Toshy_GUI.desktop')

    replace_home_in_file(tray_desktop_file)
    replace_home_in_file(gui_desktop_file)
    show_task_completed_msg()


def setup_kwin2dbus_script():
    """Install the KWin script to notify D-Bus service about window focus changes"""
    print(f'\n\n§  Setting up the Toshy KWin script...\n{cnfg.separator}')
    if not shutil.which('kpackagetool5') or not shutil.which('kwriteconfig5'):
        print(f'One or more KDE CLI tools not found. Assuming older KDE...')
        return
    
    kwin_script_name    = 'toshy-dbus-notifyactivewindow'
    kwin_script_path    = os.path.join( cnfg.toshy_dir_path,
                                        'kde-kwin-dbus-service', kwin_script_name)
    script_tmp_file     = f'{cnfg.run_tmp_dir}/{kwin_script_name}.kwinscript'

    # Create a zip file (overwrite if it exists)
    with zipfile.ZipFile(script_tmp_file, 'w') as zipf:
        # Add main.js to the kwinscript package
        zipf.write(os.path.join(kwin_script_path, 'contents', 'code', 'main.js'),
                                arcname='contents/code/main.js')
        # Add metadata.desktop to the kwinscript package
        zipf.write(os.path.join(kwin_script_path, 'metadata.json'), arcname='metadata.json')

    # Try to remove any installed KWin script entirely
    process = subprocess.Popen(
        ['kpackagetool5', '-t', 'KWin/Script', '-r', kwin_script_name],
        stdout=PIPE, stderr=PIPE)
    out, err = process.communicate()
    out = out.decode('utf-8')
    err = err.decode('utf-8')
    result = subprocess.CompletedProcess(args=process.args, returncode=process.returncode,
                                            stdout=out, stderr=err)

    if result.returncode != 0:
        pass
    else:
        print("Successfully removed existing KWin script.")

    # Install the KWin script
    process = subprocess.Popen(
        ['kpackagetool5', '-t', 'KWin/Script', '-i', script_tmp_file],
        stdout=PIPE, stderr=PIPE)
    out, err = process.communicate()
    out = out.decode('utf-8')
    err = err.decode('utf-8')
    result = subprocess.CompletedProcess(args=process.args, returncode=process.returncode,
                                            stdout=out, stderr=err)

    if result.returncode != 0:
        error(f"Error installing the KWin script. The error was:\n\t{result.stderr}")
    else:
        print("Successfully installed the KWin script.")

    # Remove the temporary kwinscript file
    try:
        os.remove(script_tmp_file)
    except (FileNotFoundError, PermissionError): pass

    # Enable the script using kwriteconfig5
    process = subprocess.Popen(
        [   'kwriteconfig5', '--file', 'kwinrc', '--group', 'Plugins', '--key',
            f'{kwin_script_name}Enabled', 'true'], stdout=PIPE, stderr=PIPE)
    out, err = process.communicate()
    out = out.decode('utf-8')
    err = err.decode('utf-8')
    result = subprocess.CompletedProcess(args=process.args, returncode=process.returncode,
                                            stdout=out, stderr=err)

    if result.returncode != 0:
        error(f"Error enabling the KWin script. The error was:\n\t{result.stderr}")
    else:
        print("Successfully enabled the KWin script.")

    # Try to get KWin to notice and activate the script on its own, now that it's in RC file
    do_kwin_reconfigure()
    show_task_completed_msg()


def setup_kde_dbus_service():
    """Install the D-Bus service initialization script to receive window focus
    change notifications from the KWin script on KDE desktops (needed for Wayland)"""
    print(f'\n\n§  Setting up the Toshy KDE D-Bus service...\n{cnfg.separator}')

    # need to autostart "$HOME/.local/bin/toshy-kde-dbus-service"
    autostart_dir_path      = os.path.join(home_dir, '.config', 'autostart')
    dbus_svc_dt_file_path   = os.path.join(cnfg.toshy_dir_path, 'desktop')
    dbus_svc_desktop_file   = os.path.join(dbus_svc_dt_file_path, 'Toshy_KDE_DBus_Service.desktop')
    start_dbus_svc_cmd      = os.path.join(home_dir, '.local', 'bin', 'toshy-kde-dbus-service')
    replace_home_in_file(dbus_svc_desktop_file)

    # Where to put the new D-Bus service file:
    # ~/.local/share/dbus-1/services/org.toshy.Toshy.service
    dbus_svcs_path          = os.path.join(home_dir, '.local', 'share', 'dbus-1', 'services')
    toshy_kde_dbus_svc_path = os.path.join(cnfg.toshy_dir_path, 'kde-kwin-dbus-service')
    kde_dbus_svc_file       = os.path.join(toshy_kde_dbus_svc_path, 'org.toshy.Toshy.service')

    if not os.path.isdir(dbus_svcs_path):
        try:
            os.makedirs(dbus_svcs_path, exist_ok=True)
        except (PermissionError, NotADirectoryError) as file_err:
            error(f"Problem trying to make sure '{dbus_svcs_path}' is a directory:\n\t{file_err}")
            safe_shutdown(1)

    # STOP INSTALLING THIS, IT'S NOT HELPFUL
    # if os.path.isdir(dbus_svcs_path):
    #     shutil.copy(kde_dbus_svc_file, dbus_svcs_path)
    #     print(f"Installed '{kde_dbus_svc_file}' file at path:\n\t'{dbus_svcs_path}'.")
    # else:
    #     error(f"Path '{dbus_svcs_path}' is not a directory. Cannot continue.")
    #     safe_shutdown(1)

    # ensure autostart directory exists
    if not os.path.isdir(autostart_dir_path):
        try:
            os.makedirs(autostart_dir_path, exist_ok=True)
        except (PermissionError, NotADirectoryError) as file_err:
            error(f"Problem trying to make sure '{autostart_dir_path}' is directory.\n\t{file_err}")
            safe_shutdown(1)

    # try to delete old desktop entry file that would have been installed by code below
    autostart_dbus_dt_file = os.path.join(autostart_dir_path, 'Toshy_KDE_DBus_Service.desktop')
    if os.path.isfile(autostart_dbus_dt_file):
        try:
            os.unlink(autostart_dbus_dt_file)
            print(f'Removed older KDE D-Bus desktop entry autostart.')
        except subprocess.CalledProcessError as proc_err:
            debug(f'Problem removing old D-Bus service desktop entry autostart:\n\t{proc_err}')

    # # STOP DOING THIS, IN FAVOR OF SYSTEMD SERVICE, INSTALLED BY BASH SCRIPT
    # shutil.copy(dbus_svc_desktop_file, autostart_dir_path)
    # print(f'Toshy KDE D-Bus service should autostart at login.')
    # subprocess.run(['pkill', '-u', cnfg.user_name, '-f', 'toshy_kde_dbus_service'])
    # subprocess.Popen([start_dbus_svc_cmd], stdout=DEVNULL, stderr=DEVNULL)
    
    # # DON'T DO THIS HERE, IT'S IN THE KDE D-BUS SERVICE PYTHON SCRIPT NOW
    # # Try to kickstart the KWin script so that it can start sending focused window info
    # kickstart_script    = 'toshy-kwin-script-kickstart.sh'
    # kickstart_cmd       = os.path.join(cnfg.toshy_dir_path, 'scripts', kickstart_script)
    # subprocess.Popen([kickstart_cmd])

    print(f'Toshy KDE D-Bus service should automatically start when needed.')
    show_task_completed_msg()


def setup_systemd_services():
    """Invoke the systemd setup script to install the systemd service units"""
    print(f'\n\n§  Setting up the Toshy systemd services...\n{cnfg.separator}')
    if cnfg.systemctl_present and cnfg.init_system == 'systemd':
        script_path = os.path.join(cnfg.toshy_dir_path, 'scripts', 'bin', 'toshy-systemd-setup.sh')
        subprocess.run([script_path])
        print(f'Finished setting up Toshy systemd services.')
    else:
        print(f'System does not seem to be using "systemd" as init system.')
    show_task_completed_msg()


def autostart_tray_icon():
    """Set up the tray icon to autostart at login"""
    print(f'\n\n§  Setting up tray icon to load automatically at login...\n{cnfg.separator}')
    desktop_files_path  = os.path.join(home_dir, '.local', 'share', 'applications')
    tray_desktop_file   = os.path.join(desktop_files_path, 'Toshy_Tray.desktop')
    autostart_dir_path  = os.path.join(home_dir, '.config', 'autostart')
    dest_link_file      = os.path.join(autostart_dir_path, 'Toshy_Tray.desktop')

    # Need to create autostart folder if necessary
    try:
        os.makedirs(autostart_dir_path, exist_ok=True)
    except (PermissionError, NotADirectoryError) as file_err:
        error(f"Problem trying to make sure '{autostart_dir_path}' is directory.\n\t{file_err}")
        safe_shutdown(1)
    subprocess.run(['ln', '-sf', tray_desktop_file, dest_link_file])

    print(f'Toshy tray icon should appear in system tray at each login.')
    show_task_completed_msg()


###################################################################################################
##  TWEAKS UTILITY FUNCTIONS - START
###################################################################################################


def apply_tweaks_GNOME():
    """Utility function to add desktop tweaks to GNOME"""
    # Disable GNOME `overlay-key` binding to Meta/Super/Win/Cmd
    # gsettings set org.gnome.mutter overlay-key ''
    subprocess.run(['gsettings', 'set', 'org.gnome.mutter', 'overlay-key', ''])

    print(f'Disabled Super key opening the GNOME overview. (Use Cmd+Space instead.)')

    # TODO: Fix this so it doesn't mess up task switching on Apple keyboards (when set to Super+Tab)
    # # Set the keyboard shortcut for "Switch applications" to "Alt+Tab"
    # # gsettings set org.gnome.desktop.wm.keybindings switch-applications "['<Alt>Tab']"
    # subprocess.run(['gsettings', 'set', 'org.gnome.desktop.wm.keybindings',
    #                 'switch-applications', "['<Alt>Tab']"])
    # # Set the keyboard shortcut for "Switch windows of an application" to "Alt+`" (Alt+Grave)
    # # gsettings set org.gnome.desktop.wm.keybindings switch-group "['<Alt>grave']"
    # subprocess.run(['gsettings', 'set', 'org.gnome.desktop.wm.keybindings',
    #                 'switch-group', "['<Alt>grave']"])
    # print(f'Enabled "Switch applications" Mac-like task switching.')

    # Enable keyboard shortcut for GNOME Terminal preferences dialog
    # gsettings set org.gnome.Terminal.Legacy.Keybindings:/org/gnome/terminal/legacy/keybindings/ preferences '<Control>less'
    cmd_path = 'org.gnome.Terminal.Legacy.Keybindings:/org/gnome/terminal/legacy/keybindings/'
    prefs_binding = '<Control>comma'
    subprocess.run(['gsettings', 'set', cmd_path, 'preferences', prefs_binding])
    print(f'Set a keybinding for GNOME Terminal preferences.')

    # Enable "Expandable folders" in Nautilus
    # dconf write /org/gnome/nautilus/list-view/use-tree-view true
    cmd_path = '/org/gnome/nautilus/list-view/use-tree-view'
    subprocess.run(['dconf', 'write', cmd_path, 'true'])

    # Set default view option in Nautilus to "list-view"
    # dconf write /org/gnome/nautilus/preferences/default-folder-viewer "'list-view'"
    cmd_path = '/org/gnome/nautilus/preferences/default-folder-viewer'
    subprocess.run(['dconf', 'write', cmd_path, "'list-view'"])

    print(f'Set Nautilus default to "List" view with "Expandable folders" enabled.')


def remove_tweaks_GNOME():
    """Utility function to remove the tweaks applied to GNOME"""
    subprocess.run(['gsettings', 'reset', 'org.gnome.mutter', 'overlay-key'])
    print(f'Removed tweak to disable GNOME "overlay-key" binding to Meta/Super.')
    
    # gsettings reset org.gnome.desktop.wm.keybindings switch-applications
    subprocess.run(['gsettings', 'reset', 'org.gnome.desktop.wm.keybindings',
                    'switch-applications'])
    # gsettings reset org.gnome.desktop.wm.keybindings switch-group
    subprocess.run(['gsettings', 'reset', 'org.gnome.desktop.wm.keybindings', 'switch-group'])
    print(f'Removed tweak to enable more Mac-like task switching')


def apply_tweaks_KDE():
    """Utility function to add desktop tweaks to KDE"""

    if not shutil.which('kwriteconfig5'):
        print(f'KDE 5.x tools not present. Skipping KDE tweaks.')
        return

    # Documentation on the use of Meta key in KDE:
    # https://userbase.kde.org/Plasma/Tips#Windows.2FMeta_Key
    subprocess.run(['kwriteconfig5', '--file', 'kwinrc', '--group',
                    'ModifierOnlyShortcuts', '--key', 'Meta', ''], check=True)
    print(f'Disabled Meta key opening application menu. (Use Cmd+Space instead.)')

    # Run reconfigure command
    do_kwin_reconfigure()

    if cnfg.fancy_pants:
        print(f'Installing "Application Switcher" KWin script...')
        # How to install nclarius grouped "Application Switcher" KWin script:
        # git clone https://github.com/nclarius/kwin-application-switcher.git
        # cd kwin-application-switcher
        # ./install.sh
        # 
        # switcher_url        = 'https://github.com/nclarius/kwin-application-switcher.git'

        # TODO: Revert to main repo if/when patch for this is accepted.
        # Patched branch that fixes some issues with maintaining grouping:
        # 'https://github.com/RedBearAK/kwin-application-switcher/tree/grouping_fix'

        switcher_branch     = 'grouping_fix'
        switcher_repo       = (
            'https://github.com/RedBearAK/kwin-application-switcher.git'
        )

        switcher_dir_name   = 'kwin-application-switcher'
        switcher_dir_path   = os.path.join(this_file_dir, switcher_dir_name)
        switcher_title      = 'KWin Application Switcher'
        switcher_cloned     = False

        git_clone_cmd        = ['git', 'clone', '--branch',
                                switcher_branch, switcher_repo, switcher_dir_path]

        # git should be installed by this point? Not necessarily.
        if not shutil.which('git'):
            error(f"Unable to clone {switcher_title}. Install 'git' and try again.")
        else:
            if os.path.exists(switcher_dir_path):
                try:
                    shutil.rmtree(switcher_dir_path)
                except (FileNotFoundError, PermissionError, OSError) as file_err:
                    warn(f'Problem removing existing switcher clone folder:\n\t{file_err}')
            try:
                subprocess.run(git_clone_cmd, check=True) # , stdout=DEVNULL, stderr=DEVNULL)
                switcher_cloned = True
            except subprocess.CalledProcessError as proc_err:
                warn(f'Problem while cloning the {switcher_title} branch:\n\t{proc_err}')
            if not switcher_cloned:
                warn(f'Unable to install {switcher_title}. Clone did not succeed.')
            else:
                try:
                    subprocess.run(["./install.sh"], cwd=switcher_dir_path, check=True,
                                    stdout=DEVNULL, stderr=DEVNULL)
                    print(f'Installed "{switcher_title}" KWin script.')
                except subprocess.CalledProcessError as proc_err:
                    warn(f'Something went wrong installing {switcher_title}.\n\t{proc_err}')

        do_kwin_reconfigure()

        # Set the LayoutName value to big_icons (shows task switcher with large icons, no previews)
        LayoutName_cmd = ['kwriteconfig5', '--file', 'kwinrc', '--group', 'TabBox',
                            '--key', 'LayoutName', 'big_icons']
        subprocess.run(LayoutName_cmd, check=True)
        print(f'Set task switcher style to: "Large Icons"')

        # Set the HighlightWindows value to false (disables "Show selected window" option)
        HighlightWindows_cmd = ['kwriteconfig5', '--file', 'kwinrc', '--group', 'TabBox',
                                '--key', 'HighlightWindows', 'false']
        subprocess.run(HighlightWindows_cmd, check=True)
        print(f'Disabled task switcher option: "Show selected window"')

        # Set the ApplicationsMode value to 1 (enables "Only one window per application" option)
        ApplicationsMode_cmd = ['kwriteconfig5', '--file', 'kwinrc', '--group', 'TabBox',
                                '--key', 'ApplicationsMode', '1']
        subprocess.run(ApplicationsMode_cmd, check=True)
        print(f'Enabled task switcher option: "Only one window per application"')

        do_kwin_reconfigure()

        # Disable single click to open/launch files/folders:
        # kwriteconfig5 --file kdeglobals --group KDE --key SingleClick false
        SingleClick_cmd = ['kwriteconfig5', '--file', 'kdeglobals', '--group', 'KDE',
                            '--key', 'SingleClick', 'false']
        subprocess.run(SingleClick_cmd, check=True)
        print('Disabled single-click to open/launch files/folders')

        # Restart Plasma shell to make the new setting active
        # killall plasmashell && kstart5 plasmashell
        try:
            if shutil.which('kquitapp5'):
                print('Stopping Plasma shell... ', flush=True, end='')
                subprocess.run(['kquitapp5', 'plasmashell'], check=True,
                                stdout=PIPE, stderr=PIPE)
                print('Plasma shell stopped.')
            else:
                error('The "kquitapp5" command is not found. Skipping plasmashell restart.')
        except subprocess.CalledProcessError as proc_err:
            err_output: bytes = proc_err.stderr             # type hint error output
            error(f'\nProblem while stopping Plasma shell:\n\t{err_output.decode()}')

        print('Starting Plasma shell (backgrounded)... ')
        subprocess.Popen(['kstart5', 'plasmashell'], stdout=PIPE, stderr=PIPE)

        # THIS STUFF DOESN'T SEEM TO WORK!
        # Disable "sort folders first" option in Dolphin:
        # kwriteconfig5 --file dolphinrc --group General --key FirstSortingFolders false
        # kwriteconfig5 --file kdeglobals --group "KFileDialog Settings" --key "Sort directories first" false 
        # FirstSortingFolders_cmd = ['kwriteconfig5', '--file', 'dolphinrc',
        #                             '--group', 'General',
        #                             '--key', 'FirstSortingFolders', 'false']
        # subprocess.run(FirstSortingFolders_cmd, check=True)
        # print('Disabled "sort folders first" option in Dolphin.')
        # # kquitapp5 dolphin && dolphin &
        # print('Restarting Dolphin file manager...')
        # try:
        #     subprocess.run(['kquitapp5', 'dolphin'], check=True)
        #     subprocess.Popen('dolphin')
        #     print('Dolphin file manager restarted.')
        # except subprocess.CalledProcessError as proc_err:
        #     error(f'Problem restarting Dolphin file manager:\n\t{proc_err}')


def remove_tweaks_KDE():
    """Utility function to remove the tweaks applied to KDE"""
    if not shutil.which('kwriteconfig5'):
        return

    # Re-enable Meta key opening the application menu
    subprocess.run(['kwriteconfig5', '--file', 'kwinrc', '--group',
                    'ModifierOnlyShortcuts', '--key', 'Meta', '--delete'], check=True)
    # Disable the "Only one window per application" task switcher option
    subprocess.run(['kwriteconfig5', '--file', 'kwinrc', '--group', 'TabBox', 
                    '--key', 'ApplicationsMode', '--delete'], check=True)

    # Run reconfigure command
    do_kwin_reconfigure()
    print(f'Re-enabled Meta key opening application menu.')
    print(f'Disabled "Only one window per application" task switcher option.')


###################################################################################################
##  TWEAKS UTILITY FUNCTIONS - END
###################################################################################################


def apply_desktop_tweaks():
    """
    Fix things like Meta key activating overview in GNOME or KDE Plasma
    and fix the Unicode sequences in KDE Plasma
    
    TODO: These tweaks should probably be done at startup of the config
            instead of (or in addition to) here in the installer. 
    """

    print(f'\n\n§  Applying any known desktop environment tweaks...\n{cnfg.separator}')

    if cnfg.fancy_pants:
        print(f'Fancy-Pants install invoked. Additional steps will be taken.')

    if cnfg.DESKTOP_ENV == 'gnome':
        print(f'Applying GNOME desktop tweaks...')
        apply_tweaks_GNOME()
        cnfg.tweak_applied = True

    if cnfg.DESKTOP_ENV == 'kde':
        print(f'Applying KDE Plasma desktop tweaks...')
        apply_tweaks_KDE()
        cnfg.tweak_applied = True

    # General (not DE specific) "fancy pants" additions:
    if cnfg.fancy_pants:

        print(f'Installing font: ', end='', flush=True)

        # install Fantasque Sans Mono NoLig (no ligatures) from GitHub fork
        font_file   = 'FantasqueSansMono-LargeLineHeight-NoLoopK-NameSuffix.zip'
        font_url    = 'https://github.com/spinda/fantasque-sans-ligatures/releases/download/v1.8.1'
        font_link   = f'{font_url}/{font_file}'

        print(f'Downloading… ', end='', flush=True)

        zip_path    = f'{cnfg.run_tmp_dir}/{font_file}'
        
        if shutil.which('curl'):
            subprocess.run(['curl', '-Lo', zip_path, font_link], 
                        stdout=DEVNULL, stderr=DEVNULL)
        elif shutil.which('wget'):
            subprocess.run(['wget', '-O', zip_path, font_link],
                        stdout=DEVNULL, stderr=DEVNULL)
        else:
            print("\nERROR: Neither 'curl' nor 'wget' is available. Can't install font.")

        if os.path.isfile(zip_path):
            folder_name = font_file.rsplit('.', 1)[0]
            extract_dir = f'{cnfg.run_tmp_dir}/'

            print(f'Unzipping… ', end='', flush=True)

            # Open the zip file and check if it has a top-level directory
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Get the first part of each path in the zip file
                top_dirs = {name.split('/')[0] for name in zip_ref.namelist()}
                
                # If the zip doesn't have a consistent top-level directory, create one and adjust extract_dir
                if len(top_dirs) > 1:
                    extract_dir = os.path.join(extract_dir, folder_name)
                    os.makedirs(extract_dir, exist_ok=True)
                
                zip_ref.extractall(extract_dir)

            # use TTF instead of OTF to try and minimize "stem darkening" effect in KDE
            font_dir        = f'{extract_dir}/TTF/'
            local_fonts_dir = os.path.join(home_dir, '.local', 'share', 'fonts')

            os.makedirs(local_fonts_dir, exist_ok=True)

            print(f'Moving… ', end='', flush=True)

            for file in os.listdir(font_dir):
                if file.endswith('.ttf'):
                    src_path = os.path.join(font_dir, file)
                    dest_path = os.path.join(local_fonts_dir, file)
                    shutil.move(src_path, dest_path)

            print(f'Refreshing font cache… ', end='', flush=True)

            # Update the font cache
            subprocess.run(['fc-cache', '-f', '-v'],
                            stdout=DEVNULL, stderr=DEVNULL)
            print(f'Done.', flush=True)

            print(f"Installed font: '{folder_name}'")
            cnfg.tweak_applied = True

    if not cnfg.tweak_applied:
        print(f'If nothing printed, no tweaks available for "{cnfg.DESKTOP_ENV}" yet.')
    show_task_completed_msg()


def remove_desktop_tweaks():
    """Undo the relevant desktop tweaks"""

    print(f'\n\n§  Removing any applied desktop environment tweaks...\n{cnfg.separator}')

    # if GNOME, re-enable `overlay-key`
    # gsettings reset org.gnome.mutter overlay-key
    if cnfg.DESKTOP_ENV == 'gnome':
        print(f'Removing GNOME desktop tweaks...')
        remove_tweaks_GNOME()

    if cnfg.DESKTOP_ENV == 'kde':
        print(f'Removing KDE Plasma desktop tweaks...')
        remove_tweaks_KDE()
        
    print('Removed known desktop tweaks applied by installer.')
    show_task_completed_msg()


def uninstall_toshy():
    print(f'\n\n§  Uninstalling Toshy...\n{cnfg.separator}')
    
    # confirm if user really wants to uninstall
    response = input("\nThis will completely uninstall Toshy. Are you sure? [y/N]: ")
    if response not in ['y', 'Y']:
        print(f"\nToshy uninstall cancelled.")
        safe_shutdown(0)
    else:
        print(f'\nToshy uninstall proceeding...\n')
    
    get_environment_info()
    
    remove_desktop_tweaks()
    
    # stop Toshy manual script if it is running
    toshy_cfg_stop_cmd = os.path.join(home_local_bin, 'toshy-config-stop')
    subprocess.run([toshy_cfg_stop_cmd])
    
    if cnfg.systemctl_present and cnfg.init_system == 'systemd':
        # stop Toshy systemd services if they are running
        toshy_svcs_stop_cmd = os.path.join(home_local_bin, 'toshy-services-stop')
        subprocess.run([toshy_svcs_stop_cmd])
        # run the systemd-remove script
        sysd_rm_cmd = os.path.join(cnfg.toshy_dir_path, 'scripts', 'bin', 'toshy-systemd-remove.sh')
        subprocess.run([sysd_rm_cmd])
    else:
        print(f'System does not seem to be using "systemd". Skipping removal of services.')

    if cnfg.DESKTOP_ENV in ['kde', 'plasma']:
        # unload/uninstall/remove KWin script(s)
        kwin_script_name = 'toshy-dbus-notifyactivewindow'
        try:
            subprocess.run(['kpackagetool5', '-t', 'KWin/Script', '-r', kwin_script_name], check=True)
            print("Successfully removed the KWin script.")
        except subprocess.CalledProcessError as proc_err:
            error(f'Problem removing Toshy KWin script {kwin_script_name}:\n\t{proc_err}')

        # kill the KDE D-Bus service script
        try:
            subprocess.run(['pkill', '-u', cnfg.user_name, '-f', 'toshy_kde_dbus_service'], check=True)
        except subprocess.CalledProcessError as proc_err:
            error(f'Problem terminating Toshy KDE D-Bus service script:\n\t{proc_err}')

    # try to remove the KDE D-Bus service autostart file
    autostart_dir_path  = os.path.join(home_dir, '.config', 'autostart')
    dbus_svc_dt_file    = os.path.join(autostart_dir_path, 'Toshy_KDE_DBus_Service.desktop')

    dbus_svc_rm_cmd = ['rm', '-f', dbus_svc_dt_file]
    try:
        # do not pass as list (brackets) since it is already a list
        subprocess.run(dbus_svc_rm_cmd, check=True)
    except subprocess.CalledProcessError as proc_err:
        error(f'Problem removing Toshy KDE D-Bus service autostart:\n\t{proc_err}')

    # terminate the tray icon process
    stop_tray_cmd = ['pkill', '-u', cnfg.user_name, '-f', 'toshy_tray']
    try:
        # do not pass as list (brackets) since it is already a list
        subprocess.run(stop_tray_cmd, check=True)
    except subprocess.CalledProcessError as proc_err:
        print(f'Problem stopping the tray icon process:\n\t{proc_err}')
    # remove the tray icon autostart file
    tray_autostart_file = os.path.join(autostart_dir_path, 'Toshy_Tray.desktop')

    tray_autostart_rm_cmd = ['rm', '-f', tray_autostart_file]
    try:
        # do not pass as list (brackets) since it is already a list
        subprocess.run(tray_autostart_rm_cmd, check=True)
    except subprocess.CalledProcessError as proc_err:
        error(f'Problem removing Toshy tray icon autostart:\n\t{proc_err}')

    # run the desktopapps-remove script
    apps_rm_cmd = os.path.join(cnfg.toshy_dir_path, 'scripts', 'toshy-desktopapps-remove.sh')
    try:
        subprocess.run([apps_rm_cmd], check=True)
    except subprocess.CalledProcessError as proc_err:
        error(f'Problem removing Toshy desktop apps:\n\t{proc_err}')

    # run the bincommands-remove script
    bin_rm_cmd = os.path.join(cnfg.toshy_dir_path, 'scripts', 'toshy-bincommands-remove.sh')
    try:
        subprocess.run([bin_rm_cmd], check=True)
    except subprocess.CalledProcessError as proc_err:
        error(f'Problem removing Toshy bin commands apps:\n\t{proc_err}')

    response_rm_udev_rules = input('Remove the Toshy "udev/uinput" rules file? [y/N]: ')
    if response_rm_udev_rules.lower() == 'y':
        elevate_privileges()
        # define the udev rules file path
        udev_rules_file = '/etc/udev/rules.d/90-toshy-keymapper-input.rules'
        # remove the 'udev' rules file
        try:
            subprocess.run(['sudo', 'rm', '-f', udev_rules_file], check=True)
        except subprocess.CalledProcessError as proc_err:
            error(f'Problem removing Toshy udev rules file:\n\t{proc_err}')
        # refresh the active 'udev' rules
        reload_udev_rules()

    print()
    print()
    print(cnfg.separator)
    print(f'Toshy uninstall complete. Reboot if indicated above with ASCII banner.')
    print(f"The '~/.config/toshy' folder with your settings has NOT been removed.")
    print(f'Please report any problems or leftover files/commands on the GitHub repo:')
    print(f'https://github.com/RedBearAK/toshy/issues/')
    print(cnfg.separator)
    print()


def handle_cli_arguments():
    """Deal with CLI arguments given to installer script"""
    parser = argparse.ArgumentParser(
        description='Toshy Installer - some options are mutually exclusive',
        epilog='Default action: Install Toshy',
        allow_abbrev=False
    )

    # Add arguments
    parser.add_argument(
        '--override-distro',
        type=str,
        # dest='override_distro',
        help=f'Override auto-detection of distro. See "--list-distros"'
    )
    parser.add_argument(
        '--list-distros',
        action='store_true',
        help='Display list of distros to use with "--override-distro"'
    )
    parser.add_argument(
        '--uninstall',
        action='store_true',
        help='Uninstall Toshy'
    )
    parser.add_argument(
        '--show-env',
        action='store_true',
        help='Show the environment the installer detects, and exit'
    )
    parser.add_argument(
        '--apply-tweaks',
        action='store_true',
        help='Apply desktop environment tweaks only, no install'
    )
    parser.add_argument(
        '--remove-tweaks',
        action='store_true',
        help='Remove desktop environment tweaks only, no install'
    )
    parser.add_argument(
        '--barebones-config',
        action='store_true',
        help='Install with mostly empty/blank keymapper config file.'
    )
    parser.add_argument(
        '--skip-native',
        action='store_true',
        help='Skip the install of native packages (for debugging installer).'
    )
    parser.add_argument(
        '--fancy-pants',
        action='store_true',
        help='See README for more info on this option.'
    )

    args = parser.parse_args()

    exit_args_dct = {
        '--uninstall':          args.uninstall,
        '--show-env':           args.show_env,
        '--list-distros':       args.list_distros,
    }

    all_args_dct = {
        '--apply-tweaks':       args.apply_tweaks,
        '--remove-tweaks':      args.remove_tweaks,
        '--override-distro':    bool(args.override_distro),
        '--barebones-config':   args.barebones_config,
        '--skip-native':        args.skip_native,
        '--fancy-pants':        args.fancy_pants,
        **exit_args_dct
    }

    # Check that "exit-after" arguments are used alone
    if any(exit_args_dct.values()) and sum(all_args_dct.values()) > 1:
        error(f"ERROR: These options should be used alone:\n" +
            ''.join(f"\n\t{arg}" for arg in exit_args_dct.keys()))
        safe_shutdown(1)

    if args.uninstall:
        uninstall_toshy()
        safe_shutdown(0)

    if args.show_env:
        get_environment_info()
        safe_shutdown(0)

    if args.list_distros:
        print(  f'Distros known to the Toshy installer (use with "--override-distro" arg):'
                f'\n\n\t{get_distro_names()}')
        safe_shutdown(0)

    if args.barebones_config:
        cnfg.barebones_config = True

    if args.skip_native:
        cnfg.skip_native = True

    if args.fancy_pants:
        cnfg.fancy_pants = True

    if args.apply_tweaks:
        get_environment_info()
        apply_desktop_tweaks()
        if cnfg.should_reboot:
            show_reboot_prompt()
            print(f'{cnfg.sep_char * 2}  Tweaks application complete. Report issues on the GitHub repo.')
            print(f'{cnfg.sep_char * 2}  https://github.com/RedBearAK/toshy/issues/')
            print(f'{cnfg.sep_char * 2}  >>  ALERT: Something odd happened. You should probably reboot.')
            print(cnfg.separator)
            print(cnfg.separator)
            print()
        safe_shutdown(0)

    if args.remove_tweaks:
        get_environment_info()
        remove_desktop_tweaks()
        safe_shutdown(0)

    if args.override_distro:
        cnfg.override_distro = args.override_distro


def main(cnfg: InstallerSettings):
    """Main installer function to call specific functions in proper sequence"""

    dot_Xmodmap_warning()
    ask_is_distro_updated()
    ask_add_home_local_bin()

    get_environment_info()

    if cnfg.DISTRO_NAME not in get_distro_names():
        exit_with_invalid_distro_error()

    elevate_privileges()

    if not cnfg.skip_native:
        install_distro_pkgs()

    load_uinput_module()
    install_udev_rules()
    verify_user_groups()

    clone_keyszer_branch()

    backup_toshy_config()
    install_toshy_files()

    setup_python_vir_env()
    install_pip_packages()

    install_bin_commands()
    install_desktop_apps()

    # Python D-Bus service script also does this, but this will refresh if script changes
    if cnfg.DESKTOP_ENV in ['kde', 'plasma']:
        setup_kwin2dbus_script()

    setup_kde_dbus_service()

    setup_systemd_services()

    autostart_tray_icon()
    apply_desktop_tweaks()

    if cnfg.DESKTOP_ENV == 'gnome':
        print()
        def is_extension_enabled(extension_uuid):
            try:
                output = subprocess.check_output(
                            ['gsettings', 'get', 'org.gnome.shell', 'enabled-extensions'])
                extensions = output.decode().strip().replace("'", "").split(",")
            except subprocess.CalledProcessError as proc_err:
                error(f"Unable to check enabled extensions:\n\t{proc_err}")
                return False
            return extension_uuid in extensions

        if is_extension_enabled("appindicatorsupport@rgcjonas.gmail.com"):
            print("AppIndicator extension is enabled. Tray icon should work.")
        else:
            print()
            debug(f"RECOMMENDATION: Install 'AppIndicator' GNOME extension\n"
                "Easiest method: 'flatpak install extensionmanager', search for 'appindicator'\n",
                ctx="!!")

    if cnfg.should_reboot or os.path.exists(cnfg.reboot_tmp_file):
        cnfg.should_reboot = True
        # create reboot reminder temp file, in case installer is run again before a reboot
        if not os.path.exists(cnfg.reboot_tmp_file):
            os.mknod(cnfg.reboot_tmp_file)
        show_reboot_prompt()
        print(f'{cnfg.sep_char * 2}  Toshy install complete. Report issues on the GitHub repo.')
        print(f'{cnfg.sep_char * 2}  https://github.com/RedBearAK/toshy/issues/')
        print(f'{cnfg.sep_char * 2}  >>  ALERT: Permissions changed. You MUST reboot for Toshy to work.')
        print(cnfg.separator)
        print(cnfg.separator)
        print()
    else:
        # Try to start the tray icon immediately, if reboot is not indicated
        tray_icon_cmd = [os.path.join(home_dir, '.local', 'bin', 'toshy-tray')]
        # Try to launch the tray icon in a separate process not linked to current shell
        # Also, suppress output that might confuse the user
        subprocess.Popen(tray_icon_cmd, close_fds=True, stdout=DEVNULL, stderr=DEVNULL)
        print()
        print()
        print()
        print(cnfg.separator)
        print(cnfg.separator)
        print(f'{cnfg.sep_char * 2}  Toshy install complete. Rebooting should not be necessary.')
        print(f'{cnfg.sep_char * 2}  Report issues on the GitHub repo.')
        print(f'{cnfg.sep_char * 2}  https://github.com/RedBearAK/toshy/issues/')
        print(cnfg.separator)
        print(cnfg.separator)
        print()
        if cnfg.SESSION_TYPE == 'wayland' and cnfg.DESKTOP_ENV == 'kde':
            print(f'Switch to a different window ONCE to get KWin script to start working!')

    if cnfg.remind_extensions or (cnfg.DESKTOP_ENV == 'gnome' and cnfg.SESSION_TYPE == 'wayland'):
        print(f'You MUST install GNOME EXTENSIONS if using Wayland+GNOME! See Toshy README.')

    # print()   # blank line to avoid crowding the prompt after install is done
    safe_shutdown(0)


if __name__ == '__main__':

    print()   # blank line in terminal to start things off

    # Invalidate any `sudo` ticket that might be hanging around, to maximize 
    # the length of time before `sudo` might demand the password again
    try:
        subprocess.run(['sudo', '-k'], check=True)
    except subprocess.CalledProcessError as proc_err:
        error(f"ERROR: 'sudo' found, but 'sudo -k' did not work. Very strange.\n\t{proc_err}")

    # create the configuration settings class instance
    cnfg                        = InstallerSettings()

    # create the native package installer class instance
    native_pkg_installer        = NativePackageInstaller()

    handle_cli_arguments()

    # proceed with install sequence if no CLI args triggered an exit-after action
    main(cnfg)