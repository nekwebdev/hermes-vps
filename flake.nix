{
  description = "Dev shell for OpenTofu + Just VPS bootstrap repository";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-24.11";
    flake-utils.url = "github:numtide/flake-utils";
    hermes-agent = {
      url = "github:NousResearch/hermes-agent";
    };
  };

  outputs =
    {
      nixpkgs,
      flake-utils,
      hermes-agent,
      ...
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };
        hermesPkg = hermes-agent.packages.${system}.default;
        pythonEnv = pkgs.python3.withPackages (
          ps: with ps; [
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
            gum
            hcloud
            linode-cli
            hermesPkg
            pythonEnv
          ];
        };
      }
    );
}
