#!/usr/bin/env python

import sys
import os
import json
import argparse
import subprocess
import logging
import time
import requests
import semver
from pexpect import pxssh
from pexpect.exceptions import EOF
from pexpect.pxssh import ExceptionPxssh

from aeon.cumulus.device import Device
from paramiko import AuthenticationException
from paramiko.ssh_exception import NoValidConnectionsError

_PROGNAME = 'cumulus_bootstrap'
_PROGVER = '0.0.1'
_OS_NAME = 'cumulus'

_DEFAULTS = {
    'init-delay': 5,
    'reload-delay': 10 * 60,
}

# ##### -----------------------------------------------------------------------
# #####
# #####                           Command Line Arguments
# #####
# ##### -----------------------------------------------------------------------


def cli_parse(cmdargs=None):
    psr = argparse.ArgumentParser(
        prog=_PROGNAME,
        description="Aeon-ZTP bootstrapper for Cumulus Linux",
        add_help=True)

    psr.add_argument(
        '--target', required=True,
        help='hostname or ip_addr of target device')

    psr.add_argument(
        '--server', required=True,
        help='Aeon-ZTP host:port')

    psr.add_argument(
        '--topdir', required=True,
        help='Aeon-ZTP install directory')

    psr.add_argument(
        '--logfile',
        help='name of log file')

    psr.add_argument(
        '--reload-delay',
        type=int, default=_DEFAULTS['reload-delay'],
        help="about of time/s to try to reconnect to device after reload")

    psr.add_argument(
        '--init-delay',
        type=int, default=_DEFAULTS['init-delay'],
        help="amount of time/s to wait before starting the bootstrap process")

    # ##### -------------------------
    # ##### authentication
    # ##### -------------------------

    group = psr.add_argument_group('authentication')

    group.add_argument(
        '--user', help='login user-name')

    group.add_argument(
        '-U', '--env_user',
        help='Username environment variable')

    group.add_argument(
        '-P', '--env_passwd',
        required=True,
        help='Passwd environment variable')

    return psr.parse_args(cmdargs)


def setup_logging(logname, logfile, target):
    log = logging.getLogger(name=logname)
    log.setLevel(logging.INFO)

    fmt = logging.Formatter(
        '%(asctime)s:%(levelname)s:{target}:%(message)s'
        .format(target=target))

    handler = logging.FileHandler(logfile) if logfile else logging.StreamHandler(sys.stdout)
    handler.setFormatter(fmt)
    log.addHandler(handler)

    return log


