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
          piperTts = pkgs.piper-tts.override {
            withAlignment = false;
            withHTTP = false;
            withTrain = false;
          };
          pipewireRuntime = pkgs.lib.optionals pkgs.stdenv.isLinux [ pkgs.pipewire ];
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
              pkgs.python3Packages.faster-whisper
              pkgs.python3Packages.httpx
              pkgs.python3Packages.numpy
              pkgs.python3Packages.ollama
              piperTts
              pkgs.python3Packages.silero-vad
              pkgs.python3Packages.sounddevice
              pkgs.python3Packages.soxr
              pkgs.python3Packages.pygobject3
              pkgs.gtk4
            ];

            nativeBuildInputs = [
              pkgs.wrapGAppsHook4
            ];

            nativeCheckInputs = [
              pkgs.python3Packages.pytestCheckHook
            ];

            preCheck = ''
              export GI_TYPELIB_PATH=${pkgs.lib.makeSearchPath "lib/girepository-1.0" [
                pkgs.gdk-pixbuf
                pkgs.gobject-introspection
                pkgs.graphene
                pkgs.gtk4
                pkgs.harfbuzz
                pkgs.pango.out
              ]}:''${GI_TYPELIB_PATH:-}
            '';

            makeWrapperArgs = pkgs.lib.optionals pkgs.stdenv.isLinux [
              "--prefix"
              "PATH"
              ":"
              (pkgs.lib.makeBinPath pipewireRuntime)
            ];
          };
        });

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/companion";
        };
        gui = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/companion-gui";
        };
      });

      devShells = forAllSystems (system:
        let
          pkgs = import nixpkgs {
            inherit system;
          };
          piperTts = pkgs.piper-tts.override {
            withAlignment = false;
            withHTTP = false;
            withTrain = false;
          };
          pipewireRuntime = pkgs.lib.optionals pkgs.stdenv.isLinux [ pkgs.pipewire ];

          python = pkgs.python3.withPackages (ps: [
            ps.pytest
            ps.faster-whisper
            ps.httpx
            ps.numpy
            ps.ollama
            ps.silero-vad
            ps.sounddevice
            ps.soxr
            ps.pygobject3
          ]);
        in
        {
          default = pkgs.mkShell {
            GI_TYPELIB_PATH = pkgs.lib.makeSearchPath "lib/girepository-1.0" [
              pkgs.gdk-pixbuf
              pkgs.gobject-introspection
              pkgs.graphene
              pkgs.gtk4
              pkgs.harfbuzz
              pkgs.pango.out
            ];
            packages = [
              python
              piperTts
              pkgs.gtk4
              pkgs.gobject-introspection
            ] ++ pipewireRuntime;
          };
        });

      checks = forAllSystems (system: {
        package = self.packages.${system}.default;
      });
    };
}
