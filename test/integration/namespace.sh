#!/bin/bash
. $(cd ${0%/*};pwd;)/../common.sh

comment="nsenter mnt"
docker run \
    --runtime runq \
    --name $(rand_name) \
    --rm \
    --cap-add sys_admin \
    $image  \
    nsenter --mount=/proc/self/ns/mnt /bin/hostname

checkrc $? 0 "$comment"

#
#
#
comment="entrypoint runs as PID 1"
cmd='exit $$'
docker run \
    --runtime runq \
    --name $(rand_name) \
    --rm \
    $image sh -c "$cmd"

checkrc $? 1 "$comment"

#
#
#
comment="trigger insmod via /proc/sys/kernel/modprobe"
cmd="mount -t xfs /foo /mnt 2>/dev/null; grep ^xfs /proc/modules"
docker run \
    --runtime runq \
    --name $(rand_name) \
    --rm \
    --cap-add sys_module \
    --cap-add sys_admin \
    $image sh -c "$cmd"

checkrc $? 0 "$comment"

myexit