class CumulusBootstrap:
    def __init__(self, self_server, cli_args):
        self.self_server = self_server
        self.cli_args = cli_args
        self.log = setup_logging(logname=_PROGNAME,
                                 logfile=self.cli_args.logfile,
                                 target=self.cli_args.target)

    # ##### -----------------------------------------------------------------------
    # #####
    # #####                           REST API functions
    # #####
    # ##### -----------------------------------------------------------------------

    def post_device_facts(self, dev):
        requests.put(
            url='http://%s/api/devices/facts' % self.self_server,
            json=dict(
                ip_addr=dev.target,
                serial_number=dev.facts['serial_number'],
                hw_model=dev.facts['hw_model'],
                os_version=dev.facts['os_version'],
                os_name=_OS_NAME))

    def post_device_status(self, dev=None, target=None, message=None, state=None):
        requests.put(
            url='http://%s/api/devices/status' % self.self_server,
            json=dict(
                os_name=_OS_NAME,
                ip_addr=target or dev.target,
                state=state, message=message))

    # ##### -----------------------------------------------------------------------
    # #####
    # #####                           Utility Functions
    # #####
    # ##### -----------------------------------------------------------------------

    def exit_results(self, results, exit_error=None, dev=None, target=None):
        if results['ok']:
            self.post_device_status(dev=dev, target=target, state='DONE', message='bootstrap completed OK')
            sys.exit(0)
        else:
            self.post_device_status(dev=dev, target=target, state='FAILED', message=results['message'])
            sys.exit(exit_error or 1)

    def wait_for_device(self, countdown, poll_delay, msg=None):
        target = self.cli_args.target
        user = self.cli_args.user or os.getenv(self.cli_args.env_user)
        passwd = os.getenv(self.cli_args.env_passwd)

        if not user:
            errmsg = "login user-name missing"
            self.log.error(errmsg)
            self.exit_results(target=target, results=dict(
                ok=False,
                error_type='login',
                message=errmsg))

        if not passwd:
            errmsg = "login user-password missing"
            self.log.error(errmsg)
            self.exit_results(target=target, results=dict(
                ok=False,
                error_type='login',
                message=errmsg))

        dev = None

        # first we need to wait for the device to be 'reachable' via the API.
        # we'll use the probe error to detect if it is or not

        while not dev:
            new_msg = msg or 'OS installation in progress. Timeout remaining: {} seconds'.format(countdown)
            self.post_device_status(target=target, state='AWAIT-ONLINE', message=new_msg)
            self.log.info(new_msg)

            try:
                dev = Device(target, user=user, passwd=passwd,
                             timeout=poll_delay)

            except AuthenticationException as e:
                self.log.info('Authentication exception reported: {} \n args: {}'.format(e, e.args))
                self.exit_results(target=target, results=dict(
                    ok=False,
                    error_type='login',
                    message='Unauthorized - check user/password'))

            except NoValidConnectionsError as e:
                countdown -= poll_delay
                if countdown <= 0:
                    self.exit_results(target=target, results=dict(
                        ok=False,
                        error_type='login',
                        message='Failed to connect to target %s within reload countdown' % target))

                time.sleep(poll_delay)

        self.post_device_facts(dev)
        return dev

    def wait_for_onie_rescue(self, countdown, poll_delay, user='root'):
        """Polls for SSH access to cumulus device in ONIE rescue mode.

        The poll functionality was necessary in addition to the current wait_for_device function
        because of incompatibilities with the dropbear_2013 OS that is on the cumulus switches and
        paramiko in the existing function.

        Args:
            countdown (int): Countdown in seconds to wait for device to become reachable.
            poll_delay (int): Countdown in seconds between poll attempts.
            user (str): SSH username to use. Defaults to 'root'.

        """
        target = self.cli_args.target
        while countdown >= 0:
            try:
                msg = 'Cumulus installation in progress. Waiting for boot to ONIE rescue mode. Timeout remaining: {} seconds'.format(countdown)
                self.post_device_status(target=target, state='AWAIT-ONLINE', message=msg)
                self.log.info(msg)
                ssh = pxssh.pxssh(options={"StrictHostKeyChecking": "no", "UserKnownHostsFile": "/dev/null"})
                ssh.login(target, user, auto_prompt_reset=False)
                ssh.PROMPT = 'ONIE:.*#'
                ssh.sendline('\n')
                ssh.prompt()

                return True
            except (ExceptionPxssh, EOF) as e:
                if (str(e) == 'Could not establish connection to host') or isinstance(e, EOF):
                    ssh.close()
                    countdown -= poll_delay
                    time.sleep(poll_delay)
                else:
                    self.log.error('Error accessing {} in ONIE rescue mode: {}.'.format(target, str(e)))
                    self.exit_results(target=target, results=dict(
                        ok=False,
                        error_type='login',
                        message='Error accessing {} in ONIE rescue mode: {}.'.format(target, str(e))))
        else:
            self.log.error('Device {} not reachable in ONIE rescue mode within reload countdown.'.format(target))
            self.exit_results(target=target, results=dict(
                ok=False,
                error_type='login',
                message='Device {} not reachable in ONIE rescue mode within reload countdown.'.format(target)))

    # ##### -----------------------------------------------------------------------
    # #####
    # #####                           OS install process
    # #####
    # ##### -----------------------------------------------------------------------

    def get_required_os(self, dev):
        profile_dir = os.path.join(self.cli_args.topdir, 'etc', 'profiles', 'default', _OS_NAME)
        conf_fpath = os.path.join(profile_dir, 'os-selector.cfg')

        cmd = "{topdir}/bin/aztp_os_selector.py -j '{dev_json}' -c {config}".format(
            topdir=self.cli_args.topdir,
            dev_json=json.dumps(dev.facts),
            config=conf_fpath)

        self.log.info('os-select: [%s]' % cmd)

        child = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)

        _stdout, _stderr = child.communicate()
        self.log.info('os-select rc={}, stdout={}'.format(child.returncode, _stdout))
        self.log.info('os-select stderr={}'.format(_stderr))

        try:
            return json.loads(_stdout)

        except Exception:
            errmsg = 'Unable to load os-select output as JSON: {}'.format(_stdout)
            self.exit_results(dev=dev, results=dict(
                ok=False,
                error_type='install',
                message=errmsg))

    def onie_install(self, dev, image_name, user='root'):
        """Initiates install in ONIE-RESCUE mode.

        Args:
            dev (Device object): Cumulus device object
            image_name (str): Name of image to download
            user (str): ONIE rescue mode user
        """

        msg = 'Cumulus download and verification in progress.'
        self.post_device_status(dev=dev, state='ONIE-RESCUE', message=msg)
        self.log.info(msg)
        try:
            ssh = pxssh.pxssh(options={"StrictHostKeyChecking": "no", "UserKnownHostsFile": "/dev/null"})
            ssh.login(dev.target, user, auto_prompt_reset=False)
            ssh.PROMPT = 'ONIE:.*#'
            ssh.sendline('\n')
            ssh.prompt()

            # Start installation process
            ssh.sendline('onie-nos-install http://{server}/images/{os_name}/{image_name}'
                         .format(server=self.cli_args.server, os_name=_OS_NAME, image_name=image_name))

            # 'installer' means that the download has started
            ssh.expect('installer', timeout=15)

            # Indicates that the image has been downloaded and verified
            ssh.expect('Please reboot to start installing OS.', timeout=180)

            ssh.prompt()
            ssh.sendline('reboot')
            time.sleep(2)
            ssh.close()

            msg = 'Cumulus download completed and verified, reboot initiated.'
            self.log.info(msg)
            self.post_device_status(dev=dev, state='OS-INSTALL', message=msg)
            return True

        except pxssh.ExceptionPxssh as e:
            self.log.info(str(e))
            self.exit_results(dev=dev, target=self.cli_args.target, results=dict(ok=False, error_type='install', message=e))

    def install_os(self, dev, image_name):
        vendor_dir = os.path.join(self.cli_args.topdir, 'vendor_images', _OS_NAME)

        image_fpath = os.path.join(vendor_dir, image_name)
        if not os.path.exists(image_fpath):
            errmsg = 'image file does not exist: %s' % image_fpath
            self.log.error(errmsg)
            self.exit_results(dev=dev, results=dict(
                ok=False, error_type='install',
                message=errmsg))

        msg = 'Installing Cumulus image=[%s] ... this can take up to 30 min.' % image_name
        self.log.info(msg)
        self.post_device_status(dev=dev, state='OS-INSTALL', message=msg)

        os_semver = semver.parse_version_info(dev.facts['os_version'])

        # Cumulus 2.x upgrade command is removed in Cumulus 3.x, so two upgrade methods are required
        # Cumulus 2.x upgrade
        if os_semver.major == 2:
            install_command = 'sudo /usr/cumulus/bin/cl-img-install -sf http://{server}/images/{os_name}/{image_name}'.format(server=self.cli_args.server, os_name=_OS_NAME, image_name=image_name)
            all_good, results = dev.api.execute([install_command])
            if not all_good:
                errmsg = 'Unable to run command: {}. Error message: {}'.format(install_command, results)
                self.exit_results(dev=dev, results=dict(
                    ok=False,
                    error_type='install',
                    message=errmsg))
        # Cumulus 3.x upgrade
        else:
            install_command = 'sudo onie-select -rf'
            all_good, results = dev.api.execute([install_command])
            if not all_good:
                errmsg = 'Unable to run command: {}. Error message: {}'.format(install_command, results)
                self.exit_results(dev=dev, results=dict(
                    ok=False,
                    error_type='install',
                    message=errmsg))
            dev.api.execute(['sudo reboot'])
            time.sleep(60)

            # Boot into ONIE rescue mode
            self.wait_for_onie_rescue(countdown=300, poll_delay=10, user='root')

            # Download and verify OS
            self.onie_install(dev, image_name)

            # Wait for onie-rescue shell to terminate
            time.sleep(60)

            # Wait for actual install to occur. This takes up to 30 min.
            self.wait_for_device(countdown=1800, poll_delay=30)

    def ensure_os_version(self, dev):
        os_install = self.get_required_os(dev)

        if not os_install['image']:
            self.log.info('no software install required')
            return dev

        self.log.info('software image install required: %s' % os_install['image'])
        self.install_os(dev, image_name=os_install['image'])

        self.log.info('software install OK')

        os_semver = semver.parse_version_info(dev.facts['os_version'])
        if os_semver.major < 3:
            self.log.info('rebooting device ... please be patient')

            self.post_device_status(
                dev, state='OS-REBOOTING',
                message='OS install completed, now rebooting ... please be patient')

            dev.api.execute(['sudo reboot'])
            time.sleep(self.cli_args.init_delay)
            return self.wait_for_device(countdown=self.cli_args.reload_delay, poll_delay=10)


# ##### -----------------------------------------------------------------------
# #####
# #####                           !!! MAIN !!!
# #####
# ##### -----------------------------------------------------------------------

def main():
    cli_args = cli_parse()
    self_server = cli_args.server
    cboot = CumulusBootstrap(self_server, cli_args)
    if not os.path.isdir(cli_args.topdir):
        cboot.exit_results(dict(
            ok=False,
            error_type='args',
            message='{} is not a directory'.format(cli_args.topdir)))

    cboot.log.info("bootstrap init-delay: {} seconds"
                  .format(cli_args.init_delay))

    cboot.post_device_status(
        target=cli_args.target,
        state='START',
        message='bootstrap started, waiting for device access')

    time.sleep(cli_args.init_delay)
    dev = cboot.wait_for_device(countdown=cli_args.reload_delay, poll_delay=10, msg='Waiting for device access')

    cboot.log.info("proceeding with bootstrap")

    if dev.facts['virtual']:
        cboot.log.info('Virtual device. No OS upgrade necessary.')
    else:
        cboot.ensure_os_version(dev)
    cboot.log.info("bootstrap process finished")
    cboot.exit_results(dict(ok=True), dev=dev)


if '__main__' == __name__:
    main()
