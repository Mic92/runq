#!/usr/bin/env python3

from dataclasses import dataclass
import sys

if sys.version_info < (3, 7, 0):
    print("This script assumes at least python3.7")
    sys.exit(1)

import tarfile
import os
import json
import time
from typing import IO, Any, Callable, List, Dict, Optional, Text, Iterator, Tuple
import subprocess
from contextlib import contextmanager, ExitStack
from pathlib import Path
import subprocess
import socket
from tempfile import TemporaryDirectory
from copy import deepcopy

from images import read_images, write_images, Image

ROOT = Path(__file__).parent.resolve()
BUILD_ROOT = ROOT.joinpath("build")
HAS_TTY = sys.stderr.isatty()

import inspect


def dbg():
    print(inspect.stack()[1][1], ":", inspect.stack()[1][2], ":", inspect.stack()[1][3])


def color_text(code: int, file: IO[Any] = sys.stdout) -> Callable[[str], None]:
    def wrapper(text: str) -> None:
        if HAS_TTY:
            print(f"\x1b[{code}m{text}\x1b[0m", file=file)
        else:
            print(text, file=file)

    return wrapper


warn = color_text(31, file=sys.stderr)
info = color_text(32)


def run(
    cmd: List[str],
    extra_env: Dict[str, str] = {},
    input: Optional[str] = None,
    stdout: Optional[int] = None,
    check: bool = True,
    cwd: str = str(ROOT),
) -> "subprocess.CompletedProcess[Text]":
    env = os.environ.copy()
    env.update(extra_env)
    env_string = []
    for k, v in extra_env.items():
        env_string.append(f"{k}={v}")
    info(" ".join(["$"] + env_string + cmd))
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        env=env,
        text=True,
        input=input,
        stdout=stdout,
    )


def build_runq() -> None:
    BUILD_ROOT.mkdir(exist_ok=True)
    version = run(["git", "rev-parse", "HEAD"], stdout=subprocess.PIPE)
    rev = version.stdout.strip()[:7]
    release_archive = BUILD_ROOT.joinpath(f"runq-{rev}.tar.gz")
    release_dir = BUILD_ROOT.joinpath(f"runq-release")

    if release_archive.exists():
        info(f"skip building {release_archive}")
    else:
        make_cmd = ["make", "release"]
        docker_init = os.environ.get("DOCKER_INIT")
        if docker_init:
            make_cmd += [f"DOCKER_INIT={docker_init}"]
        run(make_cmd)
        info(f"build {release_archive}")
        os.rename(ROOT.joinpath(release_archive.name), release_archive)

    if release_dir.joinpath("runq").exists():
        info(f"skip unpacking {release_archive}")
    else:
        release_dir.mkdir(exist_ok=True)
        run(
            [
                "tar",
                "-C",
                str(release_dir),
                "--strip-components=1",
                "-xf",
                str(release_archive),
            ]
        )
        run(
            [
                "bash",
                "mkcerts.sh",
            ],
            cwd=str(release_dir.joinpath("qemu")),
        )


def terminate(p: subprocess.Popen) -> None:
    run(["sudo", "kill", str(p.pid)])
    try:
        print(f"wait for process {p.pid} to finish")
        p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        run(["sudo", "kill", "-9", str(p.pid)])


