{ pkgs ? import (fetchTarball "https://github.com/NixOS/nixpkgs/archive/fd9984fd9a950686e7271ecf01893987a42cdf14.tar.gz") {}
}:

let
  tini = pkgs.runCommandNoCC "tini" {} ''
    cp $(dirname $(dirname $(realpath ${pkgs.docker}/bin/dockerd)))/libexec/docker/docker-init $out
  '';
in
pkgs.mkShell {
  nativeBuildInputs = with pkgs; [
    bashInteractive
    go
    pkg-config
    mypy
  ];
  buildInputs = [ pkgs.libseccomp ];
  DOCKER_INIT = tini;
  makeFlags = [ "DOCKER_INIT=${tini}" ];
}
