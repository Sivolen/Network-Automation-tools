#!venv/bin/python3
from datetime import datetime, timedelta
from nornir_napalm.plugins.tasks import napalm_get
from nornir_utils.plugins.functions import print_result

# from nornir_netmiko.tasks import netmiko_send_command, netmiko_send_config

from nornir.core.exceptions import (
    ConnectionException,
    ConnectionAlreadyOpen,
    ConnectionNotOpen,
    NornirExecutionError,
    NornirSubTaskError,
)
from app import logger
from app.modules.helpers import Helpers

from app.modules.dbutils.db_utils import (
    get_last_config_for_device,
    write_config,
    update_device_env,
    update_device_status,
    get_device_id,
)

from app.utils import (
    check_ip,
    clear_line_feed_on_device_config,
    clear_clock_period_on_device_config,
)
from app.modules.differ import diff_changed
from config import (
    username,
    password,
    fix_clock_period,
    conn_timeout,
    fix_double_line_feed,
    fix_platform_list,
)

# nr_driver = Helpers()
drivers = Helpers(
    username=username,
    password=password,
    conn_timeout=conn_timeout,
)


# Generating timestamp for BD
now = datetime.now()
# Formatting date time
timestamp = now.strftime("%Y-%m-%d %H:%M")


# Start process backup configs
def backup_config_on_db(task: Helpers.nornir_driver) -> None:
    """
    This function starts a backup of the network equipment configuration
    Need for work nornir task
    """

    # Get ip address in task
    ipaddress = task.host.hostname
    if not check_ip(ipaddress):
        return

    # Get device id from db
    device_id = get_device_id(ipaddress=ipaddress)["id"]
    #
    device_result = None
    #
    try:
        # Get device information
        device_result = task.run(task=napalm_get, getters=["get_facts", "config"])
    except (
        ConnectionException,
        ConnectionAlreadyOpen,
        ConnectionNotOpen,
        NornirExecutionError,
        NornirSubTaskError,
    ) as connection_error:
        # Checking device exist on db
        logger.info(
            f"An error occurred on Device {device_id} ({ipaddress}): {connection_error}"
        )
        update_device_status(
            device_id=device_id,
            timestamp=timestamp,
            connection_status="Connection error",
        )

    # Collect device data
    hostname = device_result.result["get_facts"]["hostname"]
    vendor = device_result.result["get_facts"]["vendor"]
    model = device_result.result["get_facts"]["model"]
    os_version = device_result.result["get_facts"]["os_version"]
    sn = device_result.result["get_facts"]["serial_number"]
    platform = task.host.platform
    uptime = timedelta(seconds=device_result.result["get_facts"]["uptime"])

    # Checking if the variable sn is a list, if yes then we get the first argument
    if isinstance(sn, list) and sn != []:
        sn = sn[0]
    else:
        sn = "undefined"

    update_device_env(
        device_id=device_id,
        hostname=str(hostname),
        vendor=str(vendor),
        model=str(model),
        os_version=str(os_version),
        sn=str(sn),
        uptime=str(uptime),
        timestamp=str(timestamp),
        connection_status="Ok",
        connection_driver=str(platform),
    )

    # Get the latest configuration file from the database,
    # needed to compare configurations
    last_config = get_last_config_for_device(device_id=device_id)

    # Run the task to get the configuration from the device
    # device_config = task.run(task=napalm_get, getters=["config"])
    # candidate_config = device_config.result["config"]["running"]
    candidate_config = device_result.result["config"]["running"]

    # Some switches always change the parameter synchronization period in their configuration,
    # if you want this not to be taken into account when comparing,
    # enable fix_clock_period in the configuration
    if task.host.platform == "ios" and fix_clock_period is True:
        candidate_config = clear_clock_period_on_device_config(candidate_config)

    if task.host.platform in fix_platform_list and fix_double_line_feed is True:
        # Delete double line feed in device configuration for optimize config compare
        candidate_config = clear_line_feed_on_device_config(config=candidate_config)

    # Open last config
    if last_config is None:
        write_config(ipaddress=str(ipaddress), config=str(candidate_config))
        return
        # If the configs do not match or there are changes in the config,
        # save the configuration to the database
    last_config = last_config["last_config"]
    # Get diff result state if config equals pass
    diff_result = diff_changed(config1=candidate_config, config2=last_config)
    # If the configs do not match or there are changes in the config,
    # save the configuration to the database
    if not diff_result:
        write_config(ipaddress=str(ipaddress), config=str(candidate_config))

    # If the configs do not match or there are changes in the config,
    # save the configuration to the database
    # if result is False:
    #     write_config(ipaddress=str(ipaddress), config=str(device_config))


# This function initializes the nornir driver and starts the configuration backup process.
def run_backup() -> None:
    """
    This function initializes the nornir driver and starts the configuration backup process.
    return:
        None
    """
    # Start process
    try:
        with drivers.nornir_driver_sql() as nr_driver:
            result = nr_driver.run(
                name="Backup configurations", task=backup_config_on_db
            )
            # Print task result
            print_result(result, vars=["stdout"])
            # if you have error uncomment this row, and you see all result
            # print_result(result)
    except NornirExecutionError as connection_error:
        print(f"Process starts error {connection_error}")


# Main
def main() -> None:
    """
    Main function
    """
    run_backup()


# Start script
if __name__ == "__main__":
    main()