@contextmanager
def run_dockerd(bridge: str) -> Iterator[None]:
    runq = BUILD_ROOT.joinpath("runq-release/runq")
    data = {
        "storage-driver": "devicemapper",
        "runtimes": {
            "runq": {
                "path": str(runq),
                "runtimeArgs": [
                    "--cpu",
                    "4",
                    "--mem",
                    "2048",
                    "--dns",
                    "8.8.8.8,8.8.4.4",
                    "--tmpfs",
                    "/tmp",
                ],
            }
        },
    }
    daemon_path = BUILD_ROOT.joinpath("daemon.json")
    with open(daemon_path, "w") as f:
        json.dump(data, f)
    sock_path = BUILD_ROOT.joinpath("docker.sock")
    docker_host = f"unix://{sock_path}"
    pid_file = BUILD_ROOT.joinpath("docker.pid")
    containerd_sock = BUILD_ROOT.joinpath("docker-containerd.sock")
    if pid_file.exists():
        with open(pid_file) as f:
            run(["sudo", "kill", "-9", f.read().strip()], check=False)
            run(["sudo", "rm", str(pid_file)], check=False)

    nix_cc = os.environ.get("NIX_CC")
    if nix_cc:
        # nix only
        with open(nix_cc + "/nix-support/dynamic-linker") as f:
            run(["patchelf", "--set-interpreter", f.read().strip(), str(runq)])

    data_root = BUILD_ROOT.joinpath("docker")

    cmd = [
        "sudo",
        "dockerd",
        "--bridge",
        bridge,
        "--pidfile",
        str(pid_file),
        "--config-file",
        str(daemon_path),
        "--containerd",
        str(containerd_sock),
        "-H",
        docker_host,
        f"--data-root={data_root}",
    ]
    containerd = ["sudo", "containerd", "--address", str(containerd_sock)]
    print(" ".join(cmd))

    with subprocess.Popen(containerd) as p1, subprocess.Popen(cmd) as p2:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        while True:
            try:
                client.connect(str(sock_path))
                client.close()
                break
            except OSError:
                res = p2.poll()
                if res != None:
                    print(f"dockerd terminated with {res}")
                    sys.exit(1)
                time.sleep(0.5)

        old = os.environ.copy()
        os.environ["DOCKER_HOST"] = docker_host
        try:
            yield
        finally:
            try:
                terminate(p2)
            finally:
                try:
                    terminate(p1)
                except OSError:
                    pass


@dataclass
class RunOption:
    docker_options: List[str]
    container_args: List[str]


def docker_run_options(image: Image, old_container: Dict[str, Any] = {}) -> RunOption:
    opts = []
    args = []
    config = old_container.get("Config")
    if config:
        opts.extend(["--workdir", config["WorkingDir"]])
        opts.extend(["--user", config.get("User", "root")])
        if config["Entrypoint"]:
            opts.extend(["--entrypoint", config["Entrypoint"][0]])
            args.extend(config["Entrypoint"][1:])
        if config["Cmd"]:
            args.extend(config["Cmd"])

        for e in config["Env"]:
            opts.extend(["--env", e])

    for m in image.mounts:
        from_path = ROOT.joinpath(m.from_path)
        opts.extend(["-v", f"{from_path}:{m.to_path}"])

    for e in image.envs:
        opts.extend(["-e", e])

    return RunOption(docker_options=opts, container_args=args)


@contextmanager
def run_container(
    image: Image,
    old_container: Dict[str, Any] = {},
    extra_options: List[str] = [],
    repo_digest: Optional[str] = None,
    name: Optional[str] = None,
    runtime: str = "runc",
) -> Iterator[Dict[str, Any]]:
    opts = docker_run_options(image, old_container)
    assert image.repo_digest is not None
    n = (name or image.name).replace(":", "-").replace("/", "-")
    subprocess.run(["docker", "rm", "-f", n], check=False)
    cmd = (
        ["docker", "run", f"--runtime={runtime}", "--name", n, "-d"]
        + extra_options
        + opts.docker_options
        + [repo_digest or image.repo_digest]
        + opts.container_args
    )
    proc = run(cmd, stdout=subprocess.PIPE)
    container_id = proc.stdout
    assert container_id is not None
    try:
        proc = run(["docker", "inspect", container_id.strip()], stdout=subprocess.PIPE)
        yield json.loads(proc.stdout)[0]
    finally:
        run(["docker", "rm", "-f", container_id], check=False)


