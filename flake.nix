{
  description = "Local-first speech companion";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];

      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
          };
        in
        {
          default = pkgs.python3Packages.buildPythonApplication {
            pname = "companion";
            version = "0.1.0";

            pyproject = true;
            src = ./.;

            build-system = [
              pkgs.python3Packages.setuptools
            ];

            dependencies = [
              pkgs.python3Packages.silero-vad
              pkgs.python3Packages.sounddevice
            ];

            nativeCheckInputs = [
              pkgs.python3Packages.pytestCheckHook
            ];
          };
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/companion";
        };
      });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
          };

          python = pkgs.python3.withPackages (ps: [
            ps.pytest
            ps.silero-vad
            ps.sounddevice
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
            ];
          };
        });

      checks = forAllSystems (system: {
        package = self.packages.${system}.default;
      });
    };
}
