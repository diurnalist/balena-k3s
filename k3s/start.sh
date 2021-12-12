#!/bin/bash
set -o errexit
set -o nounset

# Balena will mount a socket and set DOCKER_HOST to
# point to the socket path.
# if [ -n "${DOCKER_HOST:-}" ]; then
#   echo "Shimming $DOCKER_HOST socket"
#   # for containerd
#   mkdir -p /run/k3s/containerd
#   ln -sf "${DOCKER_HOST##unix://}" /run/k3s/containerd/containerd.sock
#   # for Docker, if used instead
#   ln -sf "${DOCKER_HOST##unix://}" /var/run/docker.sock
# fi

#echo "Setting net.ipv4.ip_forward=1"
#echo 1>/proc/sys/net/ipv4/ip_forward

if [ -z "${K3S_URL:-}" ]; then
  echo "no K3S_URL variable set for device"
  exit 1
fi

declare -a cmd=(k3s)
case "${K3S_ROLE:-}" in
  server)
    cmd+=(server)
    ;;
  agent)
    if [ -z "${K3S_TOKEN:-}" ]; then
      echo "starting as agent role, but no enroll token available."
      exit 1
    fi
    cmd+=(agent)
    cmd+=(--kubelet-arg=cgroup-driver=systemd)
    cmd+=(--kubelet-arg=cgroups-per-qos=false)
    cmd+=(--kubelet-arg=enforce-node-allocatable=)
    cmd+=(--kubelet-arg=volume-plugin-dir=/opt/libexec/kubernetes/kubelet-plugins/volume/exec)
    ;;
  *)
    echo "unknown K3S_ROLE=${K3S_ROLE}. please set to one of 'server','agent'"
    exit 1
    ;;
esac

exec "${cmd[@]}" "$@"
