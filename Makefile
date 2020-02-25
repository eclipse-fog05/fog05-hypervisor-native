# -*-Makefile-*-


NATIVE_PLUGIN_DIR = /etc/fos/plugins/plugin-fdu-native
PLUGIN_CONF = $(NATIVE_PLUGIN_DIR)/native_plugin.json
SYSTEMD_DIR = /lib/systemd/system/
BIN_DIR = /usr/bin
UUID = $(shell ./to_uuid.sh)

clean:
	echo "Nothing to do..."

all:
	echo "Nothing to do..."

install:
	sudo pip3 install jinja2 psutil
ifeq "$(wildcard $(NATIVE_PLUGIN_DIR))" ""
	sudo cp -r ./templates $(NATIVE_PLUGIN_DIR)
	sudo cp ./__init__.py $(NATIVE_PLUGIN_DIR)
	sudo cp ./native_plugin $(NATIVE_PLUGIN_DIR)
	sudo cp ./NativeFDU.py $(NATIVE_PLUGIN_DIR)
	sudo cp ./README.md $(NATIVE_PLUGIN_DIR)
	sudo cp /etc/fos/plugins/plugin-fdu-native/fos_native.service $(SYSTEMD_DIR)
	sudo cp ./native_plugin.json $(PLUGIN_CONF)
else
	sudo cp -r ./templates $(NATIVE_PLUGIN_DIR)
	sudo cp ./__init__.py $(NATIVE_PLUGIN_DIR)
	sudo cp ./native_plugin $(NATIVE_PLUGIN_DIR)
	sudo cp ./NativeFDU.py $(NATIVE_PLUGIN_DIR)
	sudo cp ./README.md $(NATIVE_PLUGIN_DIR)
	sudo cp /etc/fos/plugins/plugin-fdu-native/fos_native.service $(SYSTEMD_DIR)
endif
	sudo cp /etc/fos/plugins/plugin-fdu-native/fos_lxd.service /lib/systemd/system/
	sudo sh -c "echo $(UUID) | xargs -i  jq  '.configuration.nodeid = \"{}\"' $(PLUGIN_CONF) > /tmp/native_plugin.tmp && mv /tmp/native_plugin.tmp $(PLUGIN_CONF)"

uninstall:
	sudo systemctl disable fos_native
	sudo rm -rf $(NATIVE_PLUGIN_DIR)
	sudo rm -rf /var/fos/native
	sudo rm $(SYSTEMD_DIR)/fos_native.service
