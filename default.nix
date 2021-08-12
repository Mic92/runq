with import <nixpkgs> {};

let
  tini = pkgs.runCommandNoCC "tini" {} ''
    cp $(dirname $(dirname $(realpath ${docker}/bin/dockerd)))/libexec/docker/docker-init $out
  '';
in
mkShell {
  nativeBuildInputs = [
    bashInteractive
    go
    pkg-config
  ];
  buildInputs = [ libseccomp ];
  DOCKER_INIT = tini;
  makeFlags = [ "DOCKER_INIT=${tini}" ];
}
