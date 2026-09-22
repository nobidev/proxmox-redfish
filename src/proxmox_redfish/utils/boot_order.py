"""Boot order management utilities for the Proxmox Redfish daemon."""

from re import findall

from proxmoxer import ProxmoxAPI

from .meta import get_description, update_description
from ..config.logging_config import logger
from ..config.settings import BOOT_HD, BOOT_CD, BOOT_PXE
from ..proxmox.placement import vm


def get_current_boot(config):
    _, meta = get_description(config)
    order = meta.get("boot-persistent")
    if not order:
        boot = config.get("boot", "")
        order = ""
        m = findall(r"^order=(.+)$", boot)
        if m:
            order = m.pop()
    override = meta.get("boot-override")
    if not override:
        return order, None
    return order, (override.get("enabled", "Disabled"), override.get("target", "None"))


def build_boot_override_config(config, override=None, current=None, enabled=None, target=None):
    if current is None:
        current, _ = get_current_boot(config)
    r = {
        "boot": f"order={override}" if override else "",
    }
    if enabled is not None:
        if enabled == "Disabled":
            r["boot"] = f"order={current}" if current else ""
            r["description"] = update_description(config, meta={"boot-persistent": None, "boot-override": None})
        else:
            meta = {
                "boot-persistent": current,
                "boot-override": {
                    "enabled": enabled,
                    "target": target,
                },
            }
            r["description"] = update_description(config, meta=meta)
    return r


def clear_boot_override(proxmox: ProxmoxAPI, vm_id: int):
    config = vm(proxmox, vm_id).config.get()
    current, override = get_current_boot(config)
    override_enabled = "Disable"
    if override:
        override_enabled, _ = override
    if override_enabled == "Once":
        config_data = build_boot_override_config(config, current=current, enabled="Disabled")
        task = vm(proxmox, vm_id).config.post(**config_data)
        logger.debug(f"Clear override {override_enabled} boot: {task}")


def reorder_boot_order(proxmox: ProxmoxAPI, vm_id: int, current_order: str, target: str) -> str:
    """
    Reorder Proxmox boot devices based on Redfish target, preserving all devices including multiple hard drives.
    Returns the new boot order string for Proxmox config.
    """
    try:
        config = vm(proxmox, vm_id).config.get()
        if config is None:
            raise ValueError("Failed to retrieve VM configuration")

        # Parse current boot order
        devices = current_order.split(";") if current_order else []
        # Initialize device lists
        disk_devs = [BOOT_HD] if BOOT_HD else []
        cd_dev = BOOT_CD
        net_dev = BOOT_PXE

        # Check for hard drives and CD-ROMs (SCSI, SATA, IDE)
        for dev_type in ["scsi", "sata", "ide"]:
            for i in range(4):  # ide0-3, scsi0-3, sata0-3 (simplified range)
                dev_key = f"{dev_type}{i}"
                if dev_key in config:
                    dev_value = config[dev_key]
                    if "media=cdrom" in dev_value and cd_dev is None:
                        cd_dev = dev_key  # CD-ROM found
                    elif (dev_type in ["scsi", "sata"] or (dev_type == "ide" and "media=cdrom" not in dev_value)) and dev_key not in disk_devs:
                        disk_devs.append(dev_key)  # Hard drive found

        # Check for network devices
        if not net_dev:
            for i in range(4):  # net0-3 (simplified range)
                net_key = f"net{i}"
                if net_key in config:
                    net_dev = net_key
                    break

        # Build the full list of available devices, preserving all from config and current order
        available_devs = [d for d in devices if d in config] if devices else []
        for dev in disk_devs + ([cd_dev] if cd_dev else []) + ([net_dev] if net_dev else []):
            if dev and dev not in available_devs:
                available_devs.append(dev)

        # Validate the target device availability
        if target == "Pxe" and not net_dev:
            raise ValueError("No network device available for Pxe boot")
        elif target == "Cd" and not cd_dev:
            raise ValueError("No CD-ROM device available for Cd boot")
        elif target == "Hdd" and not disk_devs:
            raise ValueError("No hard disk device available for Hdd boot")

        # Reorder based on target, keeping all devices
        new_order = []
        if target == "Pxe" and net_dev:
            new_order = [net_dev] + [d for d in available_devs if d != net_dev]
        elif target == "Cd" and cd_dev:
            new_order = [cd_dev] + [d for d in available_devs if d != cd_dev]
        elif target == "Hdd" and disk_devs:
            primary_disk = disk_devs[0]
            new_order = [primary_disk] + [d for d in available_devs if d != primary_disk]
        else:
            # This should not be reached due to earlier validation
            new_order = available_devs

        # Remove duplicates and ensure valid devices only
        unique_devices = list(dict.fromkeys(new_order))
        result = ";".join(unique_devices) if unique_devices else ""
        logger.debug(f"Computed new boot order for VM {vm_id}: {result}")
        return result
    except Exception as e:
        logger.error(f"Failed to reorder boot order for VM {vm_id}: {str(e)}")
        raise
