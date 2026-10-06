# Monocypher 4.0.3 (vendored)

Ed25519 signature verification for signed node OTA manifests
(`lib/sp_core/ota_manifest.h`). It lives inside `sp_core` (compiled with it,
and shipped with it in every Builder ZIP) rather than as its own library. Only `crypto_ed25519_check` and what it
needs are linked into the device images (`--gc-sections` drops the rest);
the native tests also use `crypto_ed25519_key_pair` / `crypto_ed25519_sign`
to sign test manifests with the test-only key in
`test/fixtures/ota_manifest_vectors.json`.

| | |
|---|---|
| Upstream | https://monocypher.org, https://github.com/LoupVaillant/Monocypher |
| Release | 4.0.3, `monocypher-4.0.3.tar.gz` |
| Tarball SHA-512 | `40904ada5c7ee4f7741733e38b69a30a4b0561cbffba5ffe7c2dce16136d540251ec0d9056ff606510d3b5b708fb8a40db7e0870d4a0b2dc17ba2bfb880f8965` (matches the published `.sha512`; the monocypher.org and GitHub-release tarballs are byte-identical) |
| Licence | BSD-2-Clause or CC0-1.0, your choice (`LICENCE.md`) |

The four source files are copied **unmodified** from the tarball:
`src/monocypher.{c,h}` and `src/optional/monocypher-ed25519.{c,h}`.

| File | SHA-256 |
|---|---|
| `monocypher.c` | `57eb914fc88136119bd41655cccb8c250048bf54d470540625186f8ab16f64be` |
| `monocypher.h` | `c494da712122da7ff679fdcf318a5317e84972b6c950fe9d896212947797facd` |
| `monocypher-ed25519.c` | `60fce3578fb00b00da96490653d993c4cb427b1e1be38183285c66e04d22cc18` |
| `monocypher-ed25519.h` | `abc4fad381879f5c29176ebe014b9189956b3dfe0a3e36459b6990bc57212380` |

To upgrade: download the new release, check it against the published
SHA-512, copy the same four files and `LICENCE.md` here, update this table, and
run `pio test -e native -f test_core_ota_manifest` (RFC 8032 vectors plus
the shared manifest vectors).
