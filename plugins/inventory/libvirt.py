from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r'''
name: libvirt
plugin_type: inventory
extends_documentation_fragment:
    - constructed
short_description: Libvirt inventory source
description:
    - Get libvirt guests in an inventory source.
author:
    - Dave Olsthoorn <dave@bewaar.me>
version_added: "2.10"
options:
    plugin:
        description: Token that ensures this is a source file for the 'libvirt' plugin.
        required: True
        choices: ['libvirt', 'community.libvirt.libvirt']
    uri:
        description: Libvirt Connection URI
        required: True
        type: string
    inventory_hostname:
        description: |
            What to register as the inventory hostname.
            If set to 'uuid' the uuid of the server will be used and a
            group will be created for the server name.
            If set to 'name' the name of the server will be used unless
            there are more than one server with the same name in which
            case the 'uuid' logic will be used.
            Default is to do 'name'.
        type: string
        choices:
            - name
            - uuid
        default: "name"
    use_connection_plugin:
        description: Whether or not to use the connection plugin.
        type: boolean
        default: True
    filter:
        description: |
            Use a regex string filter out specific domains (by name or uuid;
            this depends on inventory_hostname).
        type: string
        default: ".*"
requirements:
    - "libvirt-python"
'''

EXAMPLES = r'''
# Connect to lxc host
plugin: community.libvirt.libvirt
uri: 'lxc:///'

# Connect to qemu
plugin: community.libvirt.libvirt
uri: 'qemu:///system'
'''

import re

from ansible.plugins.inventory import BaseInventoryPlugin, Constructable
from ansible.errors import AnsibleError
from ansible.module_utils.six import raise_from

try:
    import libvirt
except ImportError as imp_exc:
    LIBVIRT_IMPORT_ERROR = imp_exc
else:
    LIBVIRT_IMPORT_ERROR = None


class InventoryModule(BaseInventoryPlugin, Constructable):
    NAME = 'community.libvirt.libvirt'

    def parse(self, inventory, loader, path, cache=True):
        if LIBVIRT_IMPORT_ERROR:
            raise_from(
                AnsibleError('libvirt-python must be installed to use this plugin'),
                LIBVIRT_IMPORT_ERROR)

        super(InventoryModule, self).parse(
            inventory,
            loader,
            path,
            cache=cache
        )

        config_data = self._read_config_data(path)

        # set _options from config data
        self._consume_options(config_data)

        uri = self.get_option('uri')
        if not uri:
            raise AnsibleError("hypervisor uri not given")

        connection = libvirt.open(uri)
        if not connection:
            raise AnsibleError("hypervisor connection failure")

        # TODO(daveol)
        # make using connection plugins optional
        use_connection_plugin = self.get_option('use_connection_plugin')

        if use_connection_plugin:
            connection_plugin = dict({
                'LXC': 'community.libvirt.libvirt_lxc',
                'QEMU': 'community.libvirt.libvirt_qemu'
            }).get(connection.getType())

        # Set the domain filter.
        _filter = self.get_option('filter')

        for server in connection.listAllDomains():
            if not dict({
                   'uuid': re.match(_filter, server.UUIDString()),
                   'name': re.match(_filter, server.name())
               }).get(
                   self.get_option('inventory_hostname')
               ):
                continue

            inventory_hostname = dict({
                'uuid': server.UUIDString(),
                'name': server.name()
            }).get(
                self.get_option('inventory_hostname')
            )

            inventory_hostname_alias = dict({
                'name': server.UUIDString(),
                'uuid': server.name()
            }).get(
                self.get_option('inventory_hostname')
            )

            # TODO(daveol): Fix "Invalid characters were found in group names"
            # This warning is generated because of uuid's
            self.inventory.add_host(inventory_hostname)
            self.inventory.add_group(inventory_hostname_alias)
            self.inventory.add_child(inventory_hostname_alias, inventory_hostname)

            # Set the interface information.
            ifaces = {}

            for iface, iface_info in (connection.lookupByName(server.name())).interfaceAddresses(
                                      libvirt.VIR_DOMAIN_INTERFACE_ADDRESSES_SRC_LEASE).items():
                # Set interface hw address.
                ifaces[iface] = {
                  'hwaddr': iface_info['hwaddr'],
                  'addrs': []
                }

                if 'addrs' in iface_info:

                    # Append the addresses information to the interface dict.
                    ifaces[iface]['addrs'] = iface_info['addrs']

                    # Set the ansible_host variable to the first IP address found.
                    if not use_connection_plugin and len(iface_info['addrs']) >= 1 and \
                       'ansible_host' not in self.inventory.hosts[inventory_hostname].get_vars():
                        self.inventory.set_variable(
                            inventory_hostname,
                            'ansible_host',
                            iface_info['addrs'][0]['addr']
                        )

            if use_connection_plugin and connection_plugin is not None:
                self.inventory.set_variable(
                    inventory_hostname,
                    'ansible_libvirt_uri',
                    uri
                )
                self.inventory.set_variable(
                    inventory_hostname,
                    'ansible_connection',
                    connection_plugin
                )

            self.inventory.set_variable(
                inventory_hostname,
                'ansible_libvirt_ifaces',
                ifaces
            )

            # Get variables for compose
            variables = self.inventory.hosts[inventory_hostname].get_vars()

            # Set composed variables
            self._set_composite_vars(
                self.get_option('compose'),
                variables,
                inventory_hostname,
                self.get_option('strict'),
            )

            # Add host to composed groups
            self._add_host_to_composed_groups(
                self.get_option('groups'),
                variables,
                inventory_hostname,
                self.get_option('strict'),
            )

            # Add host to keyed groups
            self._add_host_to_keyed_groups(
                self.get_option('keyed_groups'),
                variables,
                inventory_hostname,
                self.get_option('strict'),
            )
