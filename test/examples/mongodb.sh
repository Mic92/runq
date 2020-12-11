#!/bin/bash
. $(cd ${0%/*};pwd;)/../common.sh

case "$(uname -m)" in
    s390x)
        image=sinenomine/mongodb-s390x
        ;;
    *)
        image=mongo
        ;;
esac

name=$(rand_name)
disk=$PWD/disk$$
mkfs.xfs -dfile,name=$disk,size=200m

cleanup() {
    echo cleanup
    docker rm -f $name
    rm -f $disk
    myexit
}
trap cleanup EXIT

comment="MongoDB"

docker run \
    --runtime runq \
    --name $name \
    -e RUNQ_MEM=512 \
    -v $disk:/dev/runq/$(uuid)/none/xfs/data/db \
    -d \
    $image \
      mongod --logappend --dbpath /data/db

sleep 3

docker run \
    --runtime runq \
    --rm \
    --link $name:mongo-server \
    $image \
      mongo mongo-server/foo --eval 'db.version()'

checkrc $? 0 "$comment"

