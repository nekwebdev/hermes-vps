{
  description = "Dev shell for OpenTofu + Just VPS bootstrap repository";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      nixpkgs,
      flake-utils,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
        pythonEnv = pkgs.python3.withPackages (
          ps: with ps; [
            pytest
            textual
          ]
        );
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            opentofu
            just
            openssh
            rsync
            jq
            curl
            gnugrep
            gawk
            coreutils
            bash
            shellcheck
            ruff
            gum
            hcloud
            linode-cli
            basedpyright
            uv
            git
            pythonEnv
          ];
        };
      }
    );
}
