#!/usr/bin/env python
#
import logging
import os
import sys
import time

import requests

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
)
LOG = logging.getLogger("k3s_context")

fleet_id = os.getenv("BALENA_APP_ID")
fleet_name = os.getenv("BALENA_APP_NAME")
device_uuid = os.getenv("BALENA_DEVICE_UUID")
api_token = os.getenv("BALENA_API_TOKEN")
k3s_role = os.getenv("K3S_ROLE")

LOG.info(f"balena fleet_id={fleet_id}, fleet_name={fleet_name}, device={device_uuid}")

if fleet_id == "1":
    LOG.error("contextualization is not possible in local dev mode.")
    sys.exit(1)

balena_api_root = "https://api.balena-cloud.com/v6"


def balena_get(path):
    res = requests.get(
        f"{balena_api_root}{path}",
        headers={
            "authorization": f"Bearer {api_token}",
            "content-type": "application/json",
        },
    )
    res.raise_for_status()
    return res.json()


def balena_set_device_var(device_id, name, value):
    existing_var = next(
        iter(
            balena_get(
                (
                    "/device_environment_variable?$filter="
                    f"device eq {device_id} and name eq '{name}'"
                )
            )
        ),
        None,
    )
    if not existing_var:
        LOG.info(f"creating device var {name}={value}")
        res = requests.post(
            "/device_environment_variable",
            json={
                "device": device_id,
                "name": name,
                "value": value,
            },
        )
        res.raise_for_status()
    elif existing_var["value"] != value:
        LOG.info(f"updating device var {name}={value}")
        res = requests.patch(
            f"/device_environment_variable({existing_var['id']})",
            json={
                "value": value,
            },
        )
        res.raise_for_status()


def balena_set_fleet_var(name, value):
    existing_var = next(
        iter(
            balena_get(
                (
                    "/application_environment_variable?$filter="
                    f"application eq {fleet_id} and name eq '{name}'"
                )
            )
        ),
        None,
    )
    if not existing_var:
        LOG.info(f"creating fleet var {name}={value}")
        res = requests.post(
            "/application_environment_variable",
            json={
                "application": fleet_id,
                "name": name,
                "value": value,
            },
        )
        res.raise_for_status()
    elif existing_var["value"] != value:
        LOG.info(f"updating fleet var {name}={value}")
        res = requests.patch(
            f"/application_environment_variable({existing_var['id']})",
            json={
                "value": value,
            },
        )
        res.raise_for_status()


LOG.info("entering wait loop")
loop_interval = 5.0  # seconds
while True:
    if not k3s_role:
        LOG.info("no k3s role detected, checking if cluster is bootstrapped")
        fleet_devices = balena_get(
            f"/device?$filter=belongs_to__application eq {fleet_id}"
        )
        devices_with_server_role = [
            var["device"]
            for var in balena_get(
                (
                    "/device_environment_variable?$filter="
                    f"device in ({','.join(d['id'] for d in fleet_devices)})"
                )
            )
            if var["name"] == "K3S_ROLE" and var["value"] == "server"
        ]

        if not devices_with_server_role:
            # Pick the oldest online device to be the server.
            server_device = next(
                sorted(
                    (d for d in fleet_devices if d["is_online"] == True),
                    key=itemgetter("id"),
                ),
                None,
            )
            assert server_device is not None
            balena_set_device_var(server_device["id"], "K3S_ROLE", "server")
        else:
            # assume somehow the fleet var got deleted; we know there is
            # a server and it _should_ have set this var, but maybe somebody deleted it.
            balena_set_fleet_var("K3S_ROLE", "agent")

        break

    LOG.info(f"k3s_role={k3s_role}")

    if k3s_role == "server":
        device = balena_get(f"/device?$filter=uuid eq '{device_uuid}'")
        ip_addr = next(iter(device["ip_address"].split()), None)
        assert ip_addr is not None
        balena_set_fleet_var("K3S_URL", f"https://{ip_addr}:6443")
        balena_set_fleet_var("K3S_ROLE", "agent")
        # If we are the server, monitor the node token and ensure that fleet variables
        # are properly set.
        try:
            with open("/var/lib/rancher/k3s/server/node-token", "r") as f:
                balena_set_fleet_var("K3S_TOKEN", f.read())
        except OSError:
            LOG.info("waiting for node enroll token to appear")
            loop_interval = 5.0
        else:
            # if we got here, we completed most setup successfully, slow down the
            # processing loop now.
            loop_interval = 60.0
    else:
        # we are an agent, not much for us to do, set a longer interval
        loop_interval = 60.0

    time.sleep(loop_interval)