@contextmanager
def run_container_instrumented(
    log_path: Path, repo_digest: str, image: Image, old_container: Dict[str, Any] = {}
) -> Iterator[Dict[str, Any]]:

    with ExitStack() as stack:
        sidecars = {}
        for sidecar in image.sidecars:
            sidecars[sidecar.name] = stack.enter_context(
                run_container(sidecar, name=f"{image.name}-{sidecar.name}")
            )

        image = deepcopy(image)
        for i, env in enumerate(image.envs):
            for n, sidecar in sidecars.items():
                image.envs[i] = env.replace(
                    "${" + n + "}", sidecar["NetworkSettings"]["IPAddress"]
                )

        # This is hacky but easy to implement
        if len(image.sidecars) > 0:
            info("wait for sidecars to boot")
            time.sleep(10)

        extra_options = ["-v", f"{log_path}:/.sysdig"]
        with run_container(
            image, old_container, extra_options, repo_digest, runtime="runq"
        ) as container:
            yield container


def wait_tcp_port(address: str, port: int) -> None:
    s = socket.socket()
    info(f"wait for {address}:{port}")
    while True:
        try:
            s.connect((address, port))
            s.close()
            return
        except OSError as e:
            time.sleep(0.1)


def probe_port(host: str, port: int, tempdir: Path, wget: bool):
    wait_tcp_port(host, port)
    if wget:
        wget_path = tempdir.joinpath("wget")
        wget_path.mkdir(exist_ok=True)
        run(
            [
                "wget",
                str(wget_path),
                "-q",
                "--mirror",
                "--page-requisites",
                "--no-parent",
                f"http://{host}:{port}",
            ],
            cwd=str(wget_path),
            check=False,
        )


def test_image(container: Dict[str, Any], image: Image, tempdir: Path) -> None:
    ip_address = container["NetworkSettings"]["IPAddress"]
    info(f"{image.name} -> {ip_address}")
    for spec in image.test_ports:
        probe_port(ip_address, spec.num, tempdir, spec.wget)


def get_bytes(p: Path) -> int:
    wc_proc = run(["wc", "-c", str(p)], stdout=subprocess.PIPE)
    assert wc_proc.stdout
    return int(wc_proc.stdout.split()[0])


