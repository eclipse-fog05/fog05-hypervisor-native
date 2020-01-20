# -*-Makefile-*-


NATIVE_PLUGIN_DIR = /etc/fos/plugins/plugin-fdu-native
UUID = $(shell ./to_uuid.sh)
all:
	echo "Nothing to do..."

install:
	sudo pip3 install jinja2 psutil
ifeq "$(wildcard $(NATIVE_PLUGIN_DIR))" ""
	sudo cp -r ../plugin-fdu-native /etc/fos/plugins/
else
	sudo cp -r ../plugin-fdu-native/templates /etc/fos/plugins/plugin-fdu-native/
	sudo cp ../plugin-fdu-native/__init__.py /etc/fos/plugins/plugin-fdu-native/
	sudo cp ../plugin-fdu-native/native_plugin /etc/fos/plugins/plugin-fdu-native/
	sudo cp ../plugin-fdu-native/NativeFDU.py /etc/fos/plugins/plugin-fdu-native/
	sudo cp ../plugin-fdu-native/README.md /etc/fos/plugins/plugin-fdu-native/
	sudo cp /etc/fos/plugins/plugin-fdu-native/fos_native.service /lib/systemd/system/
	sudo ln -sf /etc/fos/plugins/plugin-fdu-native/native_plugin /usr/bin/fos_native
endif
	sudo cp /etc/fos/plugins/plugin-fdu-native/fos_lxd.service /lib/systemd/system/
	sudo sh -c "echo $(UUID) | xargs -i  jq  '.configuration.nodeid = \"{}\"' /etc/fos/plugins/plugin-fdu-native/native_plugin.json > /tmp/native_plugin.tmp && mv /tmp/native_plugin.tmp /etc/fos/plugins/plugin-fdu-native/native_plugin.json"

uninstall:
	sudo systemctl disable fos_native
	sudo rm -rf /etc/fos/plugins/plugin-fdu-native
	sudo rm -rf /var/fos/native
	sudo rm /lib/systemd/system/fos_native.service
	sudo rm -rf /usr/bin/fos_native
