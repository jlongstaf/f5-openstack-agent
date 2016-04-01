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

import os

from f5_openstack_agent.lbaasv2.drivers.bigip.network_helper import \
    NetworkHelper
from f5_openstack_agent.lbaasv2.drivers.bigip.resource_helper import \
    BigIPResourceHelper
from f5_openstack_agent.lbaasv2.drivers.bigip.resource_helper import \
    ResourceType
from oslo_log import log as logging

LOG = logging.getLogger(__name__)


class BigipSnatManager(object):
    def __init__(self, driver, l2_service, l3_binding):
        self.driver = driver
        self.l2_service = l2_service
        self.l3_binding = l3_binding
        self.snat_manager = BigIPResourceHelper(ResourceType.snat)
        self.snatpool_manager = BigIPResourceHelper(ResourceType.snatpool)
        self.snat_translation_manager = BigIPResourceHelper(
            ResourceType.snat_translation)
        self.network_helper = NetworkHelper()

    def _get_snat_name(self, subnet, tenant_id):
        # Get the snat name based on HA type
        if self.driver.conf.f5_ha_type == 'standalone':
            return 'snat-traffic-group-local-only-' + subnet['id']
        elif self.driver.conf.f5_ha_type == 'pair':
            # REVISIT(RJB): should this name have a hyphen before subnetid
            return 'snat-traffic-group-1' + subnet['id']
        elif self.driver.conf.f5_ha_type == 'scalen':
            traffic_group = self.driver.tenant_to_traffic_group(tenant_id)
            base_traffic_group = os.path.basename(traffic_group)
            return 'snat-' + base_traffic_group + '-' + subnet['id']
        LOG.error('Invalid f5_ha_type:%s' % self.driver.conf.f5_ha_type)
        return ''

    def _get_snat_traffic_group(self, tenant_id):
        # Get the snat name based on HA type """
        if self.driver.conf.f5_ha_type == 'standalone':
            return 'traffic-group-local-only'
        elif self.driver.conf.f5_ha_type == 'pair':
            return 'traffic-group-1'
        elif self.driver.conf.f5_ha_type == 'scalen':
            traffic_group = self.driver.tenant_to_traffic_group(tenant_id)
            return os.path.basename(traffic_group)
        # If this is an error shouldn't we raise?
        LOG.error('Invalid f5_ha_type:%s' % self.driver.conf.f5_ha_type)
        return ''

    def get_snat_addrs(self, subnetinfo, tenant_id):
        # Get the ip addresses for snat """
        subnet = subnetinfo['subnet']
        snat_addrs = []

        snat_name = self._get_snat_name(subnet, tenant_id)
        for i in range(self.driver.conf.f5_snat_addresses_per_subnet):
            index_snat_name = snat_name + "_" + str(i)
            ports = self.driver.plugin_rpc.get_port_by_name(
                port_name=index_snat_name)
            if len(ports) > 0:
                first_port = ports[0]
                first_fixed_ip = first_port['fixed_ips'][0]
                ip_address = first_fixed_ip['ip_address']
            else:
                new_port = self.driver.plugin_rpc.create_port_on_subnet(
                    subnet_id=subnet['id'],
                    mac_address=None,
                    name=index_snat_name,
                    fixed_address_count=1)
                ip_address = new_port['fixed_ips'][0]['ip_address']
            snat_addrs.append(ip_address)
        return snat_addrs

    def assure_bigip_snats(self, bigip, subnetinfo, snat_addrs, tenant_id):
        # Ensure Snat Addresses are configured on a bigip.
        # Called for every bigip only in replication mode.
        # otherwise called once and synced.
        network = subnetinfo['network']

        snat_info = {}
        if self.l2_service.is_common_network(network):
            snat_info['network_folder'] = 'Common'
        else:
            snat_info['network_folder'] = tenant_id
        snat_info['pool_name'] = tenant_id
        # REVISIT(RJB): We need to change the folder to something env_tenant_id
        snat_info['pool_folder'] = tenant_id
        snat_info['addrs'] = snat_addrs

        self._assure_bigip_snats(bigip, subnetinfo, snat_info, tenant_id)

    def _assure_bigip_snats(self, bigip, subnetinfo, snat_info, tenant_id):
        # Configure the ip addresses for snat
        network = subnetinfo['network']
        subnet = subnetinfo['subnet']

        if tenant_id not in bigip.assured_tenant_snat_subnets:
            bigip.assured_tenant_snat_subnets[tenant_id] = []
        if subnet['id'] in bigip.assured_tenant_snat_subnets[tenant_id]:
            return

        snat_name = self._get_snat_name(subnet, tenant_id)
        for i in range(self.driver.conf.f5_snat_addresses_per_subnet):
            ip_address = snat_info['addrs'][i] + \
                '%' + str(network['route_domain_id'])
            index_snat_name = snat_name + "_" + str(i)
            if self.l2_service.is_common_network(network):
                index_snat_name = '/Common/' + index_snat_name

            snat_traffic_group = self._get_snat_traffic_group(tenant_id)
            # snat.create() did  the following in LBaaSv1
            # Creates the SNAT
            #   * if the traffic_group is empty it uses a const
            #     but this seems like it should be an error see message
            #     in this file about this
            # Create a SNAT Pool if a name was passed in
            #   * Add the snat to the list of members
            model = {
                "name": index_snat_name,
                "partition": snat_info['network_folder'],
                "address": ip_address,
                "trafficGroup": snat_traffic_group,

            }
            snat = self.snat_manager.create(bigip, model)

            model = {
                "name": snat_info['pool_name'],
                "partition": snat_info['pool_folder']
            }
            snatpool = self.snatpool_manager.create(bigip, model)
            snatpool.members.append(snat.fullPath)
            snatpool.update()

            if self.l3_binding:
                self.l3_binding.bind_address(subnet_id=subnet['id'],
                                             ip_address=ip_address)

        bigip.assured_tenant_snat_subnets[tenant_id].append(subnet['id'])

    def delete_bigip_snats(self, bigip, subnetinfo, tenant_id):
        # Assure shared snat configuration (which syncs) is deleted.
        #
        if not subnetinfo['network']:
            LOG.error('Attempted to delete selfip and snats '
                      'for missing network ... skipping.')
            return set()

        return self._delete_bigip_snats(bigip, subnetinfo, tenant_id)

    def _remove_assured_tenant_snat_subnet(self, bigip, tenant_id, subnet):
        # Remove ref for the subnet for this tenant"""
        if tenant_id in bigip.assured_tenant_snat_subnets:
            tenant_snat_subnets = \
                bigip.assured_tenant_snat_subnets[tenant_id]
            if tenant_snat_subnets and subnet['id'] in tenant_snat_subnets:
                LOG.debug(
                    'Remove subnet id %s from '
                    'bigip.assured_tenant_snat_subnets for tenant %s' %
                    (subnet['id'], tenant_id))
                tenant_snat_subnets.remove(subnet['id'])
            else:
                LOG.debug(
                    'Subnet id %s does not exist in '
                    'bigip.assured_tenant_snat_subnets for tenant %s' %
                    (subnet['id'], tenant_id))
        else:
            LOG.debug(
                'Tenant id %s does not exist in '
                'bigip.assured_tenant_snat_subnets' % tenant_id)

    def _delete_bigip_snats(self, bigip, subnetinfo, tenant_id):
        # Assure snats deleted in standalone mode """
        network = subnetinfo['network']
        subnet = subnetinfo['subnet']

        deleted_names = set()
        in_use_subnets = set()
        # Delete SNATs on traffic-group-local-only
        snat_name = self._get_snat_name(subnet, tenant_id)
        for i in range(self.driver.conf.f5_snat_addresses_per_subnet):
            index_snat_name = snat_name + "_" + str(i)
            if self.l2_service.is_common_network(network):
                tmos_snat_name = '/Common/' + index_snat_name
            else:
                tmos_snat_name = index_snat_name

            if self.l3_binding:
                snat_xlate = self.snat_translation_manager.load(
                    bigip, name=index_snat_name, partition=tenant_id)
                self.l3_binding.unbind_address(
                    subnet_id=subnet['id'], ip_address=snat_xlate.address)

            # Remove translation address from tenant snat pool
            # This seems strange that name and partition are tenant_id
            # but that is what the v1 code was doing.
            # The v1 code was also comparing basename in some cases
            # which seems dangerous because the folder may be in play?
            LOG.debug('Remove translation address from tenant SNAT pool')
            snatpool = self.snatpool_manager.load(bigip, tenant_id, tenant_id)
            snatpool.members = [
                member for member in snatpool.members
                if os.path.basename(member) != tmos_snat_name
            ]
            snatpool.update()

            # Delete snat pool if empty (no members)
            # In LBaaSv1 the snat.remove_from_pool() method did this if
            # there was only one member and it matched the one we were
            # deleting making this call basically useless, but the simplified
            # code above makes this still necessary and probably what the
            # original authors intended anyway since there is logging here
            # but not in the snat.py module from LBaaSv1
            LOG.debug('Check if snat pool is empty')
            if not snatpool.members:
                LOG.debug('Snat pool is empty - delete snatpool')
                snatpool.delete()

            # Check if subnet in use by any tenants/snatpools. If in use,
            # add subnet to hints list of subnets in use.
            self._remove_assured_tenant_snat_subnet(bigip, tenant_id, subnet)
            LOG.debug(
                'Check cache for subnet %s in use by other tenant' %
                subnet['id'])
            in_use_count = 0
            for loop_tenant_id in bigip.assured_tenant_snat_subnets:
                tenant_snat_subnets = \
                    bigip.assured_tenant_snat_subnets[loop_tenant_id]
                if subnet['id'] in tenant_snat_subnets:
                    LOG.debug(
                        'Subnet %s in use (tenant %s)' %
                        (subnet['id'], loop_tenant_id))
                    in_use_count += 1

            if in_use_count:
                in_use_subnets.add(subnet['id'])
            else:
                LOG.debug('Check subnet in use by any tenant')
                member_use_count = \
                    self.network_helper.get_snatpool_member_use_count(
                        bigip, subnet['id'])
                if member_use_count:
                    LOG.debug('Subnet in use - do not delete')
                    in_use_subnets.add(subnet['id'])
                else:
                    LOG.debug('Subnet not in use - delete')

            # Check if trans addr in use by any snatpool.  If not in use,
            # okay to delete associated neutron port.
            LOG.debug('Check trans addr %s in use.' % tmos_snat_name)
            in_use_count = \
                self.network_helper.get_snatpool_member_use_count(
                    bigip, tmos_snat_name)
            if not in_use_count:
                LOG.debug('Trans addr not in use - delete')
                deleted_names.add(index_snat_name)
            else:
                LOG.debug('Trans addr in use - do not delete')

        return deleted_names, in_use_subnets