def shrink_image(image: Image, tempdir: Path, log_path: Path) -> Tuple[str, int, int]:
    path_set = set(
        [
            b"/.dockerenv",
            # docker might need this to resolve username -> uid
            b"/etc/passwd",
            # poor mans elf interp tracking
            b"/lib/ld-musl-x86_64.so.1",
            b"/lib64/ld-linux-x86-64.so.2",
            b"/lib/x86_64-linux-gnu/ld-2.31.so",
            # hack for mongo-express
            b"/node_modules/mongo-express/public/images/favicon.ico",
        ]
    )
    with open(log_path.joinpath("logs"), "rb") as f:
        paths = f.read().split(b"\0")
        for p in paths:
            if not p.startswith(b"/"):
                continue
            path_set.add(p)
            print(p.decode("utf-8", errors="ignore"))

    export_name = tempdir.joinpath("export")
    reduced_name = tempdir.joinpath("reduced")
    # create a fresh container without any production traces
    digest = image.repo_digest
    assert digest is not None
    proc = run(["docker", "create", digest], stdout=subprocess.PIPE)
    export_id = proc.stdout.strip()
    try:
        run(["docker", "export", export_id, "-o", str(export_name)])
    finally:
        run(["docker", "rm", export_id])

    source = tarfile.open(name=export_name)
    symlink_tree = tempdir.joinpath("symlinks")
    shebangs = {}
    try:
        for entry in source:
            path = Path("/").joinpath(entry.name)
            path_str = str(path).encode("utf-8")
            if entry.issym():
                sym = symlink_tree.joinpath(entry.name)
                sym.parent.mkdir(exist_ok=True, parents=True)
                target = Path(entry.linkname)
                if target.is_absolute():
                    target = symlink_tree.joinpath(target.relative_to("/"))
                    target = Path(os.path.relpath(target, sym.parent))
                sym.symlink_to(target)
                continue
            elif not entry.isreg():
                continue

            dummy = symlink_tree.joinpath(entry.name)
            dummy.parent.mkdir(exist_ok=True, parents=True)
            open(dummy, "w").close()

            res = source.extractfile(entry)
            if not res:
                continue
            shebang = res.readline()
            if not shebang.startswith(b"#!"):
                continue

            # here we might include interpreters never executed
            # since we don't track if the file was executed
            shebang_interp = shebang[2:].split()[0]
            if not shebang_interp.startswith(b"/"):
                continue
            shebangs[entry.name] = shebang_interp

            if path_str in path_set:
                print(f"add shebang interpreter: {shebang_interp.decode('utf-8')}")
                path_set.add(shebang_interp)
                continue

    finally:
        source.close()

    for byte_p in list(path_set):
        p = Path(byte_p.decode("utf-8"))
        try:
            p = symlink_tree.joinpath(p.relative_to("/"))
        except ValueError:
            print(f"invalid shebang: {p}")
            continue
        if p.exists():
            new_p = p.resolve()
            if new_p == p:
                continue
            try:
                path = new_p.relative_to(symlink_tree)
            except ValueError:
                # ignore out-of-tree paths
                continue
            shebang = shebangs.get(str(path))
            if shebang:
                resolved = Path("/").joinpath(
                    symlink_tree.joinpath(shebang.decode("utf-8")[1:])
                    .resolve()
                    .relative_to(symlink_tree)
                )
                print(f"{shebang} -> {resolved}")
                path_set.add(str(resolved).encode("utf-8"))
            path_set.add(str(Path("/").joinpath(path)).encode("utf-8"))

    source = tarfile.open(name=export_name)
    destination = tarfile.open(name=reduced_name, mode="w")
    info("write new image")
    try:
        for entry in source:
            entry_name = str(Path("/").joinpath(entry.name))
            # just include all directories to have their permission
            # also fixes chdir into empty directories
            if entry.isdir() or entry.issym() or entry_name.encode("utf-8") in path_set:
                print(f"include {entry_name}")
                fileobj = None
                if entry.isreg():
                    fileobj = source.extractfile(entry)
                destination.addfile(entry, fileobj=fileobj)
            else:
                print(f"exclude {entry_name}")
    finally:
        source.close()
        destination.close()
    import_proc = run(["docker", "import", str(reduced_name)], stdout=subprocess.PIPE)
    new_image_id = import_proc.stdout.strip()
    info(f"new image id: {new_image_id}")
    old_size = get_bytes(export_name)
    new_size = get_bytes(reduced_name)
    return new_image_id, old_size, new_size


def analyze_image(image: Image):
    with TemporaryDirectory() as dir:
        info(f"analyze image {image.name}")
        tempdir = Path(dir)
        log_path = tempdir.joinpath("logs")
        log_path.mkdir()
        digest = image.repo_digest
        assert digest is not None
        with run_container_instrumented(log_path, digest, image) as container:
            test_image(container, image, tempdir)
            info("sleep for 10s to wait for container to load")
            time.sleep(10)
            run(["docker", "logs", container["Id"]])
            (image_id, old_size, new_size) = shrink_image(image, tempdir, log_path)
            old_container = container

        with run_container_instrumented(
            log_path, image_id, image, old_container
        ) as container:
            test_image(container, image, tempdir)
            run(["docker", "logs", container["Id"]])
        image.old_size = old_size
        image.new_size = new_size


@contextmanager
def create_bridge() -> Iterator[str]:
    name = "runq0"
    run(["sudo", "ip", "link", "del", name], check=False)
    run(["sudo", "ip", "link", "add", "name", name, "type", "bridge"])
    try:
        yield name
    finally:
        print("delete bridge")
        run(["sudo", "ip", "link", "del", name], check=False)


def main() -> None:
    images_path = ROOT.joinpath("images.json")
    images = read_images(images_path)
    build_runq()
    run(["sudo", "modprobe", "vhost_vsock"])
    with create_bridge() as br, run_dockerd(br):
        for image in images:
            if (image.old_size and image.new_size) or image.skip:
                print(f"skip {image.name}")
                continue
            analyze_image(image)
            write_images(images_path, images)


if __name__ == "__main__":
    main()
