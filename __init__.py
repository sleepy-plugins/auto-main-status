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

CONFIG_FILE = 'data/auto_main_status_config.json'

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
        
        # 1. 注册 Hook
        plugin_manager.register_hook('device_activity', self.on_device_activity)
        
        # 2. 初始检查 (防止服务器启动时状态就不对)
        asyncio.create_task(self._perform_check())

    def on_unload(self):
        # PluginManager 目前没有 unregister_hook，但卸载插件时通常是整个应用关闭或重载
        pass

    def _save_config(self, enabled: bool):
        with open(self.config_path, 'w') as f:
            json.dump({'enabled': enabled}, f)

    def handle_enable(self, args):
        self._save_config(True)
        print("Automatic Main Status: ENABLED. (Restart server to apply if running)")

    def handle_disable(self, args):
        self._save_config(False)
        print("Automatic Main Status: DISABLED. (Restart server to apply if running)")

    def handle_status(self, args):
        print(f"Automatic Main Status: {'ENABLED' if self._load_config() else 'DISABLED'}")

    async def on_device_activity(self, *args, **kwargs):
        """
        当检测到设备活动时触发
        """
        if not self.enabled:
            return
            
        l.debug(f"Device activity detected from {kwargs.get('source', 'unknown')}, checking main status...")
        await self._perform_check()

    async def _perform_check(self):
        """执行逻辑检查"""
        # 使用 create_task 或者直接 await 都可以，这里直接 await 保证顺序
        try:
            with Session(engine) as sess:
                meta = sess.exec(select(m.Metadata)).first()
                if not meta: return

                # 查询在线设备数
                online_devices = sess.exec(select(m.DeviceData).where(m.DeviceData.using == True)).all()
                has_online = len(online_devices) > 0

                target_status = STATUS_AWAKE if has_online else STATUS_SLEEPY

                if meta.status != target_status:
                    old = meta.status
                    meta.status = target_status
                    meta.last_updated = time.time()
                    sess.add(meta)
                    sess.commit()
                    
                    l.info(f"[AutoMain] Status changed: {old} -> {target_status} (Triggered by Event)")
                    await manager.evt_broadcast('status_changed', {'status': target_status})
        
        except Exception as e:
            l.error(f"Error in auto main status update: {e}")
