# coding: utf-8

import asyncio
import json
import os
import time
import argparse
from sqlmodel import Session, select
from loguru import logger as l

from plugin import PluginBase, PluginMetadata, plugin_manager
from main import engine, manager
import models as m

CONFIG_FILE = 'auto_main_status_config.json'
STATUS_AWAKE = 0
STATUS_SLEEPY = 1

class Plugin(PluginBase):
    def __init__(self, metadata: PluginMetadata):
        super().__init__(metadata)
        self.config_path = os.path.join(os.path.dirname(__file__), CONFIG_FILE)
        self.enabled = self._load_config()

    def on_load(self):
        status_str = "Enabled" if self.enabled else "Disabled"
        l.info(f"{self.metadata.name} loaded. Automation is {status_str}.")
        
        plugin_manager.register_hook('device_activity', self.on_device_activity)

    async def on_startup(self):
        l.info(f"{self.metadata.name} performing initial check...")
        asyncio.create_task(self._perform_check())

    def _load_config(self) -> bool:
        if not os.path.exists(self.config_path):
            return True
        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)
                return data.get('enabled', True)
        except:
            return True

    def _save_config(self, enabled: bool):
        self.enabled = enabled # Update memory
        with open(self.config_path, 'w') as f:
            json.dump({'enabled': enabled}, f)

    def on_register_cli(self, subparsers: argparse._SubParsersAction):
        parser = subparsers.add_parser('auto-main', help='Configure automatic main status')
        sub = parser.add_subparsers(dest='action', required=True)

        sub.add_parser('enable', help='Enable automation').set_defaults(func=self.handle_enable)
        sub.add_parser('disable', help='Disable automation').set_defaults(func=self.handle_disable)
        sub.add_parser('status', help='Show automation status').set_defaults(func=self.handle_status)

    def handle_enable(self, args):
        self._save_config(True)
        print("Automatic Main Status: ENABLED.")

    def handle_disable(self, args):
        self._save_config(False)
        print("Automatic Main Status: DISABLED.")

    def handle_status(self, args):
        print(f"Automatic Main Status: {'ENABLED' if self._load_config() else 'DISABLED'}")

    async def on_device_activity(self, *args, **kwargs):
        if not self.enabled:
            return
        await self._perform_check()

    async def _perform_check(self):
        try:
            with Session(engine) as sess:
                meta = sess.exec(select(m.Metadata)).first()
                if not meta: return

                online_devices = sess.exec(select(m.DeviceData).where(m.DeviceData.using == True)).all()
                has_online = len(online_devices) > 0

                target_status = STATUS_AWAKE if has_online else STATUS_SLEEPY

                if meta.status != target_status:
                    old = meta.status
                    meta.status = target_status
                    meta.last_updated = time.time()
                    sess.add(meta)
                    sess.commit()
                    
                    l.info(f"[AutoMain] Status changed: {old} -> {target_status} (Online: {len(online_devices)})")
                    await manager.evt_broadcast('status_changed', {'status': target_status})
        
        except Exception as e:
            l.error(f"Error in auto main status update: {e}")
