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
device_uuid = os.getenv("BALENA_DEVICE_UUID")

token_env_name = "BOOTSTRAP_API_KEY"
api_token = os.getenv(token_env_name)

LOG.info(f"balena fleet_id={fleet_id}")

balena_api_root = "https://api.balena-cloud.com/v6"


def balena_req(path, method="get", **kwargs):
    res = requests.request(
        method,
        f"{balena_api_root}{path}",
        headers={
            "authorization": f"Bearer {api_token}",
            "content-type": "application/json",
        },
        **kwargs,
    )
    res.raise_for_status()
    json = res.json()
    # Unwrap lists automatically
    return json["d"] if "d" in json else json


def balena_set_device_var(device_id, name, value):
    existing_var = next(
        iter(
            balena_req(
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
        balena_req(
            "/device_environment_variable",
            method="post",
            json={
                "device": device_id,
                "name": name,
                "value": value,
            },
        )
    elif existing_var["value"] != value:
        LOG.info(f"updating device var {name}={value}")
        balena_req(
            f"/device_environment_variable({existing_var['id']})",
            method="patch",
            json={
                "value": value,
            },
        )


def balena_set_fleet_var(name, value):
    existing_var = next(
        iter(
            balena_req(
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
        balena_req(
            "/application_environment_variable",
            method="post",
            json={
                "application": fleet_id,
                "name": name,
                "value": value,
            },
        )
    elif existing_var["value"] != value:
        LOG.info(f"updating fleet var {name}={value}")
        balena_req(
            f"/application_environment_variable({existing_var['id']})",
            method="patch",
            json={
                "value": value,
            },
        )


LOG.info("entering wait loop")
default_interval = 3600.0  # seconds


def process_loop():
    if not api_token:
        LOG.info("no bootstrap token detected, idling...")
        return

    if fleet_id == "1":
        LOG.error("contextualization is not supported in local dev mode.")
        return

    LOG.info("checking if bootstrap can continue")
    device = balena_req(f"/device?$filter=uuid eq '{device_uuid}'")[0]
    service_vars = balena_req(
        "/device_service_environment_variable?$filter="
        f"service_install/device eq {device['id']} and name eq '{token_env_name}'"
    )
    if len(service_vars) != 1:
        LOG.error(
            "there should be exactly 1 device with a service environment variable "
            f"{token_env_name} set for the k3s_context service."
        )
        return

    balena_set_device_var(device["id"], "K3S_ROLE", "server")
    balena_set_fleet_var("K3S_ROLE", "agent")
    device_ip = device["ip_address"].split()[0]
    balena_set_fleet_var("K3S_URL", f"https://{device_ip}:6443")
    try:
        with open("/var/lib/rancher/k3s/server/node-token", "r") as f:
            balena_set_fleet_var("K3S_TOKEN", f.read().strip())
    except OSError:
        LOG.info("waiting for node enroll token to appear")
        return 5.0
    else:
        # if we got here, we completed most setup successfully, slow down the
        # processing loop now.
        return 60.0


while True:
    next_interval = process_loop()
    time.sleep(next_interval or default_interval)
