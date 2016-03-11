# Copyright 2014-2016 F5 Networks Inc.
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

from oslo_log import log as logging

from f5_openstack_agent.lbaasv2.drivers.bigip.resource_helper import \
    BigIPResourceHelper
from f5_openstack_agent.lbaasv2.drivers.bigip.resource_helper import \
    ResourceType

LOG = logging.getLogger(__name__)


class PoolServiceBuilder(object):
    """Create LBaaS v2 pools and related objects on BIG-IPs.

    Handles requests to create, update, delete LBaaS v2 pools,
    health monitors, and members on one or more BIG-IP systems.
    """

    def __init__(self, service_adapter):
        self.service_adapter = service_adapter
        self.http_mon_helper = BigIPResourceHelper(ResourceType.http_monitor)
        self.https_mon_helper = BigIPResourceHelper(ResourceType.https_monitor)
        self.tcp_mon_helper = BigIPResourceHelper(ResourceType.tcp_monitor)
        self.pool_helper = BigIPResourceHelper(ResourceType.pool)

    def create_pool(self, service, bigips):
        """Create a pool on set of BIG-IPs.

        Creates a BIG-IP pool to represent an LBaaS pool object.

        :param service: Dictionary which contains a both a pool
        and load balancer definition.
        :param bigips: Array of BigIP class instances to create Listener.
        """
        pool = self.service_adapter.get_pool(service)
        for bigip in bigips:
            self.pool_helper.create(bigip, pool)

    def delete_pool(self, service, bigips):
        """Delete a pool on set of BIG-IPs.

        Deletes a BIG-IP pool defined by LBaaS pool object.

        :param service: Dictionary which contains a both a pool
        and load balancer definition.
        :param bigips: Array of BigIP class instances to delete pool.
        """
        pool = self.service_adapter.get_pool(service)

        for bigip in bigips:
            # TODO(jl) handle deleting members, monitors
            """
            p = self.pool_helper.load(bigip,
                                      name=pool["name"],
                                      partition=pool["partition"])

            # delete members
            if p.members:
                for member in p.members:
                    member.delete()

            # delete health monitors
            if p.monitor:
                pass
            """
            self.pool_helper.delete(bigip,
                                    name=pool["name"],
                                    partition=pool["partition"])

    def update_pool(self, service, bigips):
        """Update BIG-IP pool.

        :param service: Dictionary which contains a both a pool
        and load balancer definition.
        :param bigip: Array of BigIP class instances to create Listener.
        """
        pool = self.service_adapter.get_pool(service)
        for bigip in bigips:
            self.pool_helper.update(bigip, pool)

    def create_healthmonitor(self, service, bigips):
        # create member
        hm = self.service_adapter.get_healthmonitor(service)
        hm_helper = self._get_monitor_helper(service)

        for bigip in bigips:
            hm_helper.create(bigip, hm)

        # update pool with new health monitor
        pool = self.service_adapter.get_pool(service)
        for bigip in bigips:
            self.pool_helper.update(bigip, pool)

    def delete_healthmonitor(self, service, bigips):
        # delete health monitor
        hm = self.service_adapter.get_healthmonitor(service)
        hm_helper = self._get_monitor_helper(service)

        # update pool
        pool = self.service_adapter.get_pool(service)
        pool["monitor"] = ""

        for bigip in bigips:
            hm_helper.delete(bigip,
                             name=hm["name"],
                             partition=hm["partition"])
            self.pool_helper.update(bigip, pool)

    def update_healthmonitor(self, service, bigips):
        hm = self.service_adapter.get_healthmonitor(service)
        hm_helper = self._get_monitor_helper(service)
        for bigip in bigips:
            hm_helper.delete(bigip,
                             name=hm["name"],
                             partition=hm["partition"])

    # Note: can't use BigIPResourceHelper class because members
    # are created within pool objects. Following member methods
    # use the F5 SDK directly.
    def create_member(self, service, bigips):
        pool = self.service_adapter.get_pool(service)
        member = self.service_adapter.get_member(service)
        for bigip in bigips:
            part = pool["partition"]
            p = self.pool_helper.load(bigip,
                                      name=pool["name"],
                                      partition=part)
            m = p.members_s.members
            # TODO(jl) update if exists?
            m.create(**member)

    def delete_member(self, service, bigips):
        pool = self.service_adapter.get_pool(service)
        member = self.service_adapter.get_member(service)
        for bigip in bigips:
            part = pool["partition"]
            p = self.pool_helper.load(bigip,
                                      name=pool["name"],
                                      partition=part)
            m = p.members_s.members
            if m.exists(name=member["name"], partition=part):
                m = m.load(name=member["name"], partition=part)
                m.delete()

    def update_member(self, service, bigips):
        pool = self.service_adapter.get_pool(service)
        member = self.service_adapter.get_member(service)
        for bigip in bigips:
            part = pool["partition"]
            p = self.pool_helper.load(bigip,
                                      name=pool["name"],
                                      partition=part)
            m = p.members_s.members

            # TODO(jl) handle state -- SDK enforces at least state=None
            if m.exists(name=member["name"], partition=part):
                m = m.load(name=member["name"], partition=part)
                m.update(**member)

    def _get_monitor_helper(self, service):
        monitor_type = self.service_adapter.get_monitor_type(service)
        if monitor_type == "HTTPS":
            hm = self.https_mon_helper
        elif monitor_type == "TCP":
            hm = self.tcp_mon_helper
        else:
            hm = self.http_mon_helper
        return hm