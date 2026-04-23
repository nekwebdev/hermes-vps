{
  description = "Dev shell for OpenTofu + Just VPS bootstrap repository";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
      in {
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
          ];
        };
      });
}
