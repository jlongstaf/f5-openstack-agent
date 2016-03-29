# Copyright 2015-2106 F5 Networks Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import json
import pytest

from f5.bigip import BigIP
from f5_openstack_agent.lbaasv2.drivers.bigip.lbaas_builder import \
    LBaaSBuilder
from f5_openstack_agent.lbaasv2.drivers.bigip.listener_service import \
    ListenerServiceBuilder
from f5_openstack_agent.lbaasv2.drivers.bigip.pool_service import \
    PoolServiceBuilder
from f5_openstack_agent.lbaasv2.drivers.bigip.service_adapter import \
    ServiceModelAdapter
from f5_openstack_agent.lbaasv2.drivers.bigip.system_helper import \
    SystemHelper


class Config(object):
    """Stand-in for agent .ini config file"""
    def __init__(self):
        self.f5_ha_type = "standalone"
        self.f5_sync_mode = "replication"
        self.f5_global_routed_mode = True
        self.f5_device_type = "external"
        self.icontrol_hostname = "10.190.5.7"
        self.icontrol_username = "admin"
        self.icontrol_password = "admin"
        self.environment_prefix = "Test"
        self.f5_snat_mode = False
        self.debug = True


def test_create_lbaas_service():
    system_helper = SystemHelper()
    service_adapter = ServiceModelAdapter(Config())
    pool_builder = PoolServiceBuilder(service_adapter)
    listener_builder = ListenerServiceBuilder(service_adapter)
    bigips = [BigIP('10.190.5.7', 'admin', 'admin')]
    service = json.load(open("service.json"))["service"]

    try:
        listeners = service["listeners"]
        loadbalancer = service["loadbalancer"]
        pools = service["pools"]
        tenant_id = loadbalancer["tenant_id"]

        # create tenant partition
        for bigip in bigips:
            folder_name = service_adapter.get_folder_name(tenant_id)
            if not system_helper.folder_exists(bigip, folder_name):
                folder = service_adapter.get_folder(service)
                system_helper.create_folder(bigip, folder)

        # create BIG-IP virtual servers
        for listener in listeners:
            # create a service object in form expected by builder
            svc = {"loadbalancer": loadbalancer,
                   "listener": listener}

            # create BIG-IP virtual server
            print("Create listener")
            listener_builder.create_listener(svc, bigips)

            # validate
            l = listener_builder.get_listener(svc, bigips[0])
            assert l.name == listener["name"]
            print("Created listener: %s" % l.name)

        # create pools
        for pool in pools:
            # create a service object in form expected by builder
            svc = {"loadbalancer": loadbalancer,
                   "pool": pool}

            print("add_listener_pool")
            LBaaSBuilder.add_listener_pool(service, svc)

            # create
            pool_builder.create_pool(svc, bigips)

            # assign pool name to virtual
            print("Updating listener pool")
            listener_builder.update_listener_pool(
                svc, pool["name"], bigips)
            l = listener_builder.get_listener(svc, bigips[0])
            assert l.pool.endswith(pool["name"])

            # update virtual sever pool name, session persistence
            print("Updating session persistence")
            listener_builder.update_session_persistence(svc, bigips)
            l = listener_builder.get_listener(svc, bigips[0])
            assert len(l.persist) == 1
            assert l.persist[0]['name'] == 'cookie'

        # delete pools
        for pool in pools:
            # create a service object in form expected by builder
            svc = {"loadbalancer": loadbalancer,
                   "pool": pool}

            # mimic lbaas_builder
            LBaaSBuilder.add_listener_pool(service, svc)

            # remove pool name from virtual
            print("Removing listener pool setting")
            l = listener_builder.update_listener_pool(svc, "", bigips)
            assert not hasattr(l, 'pool')

            # delete pool
            pool_builder.delete_pool(svc, bigips)

            # update virtual sever pool name, session persistence
            print("Removing session persistence")
            listener_builder.remove_session_persistence(svc, bigips)
            l = listener_builder.get_listener(svc, bigips[0])
            assert not hasattr(l, 'persist')

    except Exception as err:
        pytest.fail("Error: %s" % err.message)
