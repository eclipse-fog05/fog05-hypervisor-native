# Copyright (c) 2014,2020 ADLINK Technology Inc.
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License 2.0 which is available at
# http://www.eclipse.org/legal/epl-2.0, or the Apache License, Version 2.0
# which is available at https://www.apache.org/licenses/LICENSE-2.0.
#
# SPDX-License-Identifier: EPL-2.0 OR Apache-2.0
#
# Contributors: Gabriele Baldoni, ADLINK Technology Inc. - Base plugins set


import sys
import os
import uuid
import psutil
import json
import time
import signal
import traceback
import random
from fog05_sdk.interfaces.States import State
from fog05_sdk.interfaces.RuntimePluginFDU import *
from fog05_sdk import Yaks_Connector
from NativeFDU import NativeFDU
from jinja2 import Environment
from fog05_sdk.DLogger import DLogger
from mvar import MVar
from subprocess import PIPE
from functools import partial


class Native(RuntimePluginFDU):

    def __init__(self, name, version, plugin_uuid, manifest):
        super(Native, self).__init__(name, version, plugin_uuid, manifest)
        self.pid = os.getpid()
        self.var = MVar()

        self.wait_dependencies()

        osinfo = self.connector.loc.actual.get_node_os_info(self.node)
        self.operating_system = osinfo.get('name')

        self.logger.info(
            '__init__()', ' Hello from Native Plugin - Running on {}'.format(self.operating_system))
        file_dir = os.path.dirname(__file__)
        self.DIR = os.path.abspath(file_dir)

        self.agent_conf = self.connector.loc.actual.get_node_configuration(self.node)
        self.BASE_DIR = self.agent_conf.get('agent').get('path')
        self.LOG_DIR = 'logs'
        self.STORE_DIR = 'apps'
        self.configuration = manifest.get('configuration',{})
        signal.signal(signal.SIGINT, self.__catch_signal)
        signal.signal(signal.SIGTERM, self.__catch_signal)


    def __catch_signal(self, signal, _):
        if signal in [2,15]:
            self.var.put(signal)

    def start_runtime(self):

        if self.os.dir_exists(self.BASE_DIR):
            self.logger.info('start_runtime()', ' Native Plugin - Dir exists!')
            if not self.os.dir_exists(os.path.join(self.BASE_DIR, self.STORE_DIR)):
                self.os.create_dir(os.path.join(self.BASE_DIR, self.STORE_DIR))
            if not self.os.dir_exists(os.path.join(self.BASE_DIR, self.LOG_DIR)):
                self.os.create_dir(os.path.join(self.BASE_DIR, self.LOG_DIR))
        else:
            self.logger.info('start_runtime()', 'Native Plugin - Dir not exists!')
            self.os.create_dir(os.path.join(self.BASE_DIR))
            self.os.create_dir(os.path.join(self.BASE_DIR, self.STORE_DIR))
            self.os.create_dir(os.path.join(self.BASE_DIR, self.LOG_DIR))


        self.connector.loc.desired.observe_node_runtime_fdus(self.node, self.uuid, self.__fdu_observer)


        self.manifest.update({'pid': self.pid})
        self.manifest.update({'status': 'running'})
        self.connector.loc.actual.add_node_plugin(self.node, self.uuid, self.manifest)

        self.logger.info('start_runtime()', ' Native Plugin - Started...')

        r = self.var.get()
        self.stop_runtime()
        self.connector.close()
        exit(0)

    def stop_runtime(self):
        self.logger.info('stopRuntime()', ' Native Plugin - Destroy running BE')
        for k in list(self.current_fdus.keys()):
            fdu = self.current_fdus.get(k)
            try:
                self.__force_fdu_termination(k)
                if fdu.get_status() == State.DEFINED:
                    self.undefine_fdu(k)
            except Exception as e:
                self.logger.error('stop_runtime()', 'Error {}, continuing'.format(e))
                pass
        self.logger.info('stopRuntime()', '[ DONE ] Native Plugin - Bye')
        return True

    def define_fdu(self, fdu_record):

        fdu = NativeFDU(fdu_record)
        fdu_uuid = fdu.get_fdu_id()
        instance_id = fdu.get_uuid()

        if instance_id in self.current_fdus:
            self.logger.error('define_fdu()', '[ ERRO ] Native Plugin - Instance with ID {} already defined!!'.format(instance_id))
            self.write_fdu_error(fdu_uuid, instance_id, 0, 'Instance with this ID {} already exists!'.format(instance_id))


        out_file = 'native_{}.log'.format(instance_id)
        self.logger.info('define_fdu()', ' Native Plugin - Define BE FDU')
        self.logger.info('define_fdu()', ' Native Plugin - FDU is {}'.format(fdu))

        if fdu.image is not None:
            zip_name = fdu.get_image_uri().split('/')[-1]
            zip_file = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, zip_name)
            dest = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid)
            # entity.source = os.path.join(dest,entity.command)

            # if self.operating_system.lower() == 'linux':
            #     if zip_name.endswith('.tar.gz'):
            #         unzip_cmd = 'tar -zxvf {} -C {}'.format(zip_file, dest)
            #     else:
            #         unzip_cmd = 'unzip {} -d {}'.format(zip_file, dest)
            # elif self.operating_system.lower() == 'windows':
            #     unzip_cmd = 'Expand-Archive -Path {} -DestinationPath {}'.format(zip_file, dest)
            # else:
            #     unzip_cmd = ''

            self.os.create_dir(os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid))

            if fdu.get_image_uri().startswith('http'):
                self.os.download_file(fdu.get_image_uri(), os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, zip_name))
            elif fdu.get_image_uri().startswith('file://'):
                cmd = 'cp {} {}'.format(fdu.get_image_uri()[len('file://'):], os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, zip_name))
                self.os.execute_command(cmd, blocking=True, external=False)

            fdu.source = dest
        else:
            fdu.source = None

        fdu.set_status(State.DEFINED)
        self.current_fdus.update({instance_id: fdu})
        self.update_fdu_status(fdu_uuid, instance_id, 'DEFINE')
        self.logger.info('define_fdu()', ' Native Plugin - Defined BE FDU uuid {}'.format(instance_id))

    def undefine_fdu(self, instance_uuid):
        self.logger.info('undefine_fdu()', ' Native Plugin - Undefine BE FDU uuid {}'.format(instance_uuid))
        fdu = self.current_fdus.get(instance_uuid, None)
        if fdu is None:
            self.logger.error('undefine_fdu()', 'Native Plugin - FDU not exists')
            raise FDUNotExistingException('FDU not existing',
                                             'FDU {} not in runtime {}'.format(instance_uuid, self.uuid))
        elif fdu.get_status() != State.DEFINED:
            self.logger.error('undefine_fdu()', 'Native Plugin - FDU state is wrong, or transition not allowed')
            raise StateTransitionNotAllowedException('FDU is not in DEFINED state',
                                                     'FDU {} is not in DEFINED state'.format(instance_uuid))
        else:
            fdu_uuid = fdu.get_fdu_id()
            if self.get_local_instances(fdu_uuid) == 1:
                self.os.remove_dir(os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid))

            self.current_fdus.pop(instance_uuid, None)
            self.connector.loc.actual.remove_node_fdu(self.node, self.uuid, fdu_uuid, instance_uuid)
            self.logger.info('undefine_fdu()', '[ DONE ] Native Plugin - Undefine BE FDU uuid {}'.format(instance_uuid))

    def configure_fdu(self, instance_uuid):

        self.logger.info('configure_fdu()', ' Native Plugin - Configure BE FDU uuid {}'.format(instance_uuid))
        fdu = self.current_fdus.get(instance_uuid, None)
        if fdu is None:
            self.logger.error('configure_fdu()', 'Native Plugin - FDU not exists')
            raise FDUNotExistingException('FDU not existing',
                                             'FDU {} not in runtime {}'.format(instance_uuid, self.uuid))
        elif fdu.get_status() != State.DEFINED:
            self.logger.error('configure_fdu()', 'FDU Plugin - Entity state is wrong, or transition not allowed')
            raise StateTransitionNotAllowedException('FDU is not in DEFINED state',
                                                     'FDU {} is not in DEFINED state'.format(instance_uuid))
        else:
            fdu_uuid = fdu.get_fdu_id()
            out_file = 'native_{}.log'.format(instance_uuid)
            out_file = os.path.join(self.BASE_DIR, self.LOG_DIR, out_file)
            fdu.outfile = out_file
            native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
            self.os.create_dir(native_dir)
            self.os.create_file(fdu.outfile)

            if fdu.source is not None:
                zip_name = fdu.get_image_uri().split('/')[-1]
                zip_file = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, zip_name)
                if self.operating_system.lower() == 'linux':
                    if zip_name.endswith('.tar.gz'):
                        unzip_cmd = 'tar -zxvf {} -C {}'.format(zip_file, native_dir)
                    else:
                        unzip_cmd = 'unzip {} -d {}'.format(zip_file, native_dir)
                elif self.operating_system.lower() == 'windows':
                    unzip_cmd = 'Expand-Archive -Path {} -DestinationPath {}'.format(zip_file, native_dir)
                else:
                    unzip_cmd = ''
                self.os.execute_command(unzip_cmd, blocking=True, external=True)


            for cp in fdu.get_connection_points():
                    cp_record = self.nm.create_connection_point(cp)
                    if cp_record.get('vld_ref') is not None:
                        vld = cp_record.get('vld_ref')
                        self.nm.connect_cp_to_vnetwork(cp_record.get('uuid'), vld)
                    fdu.instance_cps.append(cp_record)

            netns = self.nm.create_network_namespace()
            fdu.namespace = netns


            for intf in fdu.get_interfaces():
                intf_name = intf.get('vintf_name')
                self.logger.info('configure_fdu()','Interface Info {}'.format(intf))

                if intf.get('virtual_interface').get('intf_type').upper() in ['PHYSICAL','BRIDGED']:


                    real_intf_name = intf.get('phy_face', None)
                    if real_intf_name is None:
                        raise ValueError("phy_face cannot be none")
                    if self.os.get_intf_type(real_intf_name) in ['ethernet']:
                        self.logger.error('configure_fdu()', 'Native FDU Plugin - Creating macvlan interface')
                        mac = intf.get('mac_address', self.__generate_random_mac())
                        intf.update({'mac_address': mac})

                        macvlan_temp_name = self.nm.create_macvlan_interface(real_intf_name)
                        self.nm.move_interface_in_namespace(macvlan_temp_name, fdu.namespace)
                        self.nm.assign_mac_address_to_interface_in_namespace(macvlan_temp_name, fdu.namespace, mac)
                        self.nm.rename_virtual_interface_in_namespace(macvlan_temp_name, intf_name, fdu.namespace)
                        intf_info = self.nm.assign_address_to_interface_in_namespace(intf_name, fdu.namespace)

                        fdu.virtual_interfaces.append({'internal':intf_info.get('internal'), 'external':None})

                    elif self.os.get_intf_type(real_intf_name) in ['wireless']:
                        self.logger.error('configure_fdu()', 'Native FDU Plugin - Creating moving wireless interface to namespace')
                        intf_info = self.nm.move_interface_in_namespace(real_intf_name, fdu.namespace)
                        self.nm.rename_virtual_interface_in_namespace(real_intf_name, intf_name, fdu.namespace)
                        intf_info.update({"name":intf_name})
                        fdu.virtual_interfaces.append({'internal':intf_info, 'external':None})

                    else:
                        mac = intf.get('mac_address', self.__generate_random_mac())
                        intf.update({'mac_address': mac})
                        # create interface
                        intf_info = self.nm.create_virtual_interface_in_namespace(intf_name, fdu.namespace)
                        self.logger.info('configure_fdu()','Created interface {}'.format(intf_info))
                         # attaching external face to bridge
                        res = self.nm.attach_interface_to_bridge(intf_info.get('external').get('name'),real_intf_name)
                        self.logger.info('configure_fdu()','Attached to bridge interface {}'.format(res))
                        # assigning mac address
                        res = self.nm.assign_mac_address_to_interface_in_namespace(intf_name, fdu.namespace, mac)
                        self.logger.info('configure_fdu()','Assigned MAC to interface {}'.format(res))
                        # assign ip address
                        self.nm.assign_address_to_interface_in_namespace(intf_name, fdu.namespace)
                        self.logger.info('configure_fdu()','Assigned IP to interface {}'.format(res))

                        # adding to the list of interfaces
                        fdu.virtual_interfaces.append({'internal':intf_info.get('internal'), 'external':intf_info.get('external')})
                else:
                    self.logger.error('configure_fdu()', 'Native FDU Plugin creating interface attached to connection point')
                    mac = intf.get('mac_address', self.__generate_random_mac())
                    intf.update({'mac_address': mac})
                    intf_info = self.nm.create_virtual_interface_in_namespace(intf_name, fdu.namespace)
                    self.logger.info('configure_fdu()','Created interface {}'.format(intf_info))
                    res = self.nm.assign_mac_address_to_interface_in_namespace(intf_name, fdu.namespace, mac)

                    if intf.get('cp_id') is not None:
                        cp_id = intf.get('cp_id')
                        cp = [x for x in fdu.instance_cps if x.get('cp_id') == cp_id]
                        if len(cp) > 0:
                            cp = cp[0]
                            res = self.nm.attach_interface_to_bridge(intf_info.get('external').get('name'),cp.get('br_name'))
                            self.logger.info('configure_fdu()','Attached to bridge interface {}'.format(res))
                            self.nm.assign_address_to_interface_in_namespace(intf_name, fdu.namespace)
                            self.logger.info('configure_fdu()','Assigned IP to interface {}'.format(res))
                        else:
                            self.logger.error('configure_fdu','Native FDU Plugin unable to find connection point {} for interface {}'.format(cp_id, intf_name))
                    else:
                        self.logger.error('configure_fdu','Native FDU Plugin interface {} is not connected to anything'.format(intf_name))

                    fdu.virtual_interfaces.append({'internal':intf_info.get('internal'), 'external':intf_info.get('external')})




            fdu.on_configured('')

            self.logger.info('configure_fdu()', ' Native Plugin - FDU is {}'.format(fdu))

            self.logger.info('configure_fdu()', '[ INFO ] Native Plugin - Registreting blocking start/run/log/ls/file evals for {}'.format(instance_uuid))
            start_fun  = partial(self.start_fdu, instance_uuid)
            run_fun  = partial(self.run_blocking_fdu, instance_uuid)
            log_fun  = partial(self.get_log_fdu, instance_uuid)
            ls_fun  = partial(self.get_ls_fdu, instance_uuid)
            file_fun  = partial(self.get_file_fdu, instance_uuid)

            try:
                self.connector.loc.actual.add_plugin_fdu_start_eval(self.node, self.uuid, fdu_uuid, instance_uuid, start_fun)
                self.connector.loc.actual.add_plugin_fdu_run_eval(self.node, self.uuid, fdu_uuid, instance_uuid, run_fun)
                self.connector.loc.actual.add_plugin_fdu_log_eval(self.node, self.uuid, fdu_uuid, instance_uuid, log_fun)
                self.connector.loc.actual.add_plugin_fdu_ls_eval(self.node, self.uuid, fdu_uuid, instance_uuid, ls_fun)
                self.connector.loc.actual.add_plugin_fdu_file_eval(self.node, self.uuid, fdu_uuid, instance_uuid, file_fun)
            except Exception as e:
                self.logger.error('configure_fdu()', '[ ERRO ] Native Plugin - Error in registering start/run/log/ls/file function: {}'.format(e))
                traceback.print_exc()

            self.current_fdus.update({instance_uuid: fdu})
            self.update_fdu_status(fdu_uuid, instance_uuid, 'CONFIGURE')


            self.logger.info('configure_fdu()', '[ DONE ] Native Plugin - Configure BE FDU uuid {}'.format(instance_uuid))

    def clean_fdu(self, instance_uuid):
        self.logger.info('clean_fdu()', ' FDU Plugin - Clean BE uuid {}'.format(instance_uuid))
        fdu = self.current_fdus.get(instance_uuid, None)
        if fdu is None:
            self.logger.error('clean_fdu()', 'Native Plugin - FDU not exists')
            raise FDUNotExistingException('FDU not existing',
                                             'FDU {} not in runtime {}'.format(instance_uuid, self.uuid))
        elif fdu.get_status() != State.CONFIGURED:
            self.logger.error('clean_fdu()', 'Native Plugin - FDU state is wrong, or transition not allowed')
            raise StateTransitionNotAllowedException('FDU is not in CONFIGURED state',
                                                     'FDU {} is not in CONFIGURED state'.format(instance_uuid))
        else:
            fdu_uuid = fdu.get_fdu_id()
            self.os.remove_file(fdu.outfile)
            native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
            self.os.remove_dir(native_dir)

            for i in fdu.virtual_interfaces:
                if i.get('external') is not None:
                    self.nm.detach_interface_from_bridge(i.get('external').get('name'))
                self.nm.delete_virtual_interface_from_namespace(i.get('internal').get('name'), fdu.namespace)

            for cp in fdu.instance_cps:
                self.nm.remove_connection_point(cp.get('uuid'))

            self.nm.delete_network_namespace(fdu.namespace)

            fdu.on_clean()
            self.current_fdus.update({instance_uuid: fdu})
            self.update_fdu_status(fdu_uuid, instance_uuid, 'DEFINE')

            self.logger.info('configure_fdu()', '[ INFO ] Native Plugin - Unregistering blocking start/run/log/ls/file evals for {}'.format(instance_uuid))
            self.connector.loc.actual.remove_plugin_fdu_start_eval(self.node, self.uuid, fdu_uuid, instance_uuid)
            self.connector.loc.actual.remove_plugin_fdu_run_eval(self.node, self.uuid, fdu_uuid, instance_uuid)
            self.connector.loc.actual.remove_plugin_fdu_log_eval(self.node, self.uuid, fdu_uuid, instance_uuid)
            self.connector.loc.actual.remove_plugin_fdu_ls_eval(self.node, self.uuid, fdu_uuid, instance_uuid)
            self.connector.loc.actual.remove_plugin_fdu_file_eval(self.node, self.uuid, fdu_uuid, instance_uuid)

            self.logger.info('clean_fdu()', '[ DONE ] Native Plugin - Clean BE uuid {}'.format(instance_uuid))

    def start_fdu(self, instance_uuid, env):
        self.logger.info('start_fdu()', ' Native Plugin - Starting BE uuid {}'.format(instance_uuid))
        self.logger.info('start_fdu()', ' Native Plugin - Environment {}'.format(env))
        try:
            #  env is expected in format MYVAR=MYVALUE,MYVAR2=MYVALUE2,...
            #  converting to dictionary
            env = self.__parse_environment(env)

            fdu = self.current_fdus.get(instance_uuid, None)
            if fdu is None:
                self.logger.error('start_fdu()', 'Native Plugin - FDU not exists')
                return {'error': 'FDU not exists'}
            elif fdu.get_status() != State.CONFIGURED:
                self.logger.error('start_fdu()', 'Native Plugin - FDU state is wrong, or transition not allowed')
                return {'error': 'FDU is not in CONFIGURED state'}
            else:
                self.logger.info('start_fdu()', 'Native Plugin - FDU is {}'.format(fdu))
                fdu_uuid = fdu.get_fdu_id()
                if fdu.source is not None:
                    native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
                    source_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
                    pid_file = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, instance_uuid)
                    run_script = self.__generate_run_script(fdu.cmd, fdu.args, source_dir, pid_file, fdu.namespace)
                    if self.operating_system.lower() == 'linux':
                        self.os.store_file(run_script, native_dir, '{}_run.sh'.format(instance_uuid))
                        chmod_cmd = 'chmod +x {}'.format(os.path.join(native_dir, '{}_run.sh'.format(instance_uuid)))
                        self.os.execute_command(chmod_cmd, blocking=True, external=False)
                        cmd = '{}'.format(os.path.join(native_dir, '{}_run.sh'.format(instance_uuid)))
                    elif self.operating_system.lower() == 'windows':
                        self.os.store_file(run_script, native_dir, '{}_run.ps1'.format(instance_uuid))
                        cmd = '{}'.format(os.path.join(native_dir, '{}_run.ps1'.format(instance_uuid)))
                    else:
                        cmd = ''
                    process = self.__execute_command(cmd, fdu.outfile, env)
                    time.sleep(1)
                    pid_file = '{}.pid'.format(pid_file)
                    # pid_file = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, pid_file)
                    pid = int(self.os.read_file(pid_file))
                    fdu.on_start(pid, process)
                else:
                    # try to inject the pid file if script use {{pid_file}}
                    '''
                    This make possible to add on the launch file of you native application that fog05 can inject the pid output file
                    in this way is possible to fog05 to correct send signal to your application, in the case the {{pid_file}} is not defined the script
                    will not be modified
                    '''
                    if self.operating_system.lower() == 'linux':
                            native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
                            f_name = '{}_run.sh'.format(instance_uuid)
                            pid_file = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, instance_uuid)
                            template_xml = self.os.read_file(os.path.join(self.DIR, 'templates', 'run_native_unix2.sh'))
                            na_script = Environment().from_string(template_xml)
                            cmd = '{} {}'.format(fdu.cmd, ' '.join(fdu.args))
                            na_script = na_script.render(command=cmd, outfile=pid_file, path=native_dir, namespace=fdu.namespace)
                            self.logger.info('start_fdu()', '[ INFO ] Lenght of runscript is {}'.format(len(na_script)))
                            self.os.store_file(na_script, native_dir, f_name)
                            chmod_cmd = 'chmod +x {}'.format(os.path.join(native_dir, f_name))
                            self.os.execute_command(chmod_cmd, blocking=True, external=False)
                            cmd = '{}'.format(os.path.join(native_dir, f_name))

                    elif self.operating_system.lower() == 'windows':
                        native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
                        pid_file = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, instance_uuid)
                        run_script = self.__generate_run_script(fdu.cmd, fdu.args, None, pid_file, fdu.namespace)
                        self.logger.info('start_fdu()', '[ INFO ] PowerShell script is {}'.format(run_script))
                        self.os.store_file(run_script, native_dir, '{}_run.ps1'.format(instance_uuid))
                        cmd = '{}'.format(os.path.join(native_dir, '{}_run.ps1'.format(instance_uuid)))

                    self.logger.info('start_fdu()', 'Command is {}'.format(cmd))
                    process = self.__execute_command(cmd, fdu.outfile, env)
                    fdu.on_start(process.pid, process)

                self.current_fdus.update({instance_uuid: fdu})
                self.update_fdu_status(fdu_uuid, instance_uuid, 'RUN')
                self.logger.info('start_fdu()', '[ DONE ] Native Plugin - Running BE uuid {}'.format(instance_uuid))

                return {'result':instance_uuid}
        except Exception as e:
            self.logger.info('start_fdu()', '[ ERRO ] Native Plugin - Error: {}'.format(e))
            traceback.print_exc()
            return {'error':'{}'.format(e)}

    def run_blocking_fdu(self, instance_uuid, env):
        try:
            self.logger.info('run_blocking_fdu()', ' Native Plugin - Running BE uuid {}'.format(instance_uuid))
            self.logger.info('run_blocking_fdu()', ' Native Plugin - Environment {}'.format(env))

            #  env is expected in format MYVAR=MYVALUE,MYVAR2=MYVALUE2,...
            #  converting to dictionary
            env = self.__parse_environment(env)

            fdu = self.current_fdus.get(instance_uuid, None)
            if fdu is None:
                self.logger.error('run_blocking_fdu()', 'Native Plugin - FDU not exists')
                return {'error': 'FDU not exists'}
                # raise FDUNotExistingException('FDU not existing',
                #                                  'FDU {} not in runtime {}'.format(instance_uuid, self.uuid))
            elif fdu.get_status() != State.CONFIGURED:
                self.logger.error('run_blocking_fdu()', 'Native Plugin - FDU state is wrong, or transition not allowed')
                return {'error': 'FDU is not in CONFIGURED state'}
                # raise StateTransitionNotAllowedException('FDU is not in CONFIGURED state',
                #                                          'FDU {} is not in CONFIGURED state'.format(instance_uuid))
            else:
                self.logger.info('run_blocking_fdu()', 'Native Plugin - FDU is {}'.format(fdu))
                fdu_uuid = fdu.get_fdu_id()
                if fdu.source is not None:
                    native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
                    source_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
                    pid_file = '{}.pid'.format(os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, instance_uuid))
                    run_script = self.__generate_blocking_run_script(fdu.cmd, fdu.args, source_dir, fdu.namespace)
                    if self.operating_system.lower() == 'linux':
                        self.os.store_file(run_script, native_dir, '{}_run.sh'.format(instance_uuid))
                        chmod_cmd = 'chmod +x {}'.format(os.path.join(native_dir, '{}_run.sh'.format(instance_uuid)))
                        self.os.execute_command(chmod_cmd, blocking=True, external=False)
                        cmd = '{}'.format(os.path.join(native_dir, '{}_run.sh'.format(instance_uuid)))
                    elif self.operating_system.lower() == 'windows':
                        self.os.store_file(run_script, native_dir, '{}_run.ps1'.format(instance_uuid))
                        cmd = '{}'.format(os.path.join(native_dir, '{}_run.ps1'.format(instance_uuid)))
                    else:
                        cmd = ''
                    process = self.__execute_command_blocking(cmd, fdu.outfile, pid_file, env)
                    time.sleep(1)
                    # pid_file = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, pid_file)
                    pid = int(self.os.read_file(pid_file))
                    fdu.on_start(pid, process)
                else:
                    # try to inject the pid file if script use {{pid_file}}
                    '''
                    This make possible to add on the launch file of you native application that fog05 can inject the pid output file
                    in this way is possible to fog05 to correct send signal to your application, in the case the {{pid_file}} is not defined the script
                    will not be modified
                    '''
                    if self.operating_system.lower() == 'linux':
                            native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
                            f_name = '{}_run.sh'.format(instance_uuid)
                            pid_file = '{}.pid'.format(os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, instance_uuid))
                            template_xml = self.os.read_file(os.path.join(self.DIR, 'templates', 'blocking_run_native_unix2.sh'))
                            na_script = Environment().from_string(template_xml)
                            cmd = '{} {}'.format(fdu.cmd, ' '.join(fdu.args))
                            na_script = na_script.render(command=cmd, outfile=pid_file, path=native_dir, namespace=fdu.namespace)
                            self.logger.info('run_blocking_fdu()', '[ INFO ] Lenght of runscript is {}'.format(len(na_script)))
                            self.os.store_file(na_script, native_dir, f_name)
                            chmod_cmd = 'chmod +x {}'.format(os.path.join(native_dir, f_name))
                            self.os.execute_command(chmod_cmd, blocking=True, external=False)
                            cmd = '{}'.format(os.path.join(native_dir, f_name))

                    elif self.operating_system.lower() == 'windows':
                        native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
                        pid_file = '{}.pid'.format(os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, instance_uuid))
                        run_script = self.__generate_blocking_run_script(fdu.cmd, fdu.args, None, fdu.namespace)
                        self.logger.info('run_blocking_fdu()', '[ INFO ] PowerShell script is {}'.format(run_script))
                        self.os.store_file(run_script, native_dir, '{}_run.ps1'.format(instance_uuid))
                        cmd = '{}'.format(os.path.join(native_dir, '{}_run.ps1'.format(instance_uuid)))

                    self.logger.info('run_blocking_fdu()', 'Command is {}'.format(cmd))
                    process = self.__execute_command_blocking(cmd, fdu.outfile, pid_file, env)
                    fdu.on_start(process.pid, process)

                self.current_fdus.update({instance_uuid: fdu})
                self.update_fdu_status(fdu_uuid, instance_uuid, 'RUN')

                self.logger.info('run_blocking_fdu()', '[ DONE ] Native Plugin - Running BE uuid {} - PID: {}'.format(instance_uuid, process.pid))
                exit_code = process.wait()
                return_code = '{}'.format(exit_code)
                self.logger.info('run_blocking_fdu()', '[ DONE ] Native Plugin - Running BE uuid {} - exit code {}'.format(instance_uuid, return_code))

                fdu.on_stop()
                self.current_fdus.update({instance_uuid: fdu})
                self.update_fdu_status(fdu_uuid, instance_uuid, 'CONFIGURE')

                return {'result': return_code}

        except Exception as e:
            self.logger.info('run_blocking_fdu()', '[ ERRO ] Native Plugin - Error: {}'.format(e))
            traceback.print_exc()
            return {'error':'{}'.format(e)}


    def stop_fdu(self, instance_uuid):
        self.logger.info('stop_fdu()', ' Native Plugin - Stop BE uuid {}'.format(instance_uuid))
        fdu = self.current_fdus.get(instance_uuid, None)
        if fdu is None:
            self.logger.error('stop_fdu()', 'Native Plugin - FDU not exists')
            raise FDUNotExistingException('FDU not existing',
                                             'FDU {} not in runtime {}'.format(instance_uuid, self.uuid))
        elif fdu.get_status() != State.RUNNING:
            self.logger.error('stop_fdu()', 'Native Plugin - FDU state is wrong, or transition not allowed')
            raise StateTransitionNotAllowedException('FDU is not in RUNNING state',
                                                     'FDU {} is not in RUNNING state'.format(instance_uuid))
        else:
            fdu_uuid = fdu.get_fdu_id()
            if fdu.source is None:

                pid = fdu.pid
                self.logger.info('stop_fdu()', 'FDU source is none')
                self.logger.info('stop_fdu()', 'Native Plugin - PID {}'.format(pid))
                self.os.execute_command('sudo pkill -2 -P {}'.format(pid),blocking=True, external=False)
                # self.os.send_sig_int(pid)
                f_name = '{}.pid'.format(instance_uuid)
                f_path = os.path.join(self.BASE_DIR, self.STORE_DIR)
                pid_file = os.path.join(f_path, f_name)
                self.logger.info('stop_fdu()', 'Check if PID file exists {}'.format(pid_file))
                if self.os.file_exists(pid_file):
                    pid = int(self.os.read_file(pid_file))
                    self.logger.info('stop_fdu()', 'Native Plugin - PID {}'.format(pid))
                    self.os.execute_command('sudo pkill -2 -P {}'.format(pid),blocking=True, external=False)
                    if self.os.check_if_pid_exists(pid):
                        self.os.execute_command('sudo pkill -2 -P {}'.format(pid),blocking=True, external=False)
                        time.sleep(3)
                    if  self.os.check_if_pid_exists(pid):
                        self.os.execute_command('sudo pkill -9 -P {}'.format(pid),blocking=True, external=False)
                pid_file = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, '{}.pid'.format(instance_uuid))
                self.logger.info('stop_fdu()', 'Check if PID file exists {}'.format(pid_file))
                if self.os.file_exists(pid_file):
                    pid = int(self.os.read_file(pid_file))
                    self.logger.info('stop_fdu()', 'Native Plugin - PID {}'.format(pid))
                    self.os.execute_command('sudo pkill -2 -P {}'.format(pid), blocking=True, external=False)
                    if self.os.check_if_pid_exists(pid):
                        self.os.execute_command('sudo pkill -2 -P {}'.format(pid), blocking=True, external=False)
                        time.sleep(3)
                    if self.os.check_if_pid_exists(pid):
                        self.os.execute_command('sudo pkill -9 -P {}'.format(pid), blocking=True, external=False)
            else:

                self.logger.info('stop_fdu()', 'Instance source is not none')
                pid_file = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name, '{}.pid'.format(instance_uuid))
                pid = int(self.os.read_file(pid_file))
                if self.operating_system.lower == 'linux':
                    self.logger.info('stop_fdu()', 'Native Plugin - PID {}'.format(pid))
                    self.os.execute_command('sudo pkill -9 -P {}'.format(pid),blocking=True, external=False)
                if self.os.check_if_pid_exists(pid):
                    self.os.send_sig_int(pid)
                    time.sleep(3)
                if self.os.check_if_pid_exists(pid):
                    self.os.send_sig_kill(pid)
            fdu.on_stop()
            self.current_fdus.update({instance_uuid: fdu})
            self.update_fdu_status(fdu_uuid, instance_uuid, 'CONFIGURE')
            self.logger.info('stop_fdu()', '[ DONE ] Native Plugin - Stopped BE uuid {}'.format(instance_uuid))


    def pause_fdu(self, instance_uuid):
        fdu = self.current_fdus.get(instance_uuid, None)
        if fdu is None:
            self.logger.error('stop_fdu()', 'Native Plugin - FDU not exists')
            raise FDUNotExistingException('FDU not existing',
                                             'FDU {} not in runtime {}'.format(instance_uuid, self.uuid))
        else:
            fdu_uuid = fdu.get_fdu_id()
            self.logger.error('pause_fdu','Cannot pause native!!')
            self.write_fdu_error(fdu_uuid, instance_uuid, 7, 'Instance cannot be paused')

    def resume_fdu(self, instance_uuid):
        fdu = self.current_fdus.get(instance_uuid, None)
        if fdu is None:
            self.logger.error('stop_fdu()', 'Native Plugin - FDU not exists')
            raise FDUNotExistingException('FDU not existing',
                                             'FDU {} not in runtime {}'.format(instance_uuid, self.uuid))
        else:
            fdu_uuid = fdu.get_fdu_id()
            self.logger.error('resume_fdu','Cannot resume native!!')
            self.write_fdu_error(fdu_uuid, instance_uuid, 7, 'Instance cannot be resumed')

    def migrate_fdu(self, instance_uuid):
        record = self.connector.loc.desired.get_node_fdu(self.node, self.uuid, '*', instance_uuid)
        fdu_uuid = record.get('fdu_id')
        destination = record.get('migration_properties').get('destination')
        if destination != self.node:
            fdu = self.current_fdus.get(instance_uuid, None)
            if fdu is None:
                self.logger.error('stop_fdu()', 'Native Plugin - FDU not exists')
                raise FDUNotExistingException('FDU not existing',
                                                'FDU {} not in runtime {}'.format(instance_uuid, self.uuid))
            else:
                fdu_uuid = fdu.get_fdu_id()
                self.logger.error('pause_fdu','Cannot migrate native!!')
                self.write_fdu_error(fdu_uuid, instance_uuid, 7, 'Instance cannot be migrated')
        else:
            self.connector.loc.actual.remove_node_fdu(self.node, self.uuid, fdu_uuid, instance_uuid)

    def get_log_fdu(self, instance_uuid, unit):
        try:
            self.logger.info('get_log_fdu()', ' Native Plugin - Running BE uuid {}'.format(instance_uuid))
            fdu = self.current_fdus.get(instance_uuid, None)
            if fdu is None:
                self.logger.error('get_log_fdu()', 'Native Plugin - FDU not exists')
                return {'error': 'FDU not exists'}
            elif fdu.get_status() != State.CONFIGURED and fdu.get_status() != State.RUNNING:
                self.logger.error('get_log_fdu()', 'Native Plugin - FDU state is wrong, or transition not allowed')
                return {'error': 'FDU is not in correct state'}
            else:
                self.logger.info('get_log_fdu()', 'Native Plugin - FDU is {}'.format(fdu))
                fdu_uuid = fdu.get_fdu_id()
                out = open(fdu.outfile)
                data = out.read()
                out.close()
                return {'result': data}

        except Exception as e:
            self.logger.info('get_log_fdu()', '[ ERRO ] Native Plugin - Error: {}'.format(e))
            traceback.print_exc()
            return {'error':'{}'.format(e)}

    def get_ls_fdu(self, instance_uuid, unit):
        try:
            self.logger.info('get_ls_fdu()', ' Native Plugin - Running BE uuid {}'.format(instance_uuid))
            fdu = self.current_fdus.get(instance_uuid, None)
            if fdu is None:
                self.logger.error('get_ls_fdu()', 'Native Plugin - FDU not exists')
                return {'error': 'FDU not exists'}
            elif fdu.get_status() != State.CONFIGURED and fdu.get_status() != State.RUNNING:
                self.logger.error('get_log_fdu()', 'Native Plugin - FDU state is wrong, or transition not allowed')
                return {'error': 'FDU is not in correct state'}
            else:
                self.logger.info('get_ls_fdu()', 'Native Plugin - FDU is {}'.format(fdu))
                fdu_uuid = fdu.get_fdu_id()
                native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)

                res = json.dumps(os.listdir(native_dir))
                return {'result': res}

        except Exception as e:
            self.logger.info('get_ls_fdu()', '[ ERRO ] Native Plugin - Error: {}'.format(e))
            traceback.print_exc()
            return {'error':'{}'.format(e)}

    def get_file_fdu(self, instance_uuid, filename):
        try:
            self.logger.info('get_ls_fdu()', ' Native Plugin - Running BE uuid {}'.format(instance_uuid))
            fdu = self.current_fdus.get(instance_uuid, None)
            if fdu is None:
                self.logger.error('get_ls_fdu()', 'Native Plugin - FDU not exists')
                return {'error': 'FDU not exists'}
            elif fdu.get_status() != State.CONFIGURED and fdu.get_status() != State.RUNNING:
                self.logger.error('get_log_fdu()', 'Native Plugin - FDU state is wrong, or transition not allowed')
                return {'error': 'FDU is not in correct state'}
            else:
                self.logger.info('get_ls_fdu()', 'Native Plugin - FDU is {}'.format(fdu))
                fdu_uuid = fdu.get_fdu_id()
                native_dir = os.path.join(self.BASE_DIR, self.STORE_DIR, fdu_uuid, fdu.name)
                if os.path.exists(os.path.join(native_dir, filename)) and os.path.isfile(os.path.join(native_dir, filename)):
                    out = open(os.path.join(native_dir, filename))
                    data = out.read()
                    out.close()
                    return {'result': data}
                else:
                    return {'error':'file not exists or is directory'}

        except Exception as e:
            self.logger.info('get_ls_fdu()', '[ ERRO ] Native Plugin - Error: {}'.format(e))
            traceback.print_exc()
            return {'error':'{}'.format(e)}

    def __execute_command(self, command, out_file, env={}):
        f = open(out_file, 'w')
        if self.operating_system.lower() == 'windows':
            p = psutil.Popen(['PowerShell', '-File', command], shell=True, stdout=f, stderr=f)
        else:
            # cmd = 'sh -c {}'.format(command)
            cmd_splitted = command.split()
            self.logger.info('__execute_command()', 'CMD SPLIT = {}'.format(cmd_splitted))
            p = psutil.Popen(cmd_splitted, shell=False, stdout=f, stderr=f, stdin=PIPE, env=dict(os.environ,**env))
        self.logger.info('__execute_command()', 'PID = {}'.format(p.pid))
        return p

    def __execute_command_blocking(self, command, out_file, pidfile, env={}):
        f = open(out_file, 'w')
        f_pid = open(pidfile,'w+')
        if self.operating_system.lower() == 'windows':
            p = psutil.Popen(['PowerShell', '-File', command], shell=True, stdout=f, stderr=f, stdin=PIPE,env=dict(os.environ,**env))
        else:
            # cmd = 'sh -c {}'.format(command)
            cmd_splitted = command.split()
            self.logger.info('__execute_command_blocking()', 'CMD SPLIT = {}'.format(cmd_splitted))
            p = psutil.Popen(cmd_splitted, shell=False, stdout=f, stderr=f, stdin=PIPE,env=dict(os.environ,**env))
        self.logger.info('__execute_command_blocking()', 'PID = {}'.format(p.pid))

        f_pid.write('{}'.format(p.pid))
        f_pid.flush()
        f_pid.close()

        return p

    def __generate_blocking_run_script(self, cmd, args, directory, ns):
        if self.operating_system.lower() == 'windows':
            if len(args) == 0:
                self.logger.info('__generate_blocking_run_script()', ' Native Plugin - Generating run script for Windows')
                template_script = self.os.read_file(os.path.join(self.DIR, 'templates', 'run_native_windows.ps1'))
                na_script = Environment().from_string(template_script)
                if directory:
                    cmd = os.path.join(directory,cmd)
                na_script = na_script.render(command=cmd)
            else:
                args = json.dumps(args)[1:-1]
                template_script = self.os.read_file(os.path.join(self.DIR, 'templates', 'run_native_windows_args.ps1'))
                na_script = Environment().from_string(template_script)
                if directory:
                    cmd = os.path.join(directory, cmd)
                na_script = na_script.render(command=cmd,args_list=args)

        else:
            self.logger.info('__generate_blocking_run_script()', ' Native Plugin - Generating run script for Linux')
            if directory is None:
                template_script = self.os.read_file(os.path.join(self.DIR, 'templates', 'blocking_run_native_unix2.sh'))
            else:
                template_script = self.os.read_file(os.path.join(self.DIR, 'templates', 'blocking_run_native_unix.sh'))
            na_script = Environment().from_string(template_script)
            if directory:
                p = directory
            else:
                p = self.BASE_DIR
            if len(args)>0:
                cmd = cmd + ' {}'.format(' '.join(args))
            na_script = na_script.render(path=p,command=cmd, namespace=ns)
        return na_script

    def __generate_run_script(self, cmd, args, directory, outfile, ns):
        if self.operating_system.lower() == 'windows':
            if len(args) == 0:
                self.logger.info('__generate_run_script()', ' Native Plugin - Generating run script for Windows')
                template_script = self.os.read_file(os.path.join(self.DIR, 'templates', 'run_native_windows.ps1'))
                na_script = Environment().from_string(template_script)
                if directory:
                    cmd = os.path.join(directory,cmd)
                na_script = na_script.render(command=cmd, outfile=outfile)
            else:
                args = json.dumps(args)[1:-1]
                template_script = self.os.read_file(os.path.join(self.DIR, 'templates', 'run_native_windows_args.ps1'))
                na_script = Environment().from_string(template_script)
                if directory:
                    cmd = os.path.join(directory, cmd)
                na_script = na_script.render(command=cmd,args_list=args, outfile=outfile)

        else:
            self.logger.info('__generate_run_script()', ' Native Plugin - Generating run script for Linux')
            if directory is None:
                template_script = self.os.read_file(os.path.join(self.DIR, 'templates', 'run_native_unix2.sh'))
            else:
                template_script = self.os.read_file(os.path.join(self.DIR, 'templates', 'run_native_unix.sh'))
            na_script = Environment().from_string(template_script)
            if directory:
                p = directory
            else:
                p = self.BASE_DIR
            if len(args)>0:
                cmd = cmd + ' {}'.format(' '.join(args))
            na_script = na_script.render(path=p,command=cmd, outfile=outfile, namespace=ns)
        return na_script


    def __fdu_observer(self, fdu_info):
        self.logger.info('__fdu_observer()', ' Native Plugin - New Action of a FDU - FDU Info: {}'.format(fdu_info))
        action = fdu_info.get('status')
        fdu_uuid = fdu_info.get('uuid')
        react_func = self.__react(action)
        try:
            if action == 'UNDEFINE':
                self.logger.info('__fdu_observer()', ' Native Plugin - This is a remove for : {}'.format(fdu_info))
                self.undefine_fdu(fdu_uuid)
            elif action == 'DEFINE':
                self.logger.info('__fdu_observer()', ' Native Plugin - This is a define for : {}'.format(fdu_info))
                self.define_fdu(fdu_info)
            elif react_func is not None:
                react_func(fdu_uuid)
            else:
                self.logger.info('__fdu_observer()', ' Native Plugin - Action not recognized : {}'.format(action))
        except FDUNotExistingException as nex:
            self.logger.info('__fdu_observer()', ' Error: {}'.format(nex))
            traceback.print_exc()
            self.write_fdu_error(fdu_info.get('fdu_uuid'), fdu_uuid, 9, nex)
            time.sleep(10)
            self.connector.loc.actual.remove_node_fdu(self.node, self.uuid, fdu_info.get('fdu_uuid'), fdu_uuid)
            return
        except StateTransitionNotAllowedException as stna:
            self.logger.info('__fdu_observer()', ' Error: {}'.format(stna))
            traceback.print_exc()
            self.write_fdu_error(fdu_info.get('fdu_uuid'), fdu_uuid, 10, stna)
            time.sleep(5)
            fdu = self.current_fdus.get(fdu_uuid)
            self.update_fdu_status(fdu_info.get('fdu_uuid'), fdu_uuid,fdu.status)
            return
        except Exception as e:
            self.logger.info('__fdu_observer()', ' Error: {}'.format(e))
            traceback.print_exc()
            self.write_fdu_error(fdu_info.get('fdu_uuid'), fdu_uuid, 10, e)
            time.sleep(5)
            fdu = self.current_fdus.get(fdu_uuid)
            self.update_fdu_status(fdu_info.get('fdu_uuid'), fdu_uuid,fdu.status)
            return


    def __react(self, action):
        r = {
            'CONFIGURE': self.configure_fdu,
            'STOP': self.stop_fdu,
            'RESUME': self.resume_fdu,
            'CLEAN': self.clean_fdu,
            'LAND': self.migrate_fdu,
            'TAKE_OFF': self.migrate_fdu
        }
        return r.get(action, None)

    def __force_fdu_termination(self, fdu_uuid):
        self.logger.info('__force_fdu_termination()', ' Native Plugin - Stop a FDU uuid {} '.format(fdu_uuid))
        fdu = self.current_fdus.get(fdu_uuid, None)
        if fdu is None:
            self.logger.error('__force_fdu_termination()', 'Native Plugin - FDU not exists')
            raise FDUNotExistingException('Native not existing',
                                             'FDU {} not in runtime {}'.format(fdu_uuid, self.uuid))
        else:
            if fdu.get_status() == State.PAUSED:
                self.resume_fdu(fdu_uuid)
                self.stop_fdu(fdu_uuid)
                self.clean_fdu(fdu_uuid)
                self.undefine_fdu(fdu_uuid)
            if fdu.get_status() == State.RUNNING:
                self.stop_fdu(fdu_uuid)
                self.clean_fdu(fdu_uuid)
                self.undefine_fdu(fdu_uuid)
            if fdu.get_status() == State.CONFIGURED:
                self.clean_fdu(fdu_uuid)
                self.undefine_fdu(fdu_uuid)
            if fdu.get_status() == State.DEFINED:
                self.undefine_fdu(fdu_uuid)

    def __generate_random_mac(self):
        d = [ 0x00, 0x16,
            random.randint(0x00, 0x7f),
            random.randint(0x00, 0x7f),
            random.randint(0x00, 0xff),
            random.randint(0x00, 0xff) ]
        return ':'.join(map(lambda x: "%02x" % x, d))


    def __parse_environment(self, env):
        d_env = {}
        if env == "":
            return d_env
        env = env.split(',')
        for e in env:
            ev = e.split('=')
            k = ev[0]
            v = ev[1]
            d_env.update({k:v})
        return d_env
