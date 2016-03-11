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

import hashlib

from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class UnsupportedProtocolException(Exception):
    pass


class ServiceModelAdapter(object):
    """Class to translate LBaaS service objects to BIG-IP model objects.

    Creates BIG-IP model objects (dictionary of resource attributes) given
    an LBaaS service objet.
    """

    def __init__(self, conf):
        """Initialize the service model adapter with config."""
        self.conf = conf

    def get_pool(self, service):
        pool = service["pool"]
        loadbalancer = service["loadbalancer"]
        healthmonitor = None
        if "healthmonitor" in service:
            healthmonitor = service["healthmonitor"]

        return self._map_pool(loadbalancer, pool, healthmonitor)

    def get_pool_name(self, service):
        pool = service["pool"]
        loadbalancer = service["loadbalancer"]

        return {"name": pool["name"],
                "partition": self.get_folder_name(loadbalancer['tenant_id'])}

    def get_virtual(self, service):
        listener = service["listener"]
        loadbalancer = service["loadbalancer"]
        vip = self._map_virtual(loadbalancer, listener)
        self._add_bigip_items(listener, vip)
        return vip

    def get_virtual_name(self, service):
        listener = service["listener"]
        loadbalancer = service["loadbalancer"]

        return {"name": listener["name"],
                "partition": self.get_folder_name(loadbalancer['tenant_id'])}

    def get_traffic_group(self, service):
        tg = None
        loadbalancer = service["loadbalancer"]
        if "traffic_group" in loadbalancer:
            listener = service["listener"]
            tg = {"name": listener["name"],
                  "partition": self.get_folder_name(loadbalancer['tenant_id']),
                  "traffic_group": loadbalancer["traffic_group"]}

        return tg

    def get_member(self, service):
        loadbalancer = service["loadbalancer"]
        member = service["member"]
        return self._map_member(loadbalancer, member)

    def get_healthmonitor(self, service):
        healthmonitor = service["healthmonitor"]
        loadbalancer = service["loadbalancer"]
        return self._map_healthmonitor(loadbalancer,
                                       healthmonitor)

    def get_folder(self, service):

        loadbalancer = service["loadbalancer"]
        folder = None

        if "tenant_id" in loadbalancer:
            tenant_id = loadbalancer["tenant_id"]
            folder_name = self.get_folder_name(tenant_id)
            folder = {"name": folder_name,
                      "subPath": "/",
                      "fullPath": "/" + folder_name,
                      "hidden": False,
                      "inheritedDevicegroup": True}
            if "traffic_group" in loadbalancer:
                folder['trafficGroup'] = loadbalancer["traffic_gropu"]
                folder['inheritedTrafficGroup'] = False
            else:
                folder['inheritedTrafficGroup'] = True

        return folder

    def get_folder_name(self, tenant_id):
        if tenant_id is not None:
            name = self.conf.environment_prefix + tenant_id.replace('/', '')
        else:
            name = "Common"

        return name

    def tenant_to_traffic_group(self, tenant_id, traffic_groups):
        # Hash tenant id to index of traffic group
        hexhash = hashlib.md5(tenant_id).hexdigest()
        tg_index = int(hexhash, 16) % len(traffic_groups)
        return traffic_groups[tg_index]

    def _map_healthmonitor(self, loadbalancer, lbaas_healthmonitor):
        healthmonitor = {}

        # always expect these two
        healthmonitor["name"] = "hm_" + lbaas_healthmonitor["id"]
        healthmonitor["partition"] = \
            self.get_folder_name(loadbalancer['tenant_id'])

        # type
        if "type" in lbaas_healthmonitor:
            # healthmonitor["type"] = lbaas_healthmonitor["type"].lower()
            if (lbaas_healthmonitor["type"] == "HTTP" or
                    lbaas_healthmonitor["type"] == "HTTPS"):

                # url path
                if "url_path" in lbaas_healthmonitor:
                    healthmonitor["send"] = ("GET " +
                                             lbaas_healthmonitor["url_path"] +
                                             " HTTP/1.0\\r\\n\\r\\n")
                else:
                    healthmonitor["send"] = "GET / HTTP/1.0\\r\\n\\r\\n"

                # expected codes
                healthmonitor["recv"] = self._get_recv_text(
                    lbaas_healthmonitor)

        # interval - delay
        if "delay" in lbaas_healthmonitor:
            healthmonitor["interval"] = lbaas_healthmonitor["delay"]

        # timeout
        if "timeout" in lbaas_healthmonitor:
            if "max_retries" in lbaas_healthmonitor:
                timeout = (int(lbaas_healthmonitor["max_retries"]) *
                           int(lbaas_healthmonitor["timeout"]))
                healthmonitor["timeout"] = timeout

        return healthmonitor

    def _get_recv_text(self, lbaas_healthmonitor):
        if "expected_codes" in lbaas_healthmonitor:
            try:
                if lbaas_healthmonitor['expected_codes'].find(",") > 0:
                    status_codes = (
                        lbaas_healthmonitor['expected_codes'].split(','))
                    recv_text = "HTTP/1.(0|1) ("
                    for status in status_codes:
                        int(status)
                        recv_text += status + "|"
                    recv_text = recv_text[:-1]
                    recv_text += ")"
                elif lbaas_healthmonitor['expected_codes'].find("-") > 0:
                    status_range = (
                        lbaas_healthmonitor['expected_codes'].split('-'))
                    start_range = status_range[0]
                    int(start_range)
                    stop_range = status_range[1]
                    int(stop_range)
                    recv_text = (
                        "HTTP/1.(0|1) [" +
                        start_range + "-" +
                        stop_range + "]"
                    )
                else:
                    int(lbaas_healthmonitor['expected_codes'])
                    recv_text = "HTTP/1.(0|1) " +\
                        lbaas_healthmonitor['expected_codes']
            except Exception as exc:
                LOG.error(
                    "invalid monitor: %s, expected_codes %s, setting to 200"
                    % (exc, lbaas_healthmonitor['expected_codes']))
                recv_text = "HTTP/1.(0|1) 200"
        else:
            recv_text = "HTTP/1.(0|1) 200"

        return recv_text

    def get_monitor_type(self, service):
        monitor_type = None
        lbaas_healthmonitor = service["healthmonitor"]
        if "type" in lbaas_healthmonitor:
            monitor_type = lbaas_healthmonitor["type"]
        return monitor_type

    def _map_pool(self, loadbalancer, lbaas_pool, lbaas_hm):
        pool = dict()

        # always expect these two
        pool["name"] = lbaas_pool["name"]

        pool["partition"] = self.get_folder_name(loadbalancer["tenant_id"])

        if "description" in lbaas_pool:
            pool["description"] = lbaas_pool["description"]

        if "lb_algorithm" in lbaas_pool:
            pool["loadBalancingMode"] = self._get_lb_method(
                lbaas_pool["lb_algorithm"])

        if lbaas_hm is not None:
            pool["monitor"] = "hm_" + lbaas_hm["id"]

        return pool

    def _get_lb_method(self, method):
        lb_method = method.upper()

        if lb_method == 'LEAST_CONNECTIONS':
            return 'least-connections-member'
        elif lb_method == 'RATIO_LEAST_CONNECTIONS':
            return 'ratio-least-connections-member'
        elif lb_method == 'SOURCE_IP':
            return 'least-connections-node'
        elif lb_method == 'OBSERVED_MEMBER':
            return 'observed-member'
        elif lb_method == 'PREDICTIVE_MEMBER':
            return 'predictive-member'
        elif lb_method == 'RATIO':
            return 'ratio-member'
        else:
            return 'round-robin'

    def _map_virtual(self, loadbalancer, listener):
        vip = {}
        # always expect these two
        vip["name"] = listener["name"]
        vip["partition"] = self.get_folder_name(loadbalancer["tenant_id"])

        # TODO(jl) future work to handle TERMINATED_HTTPS, SNI containers

        if "description" in listener:
            vip["description"] = listener["description"]

        if "protocol" in listener:
            if not (listener["protocol"] == "HTTP" or
               listener["protocol"] == "HTTPS" or
               listener["protocol"] == "TCP"):
                # msg = "Unsupported protocol:  %s" % listener["protocol"]
                # raise UnsupportedProtocolException(msg)
                pass

            vip["ipProtocol"] = "tcp"

        if "connection_limit" in listener:
            vip["connectionLimit"] = listener["connection_limit"]
            if vip["connectionLimit"] < 0:
                vip["connectionLimit"] = 0

        if "protocol_port" in listener:
            port = listener["protocol_port"]
            if "vip_address" in loadbalancer:
                ip_address = loadbalancer["vip_address"]
                if str(ip_address).endswith('%0'):
                    ip_address = ip_address[:-2]

                if ':' in ip_address:
                    vip['destination'] = ip_address + "." + str(port)
                else:
                    vip['destination'] = ip_address + ":" + str(port)

        if "admin_state_up" in listener:
            if listener["admin_state_up"]:
                vip["enabled"] = True
            else:
                vip["disabled"] = True

        if "sni_container_refs" in listener:
            pass

        if "default_tls_container_ref" in listener:
            pass

        return vip

    def _add_bigip_items(self, listener, vip):
        # following are needed to complete a create()

        virtual_type = 'fastl4'
        if 'protocol' in listener:
            if (listener['protocol'] == 'HTTP' or
               listener['protocol'] == 'HTTPS'):
                virtual_type = 'standard'

        if 'session_persistence' in listener:
            if listener['session_persistence'] == 'APP_COOKIE':
                virtual_type = 'standard'

        if virtual_type == 'fastl4':
            vip['profiles'] = ['/Common/fastL4']

        # mask
        if "ip_address" in vip:
            ip_address = vip["ip_address"]
            if '.' in ip_address:
                vip["mask"] = '255.255.255.255'

        # vlan_name
        if "network_name" in listener:
            vip["vlan_name"] = listener["network_name"]
            if "snat_pool_name" in listener:
                vip["snat_pool_name"] = listener["snat_pool_name"]

        # snat
        if "use_snat" in listener and listener["use_snat"]:
            vip['sourceAddressTranslation'] = {}
            if "snat_pool_name" in vip:
                vip['sourceAddressTranslation']['type'] = 'snat'
                vip['sourceAddressTranslation']['pool'] = vip["snat_pool_name"]
            else:
                vip['sourceAddressTranslation']['type'] = 'automap'

    def _map_member(self, loadbalancer, lbaas_member):
        member = {}
        port = lbaas_member["protocol_port"]
        ip_address = lbaas_member["address"]
        if ':' in ip_address:
            member['name'] = ip_address + '.' + str(port)
        else:
            member['name'] = ip_address + ':' + str(port)
        member["partition"] = self.get_folder_name(loadbalancer["tenant_id"])
        member["address"] = ip_address
        return member